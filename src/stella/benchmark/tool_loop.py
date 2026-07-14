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

MAX_TOOL_CALLS = {"plan": 48, "candidate": 24, "repair": 16, "review": 48}
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
        while self.calls - calls_at_start < limit:
            self._prune_history()
            self.calls += 1
            extra_body = {
                **(self.transport_kwargs.get("extra_body") or {}),
                "tools": self.tools,
                "tool_choice": "auto",
            }
            request_parent = None
            started = time.monotonic()
            if self.trace is not None:
                request_payload = build_chat_completion_payload(
                    model=str(self.transport_kwargs.get("model") or ""),
                    messages=self.messages,
                    temperature=self.transport_kwargs.get("temperature", 0),
                    max_tokens=self.transport_kwargs.get("max_tokens"),
                    extra_body=extra_body,
                )
                request_parent = self.trace.emit(
                    "llm.request.started",
                    paper_id=self.trace_paper_id,
                    stage=self.name,
                    summary=f"{self.kind} call {self.calls}",
                    data={"call": self.calls, "kind": self.kind},
                    payload_kind="llm.request",
                    payload=request_payload,
                )["seq"]
            try:
                response = self.transport(
                    messages=self.messages,
                    extra_body=extra_body,
                    **{
                        key: value
                        for key, value in self.transport_kwargs.items()
                        if key != "extra_body"
                    },
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
            if tool_calls:
                assistant_entry["tool_calls"] = tool_calls
            self.messages.append(assistant_entry)
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
            for tool_call in tool_calls:
                function = tool_call.get("function") or {}
                try:
                    arguments = json.loads(function.get("arguments") or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                tool_name = str(function.get("name") or "")
                tool_parent = None
                if self.trace is not None:
                    tool_parent = self.trace.emit(
                        "tool.call.started",
                        paper_id=self.trace_paper_id,
                        stage=self.name,
                        summary=tool_name,
                        payload_kind="tool.call",
                        payload={"name": tool_name, "arguments": arguments},
                    )["seq"]
                reply, accepted = self._run_tool(
                    tool_name, arguments
                )
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
        return None
