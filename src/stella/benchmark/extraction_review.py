"""Method-specific independent-review stages for benchmark methods B/C."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from stella.lit.llm_batch import build_chat_completion_payload, extract_json_object
from stella.lit.extraction_rules import render_rule_profile

from .context_pack import PackedContext
from .run_trace import response_trace_metadata, stream_trace_callback
from .task_surfaces import CORE_PROV, FULL, get_task_surface
from .tool_loop import ContextFS, ReactUnit, accumulate_usage

if TYPE_CHECKING:
    from .run_trace import RunTrace

DEFAULT_REVIEWER_MODEL = "glm-5.2"
DEFAULT_REVIEWER_PROVIDER_ORDER = ("bigmodel",)
REVIEW_ACTIONABLE_SEVERITY = "high"
REVIEW_REVISION_ROUNDS = 1
WORKFLOW_REVIEW_RETRIES = 2
AGENTIC_REVIEW_FINALIZATION_CALLS = 2
_REVIEW_SEVERITIES = {"high", "low"}


def _review_surface_sections(workspace: Path, task_surface: str) -> list[str]:
    surface = get_task_surface(task_surface)
    return [
        f"===== TASK SURFACE UNDER REVIEW: {surface.id} =====",
        surface.instruction,
        (
            "The enrichment groups are intentionally empty on this surface. "
            "Do not challenge their absence and do not request enrichment."
            if task_surface == CORE_PROV
            else "Review all populated core and enrichment fields."
        ),
        "===== REVIEW RULE PROFILE: hvs_reviewer =====",
        render_rule_profile(workspace, "hvs_reviewer", "prompt"),
    ]


def build_workflow_reviewer_system_prompt(
    workspace: Path, task_surface: str = FULL
) -> str:
    return "\n\n".join(
        [
            "You are an independent scientific reviewer auditing an automated "
            "extraction of hypervelocity-star (HVS) candidates from one paper. "
            "This is a fixed workflow step, not an agent task: every permitted "
            "paper input is included in the user message and no tools are "
            "available. Review the complete supplied evidence once. Prioritize "
            "candidate completeness and inclusion, identity, high-impact values, "
            "and source references. Do not repeatedly pursue low-severity "
            "ambiguities or nitpick prose. Return only one JSON object with a "
            "top-level `review` field. Use an empty challenge list when no "
            "substantive problem is established. All text in English.",
            *_review_surface_sections(workspace, task_surface),
        ]
    )


def build_agentic_reviewer_system_prompt(
    workspace: Path, task_surface: str = FULL
) -> str:
    return "\n\n".join(
        [
            "You are an independent scientific reviewer auditing an automated "
            "extraction of hypervelocity-star (HVS) candidates from one paper. "
            "You did not produce the extraction. Verify it against the paper's "
            "input files using the read-only tools (list_files, search, "
            "read_lines); numbered files carry `N|` physical line-number "
            "prefixes. Start with the candidate roster and high-impact fields; "
            "stop exploring when the evidence is sufficient. Do not repeat an "
            "identical read/search call and do not spend calls resolving "
            "low-severity ambiguity. Hunt specifically for missing candidates, "
            "false inclusions, unsupported values, and wrong identifiers. Do not "
            "nitpick phrasing or style; report only checkable substantive "
            "problems. Finish by calling submit_review with your challenge list "
            "(empty if the extraction is sound). All text in English.",
            *_review_surface_sections(workspace, task_surface),
        ]
    )


def review_task_prompt(
    document: dict,
    task_surface: str = FULL,
    *,
    use_submit_tool: bool = True,
) -> str:
    compact = {
        "extraction": document.get("extraction", {}),
        "method_chain": document.get("method_chain", []),
        "candidates": document.get("candidates", []),
        "candidate_groups_considered": document.get(
            "candidate_groups_considered", []
        ),
    }
    return "\n\n".join(
        [
            "===== EXTRACTION UNDER REVIEW =====",
            json.dumps(compact, ensure_ascii=False),
            "===== REVIEW TASK =====",
            "Audit this extraction against the paper's input files. "
            "Candidates are indexed from 0 in the order shown. "
            + (
                "Call submit_review with "
                if use_submit_tool
                else "Return "
            )
            + "{\"review\": {\"challenges\": [...], "
            "\"summary\": \"...\"}}. Each challenge: {\"candidate_index\": "
            "int (-1 for document-level issues such as a missing candidate), "
            "\"field\": str, \"issue\": str (specific and checkable, cite "
            "file:line evidence), \"severity\": \"high\"|\"low\"}. Use "
            "severity high only for wrong/missing candidates, wrong values, "
            "or unsupported source_refs.",
            (
                "The empty enrichment groups are code-owned defaults on CORE+PROV; "
                "their absence is not an error. Review only the candidate set, identity, "
                "inclusion/origin, core quantities, evidence, and necessary lineage."
                if task_surface == CORE_PROV
                else "Review the complete FULL extraction surface."
            ),
        ]
    )


def workflow_review_task_prompt(
    document: dict, context: PackedContext, task_surface: str = FULL
) -> str:
    return "\n\n".join(
        [
            "===== PAPER INPUT FILES =====",
            context.text,
            review_task_prompt(
                document, task_surface, use_submit_tool=False
            ),
            "Return JSON only. Do not ask for more files and do not describe your process.",
        ]
    )


def review_structure_errors(payload: dict) -> list[str]:
    challenges = payload.get("challenges")
    if not isinstance(challenges, list):
        return ['review must be {"challenges": [...], "summary": "..."}']
    errors: list[str] = []
    if not str(payload.get("summary") or "").strip():
        errors.append("review.summary is required")
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
        if str(challenge.get("severity")) != REVIEW_ACTIONABLE_SEVERITY:
            continue
        index = int(challenge.get("candidate_index", -1))
        text = f"{challenge.get('field') or 'candidate'}: {challenge.get('issue')}"
        grouped.setdefault(index, []).append(text)
    return grouped


@dataclass(frozen=True)
class ReviewOutcome:
    payload: dict | None
    calls: int
    served_model: str
    challenges: list[dict]
    actionable_by_candidate: dict[int, list[str]]
    failure_reason: str = ""
    stop_reason: str = ""

    @property
    def failed(self) -> bool:
        return self.payload is None


def run_workflow_review(
    *,
    workspace: Path,
    document: dict,
    task_surface: str,
    context: PackedContext,
    transport: Callable[..., dict],
    transport_kwargs: dict,
    archive: Callable[[str, dict, list[dict]], None],
    usage_totals: dict[str, int],
    trace: RunTrace | None = None,
    trace_paper_id: str = "",
    stream_responses: bool = False,
) -> ReviewOutcome:
    """Run Method B's tool-free, whole-response reviewer workflow."""

    messages = [
        {
            "role": "system",
            "content": build_workflow_reviewer_system_prompt(
                workspace, task_surface
            ),
        },
        {
            "role": "user",
            "content": workflow_review_task_prompt(
                document, context, task_surface
            ),
        },
    ]
    served_model = ""
    failure_reason = ""
    calls = 0
    for _ in range(1 + WORKFLOW_REVIEW_RETRIES):
        calls += 1
        extra_body = dict(transport_kwargs.get("extra_body") or {})
        request_extra = dict(extra_body)
        if stream_responses:
            request_extra.update(
                {"stream": True, "stream_options": {"include_usage": True}}
            )
        call_id = f"{trace_paper_id}:review:{calls}"
        request_parent = None
        started = time.monotonic()
        if trace is not None:
            request_payload = build_chat_completion_payload(
                model=str(transport_kwargs.get("model") or ""),
                messages=messages,
                temperature=transport_kwargs.get("temperature", 0),
                max_tokens=transport_kwargs.get("max_tokens"),
                extra_body=request_extra,
            )
            request_parent = trace.emit(
                "llm.request.started",
                paper_id=trace_paper_id,
                stage="review",
                summary=f"workflow review call {calls}",
                data={"call": calls, "kind": "workflow_review"},
                payload_kind="llm.request",
                payload=request_payload,
                call_id=call_id,
                node_id="review",
                source_node_id="review",
                target_node_id="provider",
                attempt=1,
            )["seq"]
        callback = (
            stream_trace_callback(
                trace,
                paper_id=trace_paper_id,
                stage="review",
                call_id=call_id,
                parent_seq=request_parent,
            )
            if trace is not None and stream_responses
            else None
        )
        call_kwargs: dict[str, Any] = {
            key: value
            for key, value in transport_kwargs.items()
            if key != "extra_body"
        }
        if stream_responses:
            call_kwargs.update({"stream": True, "on_stream_event": callback})
        try:
            response = transport(
                messages=messages,
                extra_body=extra_body,
                **call_kwargs,
            )
        except Exception as exc:
            if trace is not None:
                trace.emit(
                    "llm.request.failed",
                    paper_id=trace_paper_id,
                    stage="review",
                    status="failed",
                    summary=f"{type(exc).__name__}: {exc}",
                    duration_ms=int((time.monotonic() - started) * 1000),
                    parent_seq=request_parent,
                    call_id=call_id,
                    node_id="review",
                    source_node_id="provider",
                    target_node_id="review",
                )
            raise RuntimeError(f"review: {type(exc).__name__}: {exc}") from exc
        archive(f"review-call-{calls:02d}", response, messages)
        accumulate_usage(usage_totals, response.get("usage") or {})
        if response.get("model"):
            served_model = str(response["model"])
        if trace is not None:
            trace.emit(
                "llm.response.completed",
                paper_id=trace_paper_id,
                stage="review",
                status="completed",
                data={"call": calls, **response_trace_metadata(response)},
                payload_kind="llm.response",
                payload=response,
                usage=response.get("usage") or {},
                duration_ms=int((time.monotonic() - started) * 1000),
                parent_seq=request_parent,
                call_id=call_id,
                node_id="review",
                source_node_id="provider",
                target_node_id="review",
            )
            requested_model = str(transport_kwargs.get("model") or "")
            if served_model and requested_model and served_model != requested_model:
                trace.emit(
                    "llm.served_model.changed",
                    paper_id=trace_paper_id,
                    stage="review",
                    status="completed",
                    data={
                        "requested_model": requested_model,
                        "served_model": served_model,
                    },
                    parent_seq=request_parent,
                    call_id=call_id,
                    node_id="review",
                    source_node_id="provider",
                    target_node_id="review",
                )
        choice = (response.get("choices") or [{}])[0]
        content = str((choice.get("message") or {}).get("content") or "")
        parsed: dict | None
        try:
            candidate = extract_json_object(content)
            parsed = candidate if isinstance(candidate, dict) else None
        except (ValueError, json.JSONDecodeError) as exc:
            parsed = None
            failure_reason = f"unparseable JSON: {exc}"
        payload = parsed.get("review", parsed) if parsed is not None else None
        structure_errors = (
            review_structure_errors(payload) if isinstance(payload, dict) else []
        )
        if isinstance(payload, dict) and not structure_errors:
            challenges = [
                item
                for item in payload.get("challenges", [])
                if isinstance(item, dict)
            ]
            return ReviewOutcome(
                payload=payload,
                calls=calls,
                served_model=served_model,
                challenges=challenges,
                actionable_by_candidate=challenges_by_candidate(challenges),
            )
        if parsed is not None:
            failure_reason = "; ".join(structure_errors) or "missing review object"
        rejected = (
            json.dumps(parsed, ensure_ascii=False)
            if parsed is not None
            else content[:1000]
        )
        messages.extend(
            [
                {"role": "assistant", "content": content},
                {
                    "role": "user",
                    "content": (
                        f"The previous JSON was rejected: {failure_reason}. "
                        f"Rejected value: {rejected}. Return only a corrected "
                        "{\"review\": {\"challenges\": [...], "
                        "\"summary\": \"...\"}} object."
                    ),
                },
            ]
        )
    return ReviewOutcome(
        payload=None,
        calls=calls,
        served_model=served_model,
        challenges=[],
        actionable_by_candidate={},
        failure_reason=(
            "review_workflow_structured_output_failed after "
            f"{calls} calls: {failure_reason}"
        ),
    )


