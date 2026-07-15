"""Shared read-only tool loop used by extraction and review stages."""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import TYPE_CHECKING, Any, Callable

from stella.lit.llm_batch import build_chat_completion_payload, extract_json_object

from .context_pack import PackedContext

if TYPE_CHECKING:
    from .run_trace import RunTrace

MAX_TOOL_CALLS = {"plan": 48, "candidate": 24, "repair": 16, "review": 32}
MAX_READ_LINES = 250
MAX_READ_CHARS = 30_000
MAX_SEARCH_HITS = 40
MAX_HISTORY_CHARS = 500_000
MAX_ARCHIVED_CONTENT_CHARS = 4_000
MAX_ERRORS_IN_FEEDBACK = 60


class ContextFS:
    """Read-only, line-addressed view of a packed paper context."""

    def __init__(self, context: PackedContext) -> None:
        self._lines: dict[str, list[str]] = {}
        self._kinds: dict[str, str] = {}
        body = context.text
        for item in context.files:
            self._kinds[item.path] = item.kind
        for section in re.split(r"^===== BEGIN ", body, flags=re.MULTILINE):
            if not section.strip() or "=====" not in section:
                continue
            header, _, rest = section.partition(" =====\n")
            path = header.strip()
            content = rest.rsplit("===== END ", 1)[0]
            if path in self._kinds:
                self._lines[path] = content.split("\n")

    def list_files(self) -> list[dict[str, Any]]:
        return [
            {
                "path": path,
                "kind": self._kinds.get(path, ""),
                "lines": len(lines),
            }
            for path, lines in self._lines.items()
        ]

    def read_lines(self, path: str, start_line: int, end_line: int) -> str:
        lines = self._lines.get(str(path))
        if lines is None:
            known = ", ".join(sorted(self._lines))
            return f"ERROR: unknown path {path!r}. Known files: {known}"
        try:
            start = max(1, int(start_line))
            end = int(end_line)
        except (TypeError, ValueError):
            return "ERROR: start_line and end_line must be integers"
        if end < start:
            return "ERROR: end_line must be >= start_line"
        if end - start + 1 > MAX_READ_LINES:
            end = start + MAX_READ_LINES - 1
        numbered = bool(lines) and bool(re.match(r"^\d+\|", lines[0]))
        if numbered:
            picked: list[str] = []
            for line in lines:
                match = re.match(r"^(\d+)\|", line)
                if match and start <= int(match.group(1)) <= end:
                    picked.append(line)
                elif not match and picked:
                    picked.append(line)
            body = "\n".join(picked)
        else:
            body = "\n".join(lines[start - 1 : end])
        if len(body) > MAX_READ_CHARS:
            body = body[:MAX_READ_CHARS] + "\n... (reply truncated; read a smaller range)"
        return body or "ERROR: empty range (file has fewer lines?)"

    def search(self, pattern: str, path: str = "") -> str:
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            return f"ERROR: bad regex: {exc}"
        hits: list[str] = []
        for file_path, lines in self._lines.items():
            if path and file_path != path:
                continue
            for line in lines:
                if regex.search(line):
                    hits.append(f"{file_path}:{line[:240]}")
                    if len(hits) >= MAX_SEARCH_HITS:
                        hits.append("... (hit cap reached; narrow the pattern)")
                        return "\n".join(hits)
        return "\n".join(hits) if hits else "no matches"


def read_tools_schema() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "List every available paper input file with its kind and line count.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_lines",
                "description": (
                    "Read a physical line range from one input file. Numbered "
                    "files keep their `N|` prefixes; use those exact numbers "
                    "in source_refs."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "start_line": {"type": "integer"},
                        "end_line": {"type": "integer"},
                    },
                    "required": ["path", "start_line", "end_line"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search",
                "description": (
                    "Case-insensitive regex search across input files (optionally "
                    "one file). Returns matching lines with their `N|` numbers."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                        "path": {"type": "string"},
                    },
                    "required": ["pattern"],
                },
            },
        },
    ]


def submit_tool_schema(name: str, description: str, payload_key: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {payload_key: {"type": "object"}},
                "required": [payload_key],
            },
        },
    }


def accumulate_usage(totals: dict[str, int], usage: dict) -> None:
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key)
        if isinstance(value, int):
            totals[key] = totals.get(key, 0) + value
    details = usage.get("completion_tokens_details") or {}
    if isinstance(details.get("reasoning_tokens"), int):
        totals["reasoning_tokens"] = (
            totals.get("reasoning_tokens", 0) + details["reasoning_tokens"]
        )
    cache_hits = usage.get("prompt_cache_hit_tokens")
    if not isinstance(cache_hits, int):
        prompt_details = usage.get("prompt_tokens_details") or {}
        cache_hits = prompt_details.get("cached_tokens")
    if isinstance(cache_hits, int):
        totals["prompt_cache_hit_tokens"] = (
            totals.get("prompt_cache_hit_tokens", 0)
            + cache_hits
        )


