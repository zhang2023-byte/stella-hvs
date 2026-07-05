"""Agentic extraction runs (method C): tool-driven ReAct over packed context.

Pipeline ``stella-agentic-extraction/0.1``. Differences from the staged
direct-API pipeline (``extraction_run``, method B):

- The packed paper context is NOT pasted into the prompt. It becomes a
  read-only virtual file system exposed through tools (``list_files``,
  ``read_lines``, ``search``): the model decides what to look at, and only
  those slices enter the conversation. Everything the model can possibly
  see still comes from the same deterministic pack, so the context
  manifest remains the complete audit surface.
- Structure correctness is enforced at submission time: units end by
  calling ``submit_scaffold`` / ``submit_candidate`` / ``submit_review``,
  whose payloads are checked immediately (record ids, roster shape,
  method_ref targets) and rejected back into the loop as tool results.
- After the frozen validator gates the merged document, an independent
  reviewer model (default a different family than the extractor) audits
  each paper with the same read-only tools and files structured
  challenges; actionable challenges drive one extra targeted revision
  round, then the validator runs again.

Shared with method B (deliberately, for a fair comparison): the context
packer, the skeleton builder, the frozen validator and repair-round budget,
provenance enforcement, usage accounting, and the runs archive layout.
Requests are archived alongside responses (large message bodies are
digest-compressed) so a run can be audited without re-execution.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from stella.lit.llm_batch import chat_completion_raw, extract_json_object
from stella.lit.schema_templates import build_hvs_candidates_template

from .context_pack import PackedContext, pack_paper_context
from .extraction_run import (
    TASK_CLARIFICATIONS,
    batch_structure_errors,
    enforce_pipeline_fields,
    find_cjk_strings,
    load_frozen_validator,
    merge_document,
    route_errors,
    scaffold_step_ids,
    scaffold_structure_errors,
)

PIPELINE_NAME = "stella-agentic-extraction"
PIPELINE_VERSION = "0.1.1"

DEFAULT_REVIEWER_MODEL = "mimo-v2.5-pro"
DEFAULT_MAX_REPAIR_ROUNDS = 3

MAX_TOOL_CALLS = {"plan": 48, "candidate": 24, "repair": 16, "review": 48}
MAX_READ_LINES = 250
MAX_READ_CHARS = 30_000
MAX_SEARCH_HITS = 40
MAX_HISTORY_CHARS = 500_000
MAX_ARCHIVED_CONTENT_CHARS = 4_000
MAX_ERRORS_IN_FEEDBACK = 60

_REVIEW_SEVERITIES = {"high", "low"}


# --------------------------------------------------------------------------
# Virtual file system over the packed context


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
        # Numbered sections carry their own physical `N|` prefixes; slice by
        # those numbers when present so refs stay exact even after bib
        # filtering removed ranges.
        numbered = bool(lines) and bool(re.match(r"^\d+\|", lines[0]))
        if numbered:
            picked: list[str] = []
            for line in lines:
                match = re.match(r"^(\d+)\|", line)
                if match and start <= int(match.group(1)) <= end:
                    picked.append(line)
                elif not match and picked:
                    picked.append(line)  # omission markers inside the range
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


# --------------------------------------------------------------------------
# Prompts


def build_agentic_system_prompt(workspace: Path) -> str:
    skill_dir = workspace / "skills" / "hvs-candidates-extraction"
    parts = [
        "You are a scientific data-extraction agent for hypervelocity-star "
        "(HVS) literature. The paper's input files are NOT pasted into this "
        "conversation: explore them with the read-only tools (list_files, "
        "search, read_lines). Numbered files carry `N|` physical line-number "
        "prefixes; use those exact numbers in source_refs (the prefix itself "
        "is not part of the file content; `~~~ ... omitted ~~~` markers stand "
        "for uncited bibliography lines you do not need). Work stage by "
        "stage: each request names your task and the submit tool that ends "
        "it. Always finish by calling that submit tool; if your submission "
        "is rejected, fix the reported issues and submit again. Read enough "
        "context before submitting — evidence-free guesses fail validation. "
        "All free-text fields you write must be in English. Follow the "
        "extraction skill and schema reference below exactly.",
        "===== TASK CLARIFICATIONS =====",
        TASK_CLARIFICATIONS,
        "===== EXTRACTION SKILL =====",
        (skill_dir / "SKILL.md").read_text(encoding="utf-8"),
        "===== SCHEMA REFERENCE =====",
        (skill_dir / "references" / "schema.md").read_text(encoding="utf-8"),
        "===== COORDINATE FRAME REFERENCE =====",
        (skill_dir / "references" / "coordinate_frames.md").read_text(encoding="utf-8"),
    ]
    return "\n\n".join(parts)


def build_reviewer_system_prompt() -> str:
    return (
        "You are an independent scientific reviewer auditing an automated "
        "extraction of hypervelocity-star (HVS) candidates from one paper. "
        "You did not produce the extraction. Verify it against the paper's "
        "input files using the read-only tools (list_files, search, "
        "read_lines); numbered files carry `N|` physical line-number "
        "prefixes. Hunt specifically for: (1) candidates the paper treats "
        "as possibly unbound from the Milky Way that are MISSING from the "
        "extraction; (2) extracted objects that fail the inclusion "
        "boundary below (false inclusions); (3) values whose cited source "
        "lines do not actually support them; (4) wrong identifiers. "
        "Inclusion boundary: an object belongs in the extraction ONLY when "
        "the paper's own final treatment leaves it possibly unbound from "
        "the Milky Way. Challenge (severity high) every candidate whose "
        "cited evidence does not show that — a bare table row, a tabulated "
        "probability, survey membership, a generic velocity cutoff, or an "
        "inclusion_assessment with no paper-text support (e.g. "
        "galactic_bound_claim 'not_reported' and no unbound discussion) is "
        "NOT sufficient; re-assessed objects the paper concludes are bound "
        "must be challenged. Do not nitpick "
        "phrasing or style; report only checkable substantive problems. "
        "Finish by calling submit_review with your challenge list (empty "
        "list if the extraction is sound). All text in English."
    )


def plan_task_prompt(skeleton: dict, fs: ContextFS) -> str:
    return "\n\n".join(
        [
            "===== AVAILABLE INPUT FILES =====",
            json.dumps(fs.list_files(), ensure_ascii=False, indent=2),
            "===== SKELETON =====",
            json.dumps(skeleton, ensure_ascii=False, indent=2),
            "===== STAGE 1: SCAFFOLD AND ROSTER =====",
            "Explore the paper with the tools, then call submit_scaffold "
            "with the completed skeleton EXCEPT candidate details: fill "
            "`extraction` (status, summary), the full `method_chain`, and "
            "`candidate_groups_considered` exactly per the skill. For "
            "`candidates`, provide an EXHAUSTIVE roster of identifier "
            "stubs: one entry per object the paper treats as possibly "
            "unbound from the Milky Way, each containing ONLY the "
            "`identifiers` object (record_id, paper_candidate_id, "
            "gaia_source_id, all[] with source_refs). Never sample or "
            "truncate the roster, but apply the inclusion-boundary "
            "clarifications from the system prompt: completeness means "
            "every object the paper's own final treatment leaves possibly "
            "unbound, not every table row. Keep `schema_version`, `paper`, "
            "and `inputs` unchanged. The files listed above ARE the "
            "paper's source; do not use status 'source_missing'.",
        ]
    )


def candidate_task_prompt(scaffold: dict, stub: dict) -> str:
    scaffold_view = {
        "extraction": scaffold.get("extraction", {}),
        "method_chain": scaffold.get("method_chain", []),
        "candidate_groups_considered": scaffold.get("candidate_groups_considered", []),
    }
    return "\n\n".join(
        [
            "===== DOCUMENT SCAFFOLD (already fixed) =====",
            json.dumps(scaffold_view, ensure_ascii=False, indent=2),
            "===== STAGE 2: FILL THIS CANDIDATE =====",
            json.dumps({"roster_stub": stub}, ensure_ascii=False, indent=2),
            "Research this one object in the paper's input files, then call "
            "submit_candidate with one COMPLETE CandidateRecord for it: "
            "identical record_id, every quantity with raw_value/value, "
            "source_refs pointing at real lines/cells you actually read, "
            "and method_refs referencing the scaffold's existing step ids. "
            "Follow the skill and schema exactly.",
        ]
    )


def review_task_prompt(document: dict) -> str:
    compact = {
        "extraction": document.get("extraction", {}),
        "method_chain": document.get("method_chain", []),
        "candidates": document.get("candidates", []),
        "candidate_groups_considered": document.get("candidate_groups_considered", []),
    }
    return "\n\n".join(
        [
            "===== EXTRACTION UNDER REVIEW =====",
            json.dumps(compact, ensure_ascii=False),
            "===== REVIEW TASK =====",
            "Audit this extraction against the paper's input files. "
            "Candidates are indexed from 0 in the order shown. Call "
            "submit_review with {\"review\": {\"challenges\": [...], "
            "\"summary\": \"...\"}}. Each challenge: {\"candidate_index\": "
            "int (-1 for document-level issues such as a missing candidate), "
            "\"field\": str, \"issue\": str (specific and checkable, cite "
            "file:line evidence), \"severity\": \"high\"|\"low\"}. Use "
            "severity high only for wrong/missing candidates, wrong values, "
            "or unsupported source_refs.",
        ]
    )


# --------------------------------------------------------------------------
# ReAct unit runner


@dataclass
class AgenticResult:
    arxiv_id: str
    status: str
    plan_calls: int = 0
    candidate_calls: int = 0
    repair_calls: int = 0
    review_calls: int = 0
    repair_rounds: int = 0
    review_challenges: int = 0
    review_fix_targets: int = 0
    validator_errors: int = 0
    validator_warnings: int = 0
    cjk_paths: list[str] = field(default_factory=list)
    usage_totals: dict[str, int] = field(default_factory=dict)
    error: str = ""


def _accumulate_usage(totals: dict[str, int], usage: dict) -> None:
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key)
        if isinstance(value, int):
            totals[key] = totals.get(key, 0) + value
    details = usage.get("completion_tokens_details") or {}
    if isinstance(details.get("reasoning_tokens"), int):
        totals["reasoning_tokens"] = (
            totals.get("reasoning_tokens", 0) + details["reasoning_tokens"]
        )
    if isinstance(usage.get("prompt_cache_hit_tokens"), int):
        totals["prompt_cache_hit_tokens"] = (
            totals.get("prompt_cache_hit_tokens", 0)
            + usage["prompt_cache_hit_tokens"]
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
    """One tool-loop unit: plan, one candidate, one repair, or the review."""

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

    # -- history hygiene ---------------------------------------------------

    def _prune_history(self) -> None:
        total = sum(len(json.dumps(m, ensure_ascii=False)) for m in self.messages)
        if total <= MAX_HISTORY_CHARS:
            return
        # Keep system + task + the most recent exchanges; drop the oldest
        # assistant/tool turns until under budget. Tool-reply messages must
        # be dropped together with the assistant turn that requested them —
        # an orphaned role:"tool" message is invalid on OpenAI-style APIs.
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
                "content": "(earlier tool exchanges pruned for length; "
                "re-read anything you still need)",
            }
        ] + body

    # -- tool dispatch -----------------------------------------------------

    def _run_tool(self, name: str, arguments: dict) -> tuple[str, dict | None]:
        """Returns (tool reply text, accepted submission payload or None)."""

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

    # -- main loop ----------------------------------------------------------

    def run(self, *, extra_user: str | None = None, budget: int | None = None) -> dict | None:
        """Run the loop until an accepted submission or budget exhaustion."""

        if extra_user:
            self.messages.append({"role": "user", "content": extra_user})
        limit = budget if budget is not None else MAX_TOOL_CALLS[self.kind]
        calls_at_start = self.calls
        while self.calls - calls_at_start < limit:
            self._prune_history()
            self.calls += 1
            try:
                response = self.transport(
                    messages=self.messages,
                    extra_body={
                        **(self.transport_kwargs.get("extra_body") or {}),
                        "tools": self.tools,
                        "tool_choice": "auto",
                    },
                    **{
                        key: value
                        for key, value in self.transport_kwargs.items()
                        if key != "extra_body"
                    },
                )
            except Exception as exc:  # transport failure ends the unit
                raise RuntimeError(
                    f"{self.name}: {type(exc).__name__}: {exc}"
                ) from exc
            self.archive(f"{self.name}-call-{self.calls:02d}", response, self.messages)
            _accumulate_usage(self.usage_totals, response.get("usage") or {})
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
                # No tool call: try to salvage a direct JSON submission,
                # else nudge the model back onto the submit tool.
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
                reply, accepted = self._run_tool(
                    str(function.get("name") or ""), arguments
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


# --------------------------------------------------------------------------
# Review handling


def review_structure_errors(payload: dict) -> list[str]:
    challenges = payload.get("challenges")
    if not isinstance(challenges, list):
        return ['review must be {"challenges": [...], "summary": "..."}']
    errors: list[str] = []
    for index, challenge in enumerate(challenges):
        if not isinstance(challenge, dict):
            errors.append(f"challenges[{index}] must be an object")
            continue
        if not str(challenge.get("issue") or "").strip():
            errors.append(f"challenges[{index}].issue is required")
        severity = str(challenge.get("severity") or "")
        if severity not in _REVIEW_SEVERITIES:
            errors.append(
                f"challenges[{index}].severity must be one of "
                f"{sorted(_REVIEW_SEVERITIES)}"
            )
        if not isinstance(challenge.get("candidate_index"), int):
            errors.append(
                f"challenges[{index}].candidate_index must be an integer "
                "(-1 for document-level)"
            )
    return errors


def challenges_by_candidate(challenges: list[dict]) -> dict[int, list[str]]:
    grouped: dict[int, list[str]] = {}
    for challenge in challenges:
        if str(challenge.get("severity")) != "high":
            continue
        index = int(challenge.get("candidate_index", -1))
        text = f"{challenge.get('field') or 'candidate'}: {challenge.get('issue')}"
        grouped.setdefault(index, []).append(text)
    return grouped


# --------------------------------------------------------------------------
# Paper runner


def run_paper_agentic(
    *,
    workspace: Path,
    arxiv_id: str,
    run_dir: Path,
    api_key: str,
    base_url: str,
    model: str,
    reviewer_model: str,
    prompt_version: str,
    max_repair_rounds: int = DEFAULT_MAX_REPAIR_ROUNDS,
    timeout_seconds: int = 1800,
    request_extra: dict | None = None,
    reviewer_request_extra: dict | None = None,
    validator_module=None,
    transport: Callable[..., dict] | None = None,
) -> AgenticResult:
    transport = transport or chat_completion_raw
    validator = validator_module or load_frozen_validator(workspace)
    paper_dir = run_dir / arxiv_id
    attempts_dir = paper_dir / "attempts"
    attempts_dir.mkdir(parents=True, exist_ok=True)

    result = AgenticResult(arxiv_id=arxiv_id, status="failed")
    stage_log: list[dict] = []

    skeleton = build_hvs_candidates_template(
        literature_dir=workspace / "literature",
        arxiv_id=arxiv_id,
        workspace=workspace,
    ).copy()
    context = pack_paper_context(
        workspace, arxiv_id, list(skeleton["inputs"]["ecsv_paths"])
    )
    (paper_dir / "context_manifest.json").write_text(
        json.dumps(context.manifest(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    fs = ContextFS(context)

    def archive(name: str, response: dict, messages: list[dict]) -> None:
        (attempts_dir / f"{name}.response.json").write_text(
            json.dumps(response, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (attempts_dir / f"{name}.request.json").write_text(
            json.dumps(archive_request(messages), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )

    system_prompt = build_agentic_system_prompt(workspace)
    extractor_kwargs = {
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "temperature": 0,
        "timeout_seconds": timeout_seconds,
        "extra_body": dict(request_extra or {}),
    }
    reviewer_kwargs = {
        "api_key": api_key,
        "base_url": base_url,
        "model": reviewer_model,
        "temperature": 0,
        "timeout_seconds": timeout_seconds,
        "extra_body": dict(reviewer_request_extra or {}),
    }
    request_parameters: dict[str, Any] = {"temperature": 0}
    if request_extra:
        request_parameters.update(request_extra)
    request_parameters["reviewer_model"] = reviewer_model

    served_model = ""
    errors: list[str] = []
    warnings: list[str] = []
    cjk_paths: list[str] = []

    def make_unit(
        name: str,
        kind: str,
        task_prompt: str,
        submit_name: str,
        submit_key: str,
        submit_check: Callable[[dict], list[str]],
        *,
        reviewer: bool = False,
    ) -> ReactUnit:
        return ReactUnit(
            name=name,
            kind=kind,
            system_prompt=build_reviewer_system_prompt() if reviewer else system_prompt,
            task_prompt=task_prompt,
            fs=fs,
            submit_name=submit_name,
            submit_key=submit_key,
            submit_check=submit_check,
            transport=transport,
            transport_kwargs=reviewer_kwargs if reviewer else extractor_kwargs,
            archive=archive,
            usage_totals=result.usage_totals,
        )

    try:
        # ---- Stage 1: plan (scaffold + roster) ---------------------------
        plan_unit = make_unit(
            "plan",
            "plan",
            plan_task_prompt(skeleton, fs),
            "submit_scaffold",
            "document",
            lambda payload: scaffold_structure_errors(payload, arxiv_id),
        )
        scaffold = plan_unit.run()
        result.plan_calls = plan_unit.calls
        served_model = plan_unit.served_model or served_model
        if scaffold is None:
            result.status = "plan_failed"
            _write_report(paper_dir, result, [], stage_log)
            return result
        roster = scaffold["candidates"]
        step_ids = scaffold_step_ids(scaffold)
        stage_log.append({"stage": "plan", "calls": plan_unit.calls, "roster": len(roster)})

        # ---- Stage 2: per-candidate ReAct fills --------------------------
        candidate_units: list[ReactUnit] = []
        candidate_records: list[list[dict]] = []
        for index, stub in enumerate(roster):
            unit = make_unit(
                f"cand-{index:03d}",
                "candidate",
                candidate_task_prompt(scaffold, stub),
                "submit_candidate",
                "candidate",
                lambda payload, s=stub: batch_structure_errors(
                    {"candidates": [payload]}, [s], step_ids
                ),
            )
            record = unit.run()
            result.candidate_calls += unit.calls
            served_model = unit.served_model or served_model
            candidate_units.append(unit)
            if record is None:
                result.status = "candidate_failed"
                stage_log.append({"stage": f"cand-{index:03d}", "calls": unit.calls, "failed": True})
                _write_report(paper_dir, result, [], stage_log)
                return result
            candidate_records.append([record])
            stage_log.append({"stage": f"cand-{index:03d}", "calls": unit.calls})

        # ---- Merge + validate + targeted repair --------------------------
        document: dict = {}

        def validate_current() -> None:
            nonlocal document, errors, warnings, cjk_paths
            document = merge_document(scaffold, candidate_records)
            document = enforce_pipeline_fields(
                document,
                skeleton,
                served_model_id=served_model,
                requested_model=model,
                prompt_version=prompt_version,
                request_parameters=request_parameters,
                extracted_at=_dt.datetime.now().isoformat(timespec="seconds"),
            )
            report = validator.validate_hvs_candidates_report(
                document, workspace=workspace, require_complete=True
            )
            errors = list(report.errors)
            warnings = list(report.warnings)
            cjk_paths = find_cjk_strings(document)

        def targeted_repair(
            extra_by_candidate: dict[int, list[str]],
            scaffold_extra: list[str],
            label: str,
        ) -> None:
            nonlocal scaffold, step_ids, served_model
            if scaffold_extra:
                feedback = (
                    f"{label}: the merged document failed checks at the "
                    "document level. Fix these and call submit_scaffold "
                    "again with the corrected scaffold (NEVER renumber or "
                    "delete existing method_chain step ids; append new steps "
                    "at the end):\n"
                    + "\n".join(f"- {error}" for error in scaffold_extra[:MAX_ERRORS_IN_FEEDBACK])
                )
                plan_unit.submit_check = lambda payload: scaffold_structure_errors(
                    payload, arxiv_id, repair=True
                )
                repaired = plan_unit.run(
                    extra_user=feedback, budget=MAX_TOOL_CALLS["repair"]
                )
                result.repair_calls += plan_unit.calls - result.plan_calls
                result.plan_calls = plan_unit.calls
                if repaired is not None and len(repaired.get("candidates", [])) == len(roster):
                    scaffold = repaired
                    step_ids = scaffold_step_ids(scaffold)
            for index, issues in sorted(extra_by_candidate.items()):
                if not 0 <= index < len(candidate_units):
                    continue
                unit = candidate_units[index]
                feedback = (
                    f"{label}: your submitted candidate failed downstream "
                    "checks. Fix these and call submit_candidate again with "
                    "the complete corrected record:\n"
                    + "\n".join(f"- {issue}" for issue in issues[:MAX_ERRORS_IN_FEEDBACK])
                    + "\n\nCURRENT method_chain (method_refs must use these ids):\n"
                    + json.dumps(scaffold.get("method_chain", []), ensure_ascii=False)
                )
                calls_before = unit.calls
                record = unit.run(extra_user=feedback, budget=MAX_TOOL_CALLS["repair"])
                result.repair_calls += unit.calls - calls_before
                served_model = unit.served_model or served_model
                if record is not None:
                    candidate_records[index] = [record]

        validate_current()
        for round_index in range(max_repair_rounds):
            stage_log.append(
                {
                    "round": round_index,
                    "errors": len(errors),
                    "cjk": len(cjk_paths),
                    "errors_sample": errors[:15],
                }
            )
            if not errors and not cjk_paths:
                break
            result.repair_rounds = round_index + 1
            scaffold_errors, candidate_errors = route_errors(errors)
            for path in cjk_paths:
                match = re.match(r"^\$\.candidates\[(\d+)\]", path)
                if match:
                    candidate_errors.setdefault(int(match.group(1)), []).append(
                        f"non-English text at {path}; rewrite in English"
                    )
                else:
                    scaffold_errors.append(
                        f"non-English text at {path}; rewrite in English"
                    )
            targeted_repair(candidate_errors, scaffold_errors, "VALIDATION REPAIR")
            validate_current()

        # ---- Stage 3: independent review + one revision -------------------
        review_unit = make_unit(
            "review",
            "review",
            review_task_prompt(document),
            "submit_review",
            "review",
            review_structure_errors,
            reviewer=True,
        )
        review = review_unit.run()
        result.review_calls = review_unit.calls
        if review is not None:
            challenges = [c for c in review.get("challenges", []) if isinstance(c, dict)]
            result.review_challenges = len(challenges)
            (paper_dir / "review.json").write_text(
                json.dumps(review, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            grouped = challenges_by_candidate(challenges)
            document_level = grouped.pop(-1, [])
            result.review_fix_targets = len(grouped) + (1 if document_level else 0)
            if grouped or document_level:
                targeted_repair(grouped, document_level, "REVIEWER CHALLENGE")
                validate_current()
        else:
            stage_log.append({"stage": "review", "calls": review_unit.calls, "failed": True})

        stage_log.append(
            {"stage": "final", "errors": len(errors), "cjk": len(cjk_paths)}
        )
        (paper_dir / "literature_hvs_candidates.json").write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        result.validator_errors = len(errors)
        result.validator_warnings = len(warnings)
        result.cjk_paths = cjk_paths
        if errors:
            result.status = "validator_errors"
        elif cjk_paths:
            result.status = "ok_with_cjk_warnings"
        else:
            result.status = "ok"
    except RuntimeError as exc:
        result.error = str(exc)
        result.status = "transport_error"
    except Exception as exc:  # always leave a report behind for debugging
        result.error = f"{type(exc).__name__}: {exc}"
        result.status = "harness_error"
    _write_report(paper_dir, result, errors, stage_log)
    return result


def _write_report(
    paper_dir: Path,
    result: AgenticResult,
    errors: list[str],
    stage_log: list[dict],
) -> None:
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "report.json").write_text(
        json.dumps(
            {
                "arxiv_id": result.arxiv_id,
                "status": result.status,
                "plan_calls": result.plan_calls,
                "candidate_calls": result.candidate_calls,
                "repair_calls": result.repair_calls,
                "review_calls": result.review_calls,
                "repair_rounds": result.repair_rounds,
                "review_challenges": result.review_challenges,
                "review_fix_targets": result.review_fix_targets,
                "stage_log": stage_log,
                "validator_errors": errors,
                "validator_warnings_count": result.validator_warnings,
                "cjk_paths": result.cjk_paths,
                "usage_totals": result.usage_totals,
                "error": result.error,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