def run_agentic_review(
    *,
    workspace: Path,
    document: dict,
    task_surface: str,
    fs: ContextFS,
    transport: Callable[..., dict],
    transport_kwargs: dict,
    archive: Callable[[str, dict, list[dict]], None],
    usage_totals: dict[str, int],
    trace: RunTrace | None = None,
    trace_paper_id: str = "",
    stream_responses: bool = False,
) -> ReviewOutcome:
    """Run Method C's bounded read-tool reviewer agent."""

    unit = ReactUnit(
        name="review",
        kind="review",
        system_prompt=build_agentic_reviewer_system_prompt(
            workspace, task_surface
        ),
        task_prompt=review_task_prompt(document, task_surface),
        fs=fs,
        submit_name="submit_review",
        submit_key="review",
        submit_check=review_structure_errors,
        transport=transport,
        transport_kwargs=transport_kwargs,
        archive=archive,
        usage_totals=usage_totals,
        trace=trace,
        trace_paper_id=trace_paper_id,
        stream_responses=stream_responses,
        finalization_calls=AGENTIC_REVIEW_FINALIZATION_CALLS,
        stall_on_repeated_tool_batch=True,
    )
    payload = unit.run()
    challenges = (
        [item for item in payload.get("challenges", []) if isinstance(item, dict)]
        if payload is not None
        else []
    )
    return ReviewOutcome(
        payload=payload,
        calls=unit.calls,
        served_model=unit.served_model,
        challenges=challenges,
        actionable_by_candidate=challenges_by_candidate(challenges),
        failure_reason=unit.failure_reason,
        stop_reason=unit.stop_reason,
    )


def reviewed_delivery_status(
    *, review_failed: bool, errors: list[str], cjk_paths: list[str]
) -> str:
    if review_failed:
        return "review_failed"
    if errors:
        return "validator_errors"
    if cjk_paths:
        return "ok_with_cjk_warnings"
    return "ok"