def _digest_content(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_ARCHIVED_CONTENT_CHARS:
        return {
            "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
            "chars": len(value),
            "head": value[:400],
        }
    return value


def archive_request(messages: list[dict]) -> list[dict]:
    archived = []
    for message in messages:
        entry = dict(message)
        if "content" in entry:
            entry["content"] = _digest_content(entry.get("content"))
        archived.append(entry)
    return archived


class ReactUnit:
    """One bounded read-only tool loop ending in a validated submit call."""

    def __init__(
        self,
        *,
        name: str,
        kind: str,
        system_prompt: str,
        task_prompt: str,
        fs: ContextFS,
        submit_name: str,
        submit_key: str,
        submit_check: Callable[[dict], list[str]],
        transport: Callable[..., dict],
        transport_kwargs: dict,
        archive: Callable[[str, dict, list[dict]], None],
        usage_totals: dict[str, int],
        trace: RunTrace | None = None,
        trace_paper_id: str = "",
        stream_responses: bool = False,
        finalization_calls: int = 0,
        stall_on_repeated_tool_batch: bool = False,
    ) -> None:
        self.name = name
        self.kind = kind
        self.fs = fs
        self.submit_name = submit_name
        self.submit_key = submit_key
        self.submit_check = submit_check
        self.transport = transport
        self.transport_kwargs = transport_kwargs
        self.archive = archive
        self.usage_totals = usage_totals
        self.trace = trace
        self.trace_paper_id = trace_paper_id
        self.stream_responses = stream_responses
        self.finalization_calls = max(0, int(finalization_calls))
        self.stall_on_repeated_tool_batch = stall_on_repeated_tool_batch
        self.stop_reason = ""
        self.failure_reason = ""
        self.messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task_prompt},
        ]
        self.calls = 0
        self.served_model = ""
        self.tools = read_tools_schema() + [
            submit_tool_schema(
                submit_name,
                f"Submit your finished {kind} payload. Ends the task when accepted.",
                submit_key,
            )
        ]

    def _prune_history(self) -> None:
        total = sum(len(json.dumps(m, ensure_ascii=False)) for m in self.messages)
        if total <= MAX_HISTORY_CHARS:
            return
        head, body = self.messages[:2], self.messages[2:]
        while body and total > MAX_HISTORY_CHARS:
            dropped = body.pop(0)
            total -= len(json.dumps(dropped, ensure_ascii=False))
            while body and body[0].get("role") == "tool":
                orphan = body.pop(0)
                total -= len(json.dumps(orphan, ensure_ascii=False))
        self.messages = head + [
            {
                "role": "user",
                "content": "(earlier tool exchanges pruned for length; re-read anything you still need)",
            }
        ] + body

    def _run_tool(self, name: str, arguments: dict) -> tuple[str, dict | None]:
        if name == "list_files":
            return json.dumps(self.fs.list_files(), ensure_ascii=False), None
        if name == "read_lines":
            return (
                self.fs.read_lines(
                    str(arguments.get("path", "")),
                    arguments.get("start_line", 1),
                    arguments.get("end_line", 1),
                ),
                None,
            )
        if name == "search":
            return (
                self.fs.search(
                    str(arguments.get("pattern", "")),
                    str(arguments.get("path", "")),
                ),
                None,
            )
        if name == self.submit_name:
            payload = arguments.get(self.submit_key)
            if not isinstance(payload, dict):
                return (
                    f"REJECTED: {self.submit_name} needs a JSON object under "
                    f"the {self.submit_key!r} key",
                    None,
                )
            errors = self.submit_check(payload)
            if errors:
                shown = errors[:MAX_ERRORS_IN_FEEDBACK]
                return (
                    "REJECTED, fix these and submit again:\n"
                    + "\n".join(f"- {error}" for error in shown),
                    None,
                )
            return "ACCEPTED", payload
        return f"ERROR: unknown tool {name!r}", None

    def run(
        self, *, extra_user: str | None = None, budget: int | None = None
    ) -> dict | None:
        if extra_user:
            self.messages.append({"role": "user", "content": extra_user})
        limit = budget if budget is not None else MAX_TOOL_CALLS[self.kind]
        calls_at_start = self.calls
        research_limit = max(0, limit - self.finalization_calls)
        finalizing = False
        finalization_used = 0
        previous_tool_batch = ""

        def enter_finalization(reason: str) -> None:
            nonlocal finalizing
            if finalizing:
                return
            finalizing = True
            self.stop_reason = reason
            self.messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Research has stopped ({reason}). Do not call any "
                        f"read tool. Use the evidence already collected and call "
                        f"{self.submit_name} now. Submit an empty challenge list "
                        "if no substantive problem was established."
                    ),
                }
            )

        while self.calls - calls_at_start < limit:
            if (
                self.finalization_calls
                and not finalizing
                and self.calls - calls_at_start >= research_limit
            ):
                enter_finalization(f"{self.kind}_research_budget_exhausted")
            if finalizing and finalization_used >= self.finalization_calls:
                break
            self._prune_history()
            self.calls += 1
            extra_body = {
                **(self.transport_kwargs.get("extra_body") or {}),
                "tools": self.tools,
                "tool_choice": (
                    {
                        "type": "function",
                        "function": {"name": self.submit_name},
                    }
                    if finalizing
                    else "auto"
                ),
            }
            if finalizing:
                finalization_used += 1
            request_parent = None
            call_id = f"{self.trace_paper_id}:{self.name}:{self.calls}"
            started = time.monotonic()
            if self.trace is not None:
                request_extra = dict(extra_body)
                if self.stream_responses:
                    request_extra.update(
                        {"stream": True, "stream_options": {"include_usage": True}}
                    )
                request_payload = build_chat_completion_payload(
                    model=str(self.transport_kwargs.get("model") or ""),
                    messages=self.messages,
                    temperature=self.transport_kwargs.get("temperature", 0),
                    max_tokens=self.transport_kwargs.get("max_tokens"),
                    extra_body=request_extra,
                )
                request_parent = self.trace.emit(
                    "llm.request.started",
                    paper_id=self.trace_paper_id,
                    stage=self.name,
                    summary=f"{self.kind} call {self.calls}",
                    data={"call": self.calls, "kind": self.kind},
                    payload_kind="llm.request",
                    payload=request_payload,
                    call_id=call_id,
                    node_id=self.name,
                    source_node_id=self.name,
                    target_node_id="provider",
                    attempt=1,
                )["seq"]
            stream_callback = None
            if self.trace is not None and self.stream_responses:
                from .run_trace import stream_trace_callback

                stream_callback = stream_trace_callback(
                    self.trace,
                    paper_id=self.trace_paper_id,
                    stage=self.name,
                    call_id=call_id,
                    parent_seq=request_parent,
                )
            try:
                call_kwargs = {
                    key: value
                    for key, value in self.transport_kwargs.items()
                    if key != "extra_body"
                }
                if self.stream_responses:
                    call_kwargs.update(
                        {"stream": True, "on_stream_event": stream_callback}
                    )
                response = self.transport(
                    messages=self.messages,
                    extra_body=extra_body,
                    **call_kwargs,
                )
            except Exception as exc:
                if self.trace is not None:
                    self.trace.emit(
                        "llm.request.failed",
                        paper_id=self.trace_paper_id,
                        stage=self.name,
                        status="failed",
                        summary=f"{type(exc).__name__}: {exc}",
                        duration_ms=int((time.monotonic() - started) * 1000),
                        parent_seq=request_parent,
                        call_id=call_id,
                        node_id=self.name,
                        source_node_id="provider",
                        target_node_id=self.name,
                    )
                raise RuntimeError(
                    f"{self.name}: {type(exc).__name__}: {exc}"
                ) from exc
            self.archive(f"{self.name}-call-{self.calls:02d}", response, self.messages)
            accumulate_usage(self.usage_totals, response.get("usage") or {})
            if self.trace is not None:
                from .run_trace import response_trace_metadata

                self.trace.emit(
                    "llm.response.completed",
                    paper_id=self.trace_paper_id,
                    stage=self.name,
                    status="completed",
                    data={"call": self.calls, **response_trace_metadata(response)},
                    payload_kind="llm.response",
                    payload=response,
                    usage=response.get("usage") or {},
                    duration_ms=int((time.monotonic() - started) * 1000),
                    parent_seq=request_parent,
                    call_id=call_id,
                    node_id=self.name,
                    source_node_id="provider",
                    target_node_id=self.name,
                )
                requested_model = str(self.transport_kwargs.get("model") or "")
                served_model = str(response.get("model") or "")
                if served_model and requested_model and served_model != requested_model:
                    self.trace.emit(
                        "llm.served_model.changed",
                        paper_id=self.trace_paper_id,
                        stage=self.name,
                        status="completed",
                        data={
                            "requested_model": requested_model,
                            "served_model": served_model,
                        },
                        parent_seq=request_parent,
                        call_id=call_id,
                        node_id=self.name,
                        source_node_id="provider",
                        target_node_id=self.name,
                    )
            if response.get("model"):
                self.served_model = str(response["model"])
            choice = (response.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            tool_calls = message.get("tool_calls") or []
            assistant_entry: dict[str, Any] = {
                "role": "assistant",
                "content": message.get("content") or "",
            }
            if message.get("reasoning_content"):
                assistant_entry["reasoning_content"] = message["reasoning_content"]
            if tool_calls:
                assistant_entry["tool_calls"] = tool_calls
            self.messages.append(assistant_entry)
            length_exhausted = (
                self.finalization_calls
                and not finalizing
                and str(choice.get("finish_reason") or "") == "length"
            )
            if not tool_calls:
                content = str(message.get("content") or "")
                try:
                    parsed = extract_json_object(content)
                except (ValueError, json.JSONDecodeError):
                    parsed = None
                if isinstance(parsed, dict):
                    payload = parsed.get(self.submit_key, parsed)
                    if isinstance(payload, dict) and not self.submit_check(payload):
                        return payload
                if length_exhausted:
                    enter_finalization(f"{self.kind}_length_exhausted")
                    continue
                self.messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"You must finish by calling {self.submit_name} "
                            "(or another tool to keep researching). Plain "
                            "text replies are not accepted."
                        ),
                    }
                )
                continue

            parsed_calls: list[tuple[dict, str, dict]] = []
            for tool_call in tool_calls:
                function = tool_call.get("function") or {}
                try:
                    arguments = json.loads(function.get("arguments") or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                parsed_calls.append(
                    (tool_call, str(function.get("name") or ""), arguments)
                )
            non_submit_batch = [
                {"name": name, "arguments": arguments}
                for _, name, arguments in parsed_calls
                if name != self.submit_name
            ]
            repeated_batch = False
            if (
                self.stall_on_repeated_tool_batch
                and not finalizing
                and non_submit_batch
                and len(non_submit_batch) == len(parsed_calls)
            ):
                signature = json.dumps(
                    non_submit_batch,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                repeated_batch = signature == previous_tool_batch
                previous_tool_batch = signature

            for tool_call, tool_name, arguments in parsed_calls:
                tool_parent = None
                if self.trace is not None:
                    tool_parent = self.trace.emit(
                        "tool.call.started",
                        paper_id=self.trace_paper_id,
                        stage=self.name,
                        summary=tool_name,
                        payload_kind="tool.call",
                        payload={"name": tool_name, "arguments": arguments},
                        call_id=str(tool_call.get("id") or call_id),
                        node_id=self.name,
                        source_node_id=self.name,
                        target_node_id=f"tool:{tool_name}",
                    )["seq"]
                if finalizing and tool_name != self.submit_name:
                    reply, accepted = (
                        f"REJECTED: finalization is active; call {self.submit_name}",
                        None,
                    )
                elif repeated_batch and tool_name != self.submit_name:
                    reply, accepted = (
                        f"STOPPED: repeated tool batch; call {self.submit_name}",
                        None,
                    )
                else:
                    reply, accepted = self._run_tool(tool_name, arguments)
                if self.trace is not None:
                    self.trace.emit(
                        "tool.call.completed",
                        paper_id=self.trace_paper_id,
                        stage=self.name,
                        status="accepted" if accepted is not None else "completed",
                        summary=tool_name,
                        payload_kind="tool.result",
                        payload={"name": tool_name, "result": reply},
                        parent_seq=tool_parent,
                        call_id=str(tool_call.get("id") or call_id),
                        node_id=self.name,
                        source_node_id=f"tool:{tool_name}",
                        target_node_id=self.name,
                    )
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.get("id") or "",
                        "content": reply,
                    }
                )
                if accepted is not None:
                    return accepted
            if repeated_batch:
                enter_finalization(f"{self.kind}_repeated_tool_stall")
            elif length_exhausted:
                enter_finalization(f"{self.kind}_length_exhausted")
        if self.finalization_calls:
            reason = self.stop_reason or f"{self.kind}_research_budget_exhausted"
            self.stop_reason = reason
            self.failure_reason = (
                f"{self.kind}_submission_missing ({reason}): no valid "
                f"{self.submit_name} payload after "
                f"{self.calls - calls_at_start} calls"
            )
        return None
