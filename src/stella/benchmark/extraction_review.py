"""Method-specific independent-review stages for benchmark methods B/C."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from stella.lit.llm_batch import (
    LLMTransportError,
    build_chat_completion_payload,
)
from stella.lit.extraction_rules import render_rule_profile

from .context_pack import PackedContext
from .roster_bundle import roster_payload_json_schema, roster_structure_errors
from .structured_output import (
    StructuredOutputError,
    apply_structured_output_request,
    parse_structured_output,
    review_payload_json_schema,
)
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
_METHOD_SEMANTIC_RE = re.compile(
    r"\b(?:direct producer|producer[- ]type|step_type compatibility|lineage|"
    r"solar(?:_position_and_motion| parameter)|cross[- ]category|"
    r"quantity categor(?:y|ies)|method[- ]chain semantic)\b",
    re.IGNORECASE,
)
_METHOD_STRUCTURAL_RE = re.compile(
    r"\b(?:unknown|missing|invalid|duplicate|broken|dangling)\b.*\bmethod_ref|"
    r"\bmethod_ref\b.*\b(?:unknown|missing|invalid|duplicate|broken|dangling)\b|"
    r"\b(?:step[-_ ]?id|depends_on|dependency|cycle|acyclic)\b",
    re.IGNORECASE,
)


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
            "ambiguities or nitpick prose. Method-chain ID/dependency/reference "
            "breakage is structural and may block delivery. Producer-type "
            "compatibility, lineage completeness, solar-parameter completeness, "
            "and cross-category method semantics are low-severity diagnostics "
            "only: never make them high severity or request a revision for them. "
            "Return only one JSON object with a "
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
            "nitpick phrasing or style. Method-chain ID/dependency/reference "
            "breakage is structural and may block delivery. Producer-type "
            "compatibility, lineage completeness, solar-parameter completeness, "
            "and cross-category method semantics are low-severity diagnostics "
            "only: never make them high severity or request a revision for them. "
            "Report only checkable substantive "
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
    sealed_roster_anchors: list[dict] | None = None,
) -> str:
    compact = {
        "extraction": document.get("extraction", {}),
        "method_chain": document.get("method_chain", []),
        "candidates": document.get("candidates", []),
        "candidate_groups_considered": document.get(
            "candidate_groups_considered", []
        ),
    }
    if sealed_roster_anchors is not None:
        compact["sealed_roster_inclusion_anchors"] = sealed_roster_anchors
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
            + (
                "severity high only for wrong values or unsupported "
                "source_refs. Candidate membership was sealed by an earlier "
                "independent roster review; sealed_roster_inclusion_anchors "
                "is its read-only evidence, not a mutable candidate field. "
                "Do not challenge membership: no additions, deletions, "
                "renames, or reordering. "
                if sealed_roster_anchors is not None
                else "severity high only for wrong/missing candidates, wrong values, "
                "or unsupported source_refs. "
            )
            + "Method-chain semantic completeness "
            "(producer taxonomy, lineage, solar parameters, or cross-category "
            "compatibility) is low severity only and is never an actionable "
            "challenge. Structural method-chain breakage remains actionable.",
            (
                "The empty enrichment groups are code-owned defaults on CORE+PROV; "
                "their absence is not an error. Review only the candidate set, identity, "
                "inclusion/origin, core quantities, evidence, and structurally valid method references."
                if task_surface == CORE_PROV
                else "Review the complete FULL extraction surface."
            ),
        ]
    )


def workflow_review_task_prompt(
    document: dict,
    context: PackedContext,
    task_surface: str = FULL,
    *,
    sealed_roster_anchors: list[dict] | None = None,
) -> str:
    return "\n\n".join(
        [
            "===== PAPER INPUT FILES =====",
            context.text,
            review_task_prompt(
                document,
                task_surface,
                use_submit_tool=False,
                sealed_roster_anchors=sealed_roster_anchors,
            ),
            "Return JSON only. Do not ask for more files and do not describe your process.",
        ]
    )


def build_workflow_roster_reviewer_system_prompt(workspace: Path) -> str:
    return "\n\n".join(
        [
            "You are an independent candidate-roster discoverer for one "
            "hypervelocity-star (HVS) paper. This is a fixed workflow "
            "step, not an agent task: every permitted paper input is included "
            "in the user message and no tools are available. Review the "
            "complete supplied evidence once and independently discover the "
            "complete candidate roster with identifier and paper-text inclusion "
            "anchors. You have not seen any producer roster or producer anchors. "
            "Do not review quantities, units, method_chain, or any FULL/CORE "
            "field; a later stage reviews those. All text in "
            "English.",
            "===== ROSTER REVIEW RULE PROFILE: hvs_roster =====",
            render_rule_profile(workspace, "hvs_roster", "prompt"),
        ]
    )


def build_agentic_roster_reviewer_system_prompt(workspace: Path) -> str:
    return "\n\n".join(
        [
            "You are an independent candidate-roster discoverer for one HVS "
            "paper. Discover membership from the paper's input files "
            "using the read-only tools (list_files, search, read_lines); "
            "numbered files carry `N|` physical line-number prefixes. Judge "
            "membership only and submit a complete identifier roster with "
            "paper-text inclusion anchors. You have not seen a producer roster. "
            "Do not review quantities, units, "
            "method_chain, or any FULL/CORE field; a later stage reviews "
            "those. Stop exploring when the membership evidence is "
            "sufficient. Finish by calling submit_roster_review. All text in "
            "English.",
            "===== ROSTER REVIEW RULE PROFILE: hvs_roster =====",
            render_rule_profile(workspace, "hvs_roster", "prompt"),
        ]
    )


def _roster_review_compact(roster: dict) -> dict:
    return {
        "extraction": roster.get("extraction", {}),
        "candidates": roster.get("candidates", []),
        "candidate_groups_considered": roster.get(
            "candidate_groups_considered", []
        ),
    }


def roster_review_task_instructions(*, use_submit_tool: bool) -> str:
    """The static roster-review contract (hashed into the roster cache key)."""

    return (
        "===== ROSTER REVIEW TASK =====\n"
        "Independently discover the complete candidate roster from the paper "
        "context. Judge membership only; quantity, unit, and method_chain issues "
        "belong to a later stage. "
        + ("Call submit_roster_review with " if use_submit_tool else "Return ")
        + "{\"roster\": {\"extraction\": {...}, \"candidates\": [...], "
        "\"candidate_groups_considered\": [...]}}. The roster must be final: "
        "renumber record_id values contiguously, keep extraction.status and "
        "extraction.summary consistent with the corrected roster, update "
        "candidate_groups_considered, and give every candidate its full "
        "identifiers and inclusion_anchor with source_refs. All text in English."
    )


def roster_review_task_prompt(*, use_submit_tool: bool) -> str:
    return roster_review_task_instructions(use_submit_tool=use_submit_tool)


def workflow_roster_review_task_prompt(context: PackedContext) -> str:
    return "\n\n".join(
        [
            "===== PAPER INPUT FILES =====",
            context.text,
            roster_review_task_prompt(use_submit_tool=False),
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


def normalize_review_payload(payload: dict) -> dict:
    """Keep method-chain semantics diagnostic-only even if a model over-ranks them."""

    normalized: list[Any] = []
    for challenge in payload.get("challenges", []):
        if not isinstance(challenge, dict):
            normalized.append(challenge)
            continue
        item = dict(challenge)
        text = f"{item.get('field') or ''} {item.get('issue') or ''}"
        if (
            item.get("severity") == REVIEW_ACTIONABLE_SEVERITY
            and _METHOD_SEMANTIC_RE.search(text)
            and not _METHOD_STRUCTURAL_RE.search(text)
        ):
            item["severity"] = "low"
        normalized.append(item)
    return {**payload, "challenges": normalized}


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


def _whole_response_structured_outcome(
    *,
    messages: list[dict],
    stage: str,
    trace_kind: str,
    archive_prefix: str,
    payload_key: str,
    contract_hint: str,
    failure_label: str,
    structure_check: Callable[[dict], list[str]],
    payload_schema: dict[str, Any],
    transport: Callable[..., dict],
    transport_kwargs: dict,
    archive: Callable[[str, dict, list[dict]], None],
    usage_totals: dict[str, int],
    trace: RunTrace | None = None,
    trace_paper_id: str = "",
    stream_responses: bool = False,
) -> tuple[dict | None, int, str, str]:
    """One tool-free whole-response structured-output loop with retries.

    Returns (payload, calls, served_model, failure_reason); the payload is
    None when every attempt was rejected by ``structure_check``.
    """

    served_model = ""
    failure_reason = ""
    calls = 0
    for _ in range(1 + WORKFLOW_REVIEW_RETRIES):
        calls += 1
        structured_contract = transport_kwargs.get("structured_output_contract")
        if not isinstance(structured_contract, dict):
            raise ValueError(f"{stage}: frozen structured-output contract is required")
        tool_name = "submit_" + stage.replace("-", "_")
        extra_body = apply_structured_output_request(
            dict(transport_kwargs.get("extra_body") or {}),
            contract=structured_contract,
            schema=payload_schema,
            tool_name=tool_name,
        )
        request_extra = dict(extra_body)
        if stream_responses:
            request_extra.update(
                {"stream": True, "stream_options": {"include_usage": True}}
            )
        call_id = f"{trace_paper_id}:{stage}:{calls}"
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
                stage=stage,
                summary=f"{trace_kind.replace('_', ' ')} call {calls}",
                data={"call": calls, "kind": trace_kind},
                payload_kind="llm.request",
                payload=request_payload,
                call_id=call_id,
                node_id=stage,
                source_node_id=stage,
                target_node_id="provider",
                attempt=1,
            )["seq"]
        callback = (
            stream_trace_callback(
                trace,
                paper_id=trace_paper_id,
                stage=stage,
                call_id=call_id,
                parent_seq=request_parent,
            )
            if trace is not None and stream_responses
            else None
        )
        call_kwargs: dict[str, Any] = {
            key: value
            for key, value in transport_kwargs.items()
            if key not in {"extra_body", "structured_output_contract"}
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
                    stage=stage,
                    status="failed",
                    summary=f"{type(exc).__name__}: {exc}",
                    duration_ms=int((time.monotonic() - started) * 1000),
                    parent_seq=request_parent,
                    call_id=call_id,
                    node_id=stage,
                    source_node_id="provider",
                    target_node_id=stage,
                )
            if isinstance(exc, LLMTransportError):
                raise exc.with_context(stage=stage, call_id=call_id)
            raise RuntimeError(f"{stage}: {type(exc).__name__}: {exc}") from exc
        archive(f"{archive_prefix}-call-{calls:02d}", response, messages)
        accumulate_usage(usage_totals, response.get("usage") or {})
        if response.get("model"):
            served_model = str(response["model"])
        if trace is not None:
            trace.emit(
                "llm.response.completed",
                paper_id=trace_paper_id,
                stage=stage,
                status="completed",
                data={"call": calls, **response_trace_metadata(response)},
                payload_kind="llm.response",
                payload=response,
                usage=response.get("usage") or {},
                duration_ms=int((time.monotonic() - started) * 1000),
                parent_seq=request_parent,
                call_id=call_id,
                node_id=stage,
                source_node_id="provider",
                target_node_id=stage,
            )
            requested_model = str(transport_kwargs.get("model") or "")
            if served_model and requested_model and served_model != requested_model:
                trace.emit(
                    "llm.served_model.changed",
                    paper_id=trace_paper_id,
                    stage=stage,
                    status="completed",
                    data={
                        "requested_model": requested_model,
                        "served_model": served_model,
                    },
                    parent_seq=request_parent,
                    call_id=call_id,
                    node_id=stage,
                    source_node_id="provider",
                    target_node_id=stage,
                )
        choice = (response.get("choices") or [{}])[0]
        content = str((choice.get("message") or {}).get("content") or "")
        parsed: dict | None
        try:
            parsed = parse_structured_output(
                response,
                mode=str(structured_contract.get("mode") or ""),
                schema=payload_schema,
                tool_name=tool_name,
            )
        except StructuredOutputError as exc:
            parsed = None
            failure_reason = str(exc)
        payload = parsed
        structure_errors = (
            structure_check(payload) if isinstance(payload, dict) else []
        )
        if isinstance(payload, dict) and not structure_errors:
            return payload, calls, served_model, ""
        if parsed is not None:
            failure_reason = (
                "; ".join(structure_errors) or f"missing {payload_key} object"
            )
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
                        f"{contract_hint} object."
                    ),
                },
            ]
        )
    return (
        None,
        calls,
        served_model,
        f"{failure_label}_structured_output_failed after {calls} calls: "
        f"{failure_reason}",
    )


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
    sealed_roster_anchors: list[dict] | None = None,
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
                document,
                context,
                task_surface,
                sealed_roster_anchors=sealed_roster_anchors,
            ),
        },
    ]
    payload, calls, served_model, failure_reason = (
        _whole_response_structured_outcome(
            messages=messages,
            stage="review",
            trace_kind="workflow_review",
            archive_prefix="review",
            payload_key="review",
            contract_hint=(
                '{"review": {"challenges": [...], "summary": "..."}}'
            ),
            failure_label="review_workflow",
            structure_check=review_structure_errors,
            payload_schema=review_payload_json_schema(),
            transport=transport,
            transport_kwargs=transport_kwargs,
            archive=archive,
            usage_totals=usage_totals,
            trace=trace,
            trace_paper_id=trace_paper_id,
            stream_responses=stream_responses,
        )
    )
    if payload is None:
        return ReviewOutcome(
            payload=None,
            calls=calls,
            served_model=served_model,
            challenges=[],
            actionable_by_candidate={},
            failure_reason=failure_reason,
        )
    payload = normalize_review_payload(payload)
    challenges = [
        item for item in payload.get("challenges", []) if isinstance(item, dict)
    ]
    return ReviewOutcome(
        payload=payload,
        calls=calls,
        served_model=served_model,
        challenges=challenges,
        actionable_by_candidate=challenges_by_candidate(challenges),
    )


@dataclass(frozen=True)
class RosterReviewOutcome:
    payload: dict | None
    calls: int
    served_model: str
    failure_reason: str = ""
    stop_reason: str = ""

    @property
    def failed(self) -> bool:
        return self.payload is None


def roster_reconciliation_prompt(
    produced: dict, reviewed: dict, comparison: dict, *, use_submit_tool: bool
) -> str:
    action = "Call submit_reconciled_roster with" if use_submit_tool else "Return"
    return "\n\n".join(
        [
            "===== DETERMINISTIC ROSTER MISMATCH =====",
            json.dumps(comparison, ensure_ascii=False, sort_keys=True),
            "===== PRODUCER ROSTER =====",
            json.dumps(_roster_review_compact(produced), ensure_ascii=False),
            "===== INDEPENDENT REVIEWER ROSTER =====",
            json.dumps(_roster_review_compact(reviewed), ensure_ascii=False),
            "===== ONE BOUNDED RECONCILIATION =====",
            f"{action} {{\"roster\": {{...}}}}. Resolve only the shown roster "
            "difference against the already supplied paper evidence. Submit one "
            "complete final roster; no further reconciliation is available.",
        ]
    )


def run_workflow_roster_reconciliation(
    *,
    workspace: Path,
    produced: dict,
    reviewed: dict,
    comparison: dict,
    arxiv_id: str,
    context: PackedContext,
    transport: Callable[..., dict],
    transport_kwargs: dict,
    archive: Callable[[str, dict, list[dict]], None],
    usage_totals: dict[str, int],
    trace: RunTrace | None = None,
    trace_paper_id: str = "",
    stream_responses: bool = False,
) -> RosterReviewOutcome:
    messages = [
        {"role": "system", "content": build_workflow_roster_reviewer_system_prompt(workspace)},
        {
            "role": "user",
            "content": "\n\n".join(
                [
                    "===== PAPER INPUT FILES =====",
                    context.text,
                    roster_reconciliation_prompt(
                        produced, reviewed, comparison, use_submit_tool=False
                    ),
                ]
            ),
        },
    ]
    payload, calls, served_model, failure_reason = _whole_response_structured_outcome(
        messages=messages,
        stage="roster_reconciliation",
        trace_kind="workflow_roster_reconciliation",
        archive_prefix="roster-reconciliation",
        payload_key="roster",
        contract_hint='{"roster": {"extraction": {...}, "candidates": [...], "candidate_groups_considered": [...]}}',
        failure_label="roster_reconciliation_workflow",
        structure_check=lambda item: roster_structure_errors(item, arxiv_id),
        payload_schema=roster_payload_json_schema(),
        transport=transport,
        transport_kwargs=transport_kwargs,
        archive=archive,
        usage_totals=usage_totals,
        trace=trace,
        trace_paper_id=trace_paper_id,
        stream_responses=stream_responses,
    )
    return RosterReviewOutcome(payload, calls, served_model, failure_reason)


def run_agentic_roster_reconciliation(
    *,
    workspace: Path,
    produced: dict,
    reviewed: dict,
    comparison: dict,
    arxiv_id: str,
    fs: ContextFS,
    transport: Callable[..., dict],
    transport_kwargs: dict,
    archive: Callable[[str, dict, list[dict]], None],
    usage_totals: dict[str, int],
    trace: RunTrace | None = None,
    trace_paper_id: str = "",
    stream_responses: bool = False,
) -> RosterReviewOutcome:
    unit = ReactUnit(
        name="roster-reconciliation",
        kind="review",
        system_prompt=build_agentic_roster_reviewer_system_prompt(workspace),
        task_prompt=roster_reconciliation_prompt(
            produced, reviewed, comparison, use_submit_tool=True
        ),
        fs=fs,
        submit_name="submit_reconciled_roster",
        submit_key="roster",
        submit_check=lambda item: roster_structure_errors(item, arxiv_id),
        submit_payload_schema=roster_payload_json_schema(),
        transport=transport,
        transport_kwargs=transport_kwargs,
        archive=archive,
        usage_totals=usage_totals,
        trace=trace,
        trace_paper_id=trace_paper_id,
        stream_responses=stream_responses,
        finalization_calls=1,
        stall_on_repeated_tool_batch=True,
    )
    payload = unit.run()
    return RosterReviewOutcome(
        payload, unit.calls, unit.served_model, unit.failure_reason, unit.stop_reason
    )


def run_workflow_roster_review(
    *,
    workspace: Path,
    arxiv_id: str,
    context: PackedContext,
    transport: Callable[..., dict],
    transport_kwargs: dict,
    archive: Callable[[str, dict, list[dict]], None],
    usage_totals: dict[str, int],
    trace: RunTrace | None = None,
    trace_paper_id: str = "",
    stream_responses: bool = False,
) -> RosterReviewOutcome:
    """Run Method B's tool-free, whole-response pre-seal roster review."""

    messages = [
        {
            "role": "system",
            "content": build_workflow_roster_reviewer_system_prompt(workspace),
        },
        {
            "role": "user",
            "content": workflow_roster_review_task_prompt(context),
        },
    ]
    payload, calls, served_model, failure_reason = (
        _whole_response_structured_outcome(
            messages=messages,
            stage="roster_review",
            trace_kind="workflow_roster_review",
            archive_prefix="roster-review",
            payload_key="roster",
            contract_hint=(
                '{"roster": {"extraction": {...}, "candidates": [...], '
                '"candidate_groups_considered": [...]}}'
            ),
            failure_label="roster_review_workflow",
            structure_check=lambda item: roster_structure_errors(item, arxiv_id),
            payload_schema=roster_payload_json_schema(),
            transport=transport,
            transport_kwargs=transport_kwargs,
            archive=archive,
            usage_totals=usage_totals,
            trace=trace,
            trace_paper_id=trace_paper_id,
            stream_responses=stream_responses,
        )
    )
    return RosterReviewOutcome(
        payload=payload,
        calls=calls,
        served_model=served_model,
        failure_reason=failure_reason,
    )


def run_agentic_roster_review(
    *,
    workspace: Path,
    arxiv_id: str,
    fs: ContextFS,
    transport: Callable[..., dict],
    transport_kwargs: dict,
    archive: Callable[[str, dict, list[dict]], None],
    usage_totals: dict[str, int],
    trace: RunTrace | None = None,
    trace_paper_id: str = "",
    stream_responses: bool = False,
) -> RosterReviewOutcome:
    """Run Method C's bounded read-tool pre-seal roster review."""

    unit = ReactUnit(
        name="roster-review",
        kind="review",
        system_prompt=build_agentic_roster_reviewer_system_prompt(workspace),
        task_prompt=roster_review_task_prompt(use_submit_tool=True),
        fs=fs,
        submit_name="submit_roster_review",
        submit_key="roster",
        submit_check=lambda item: roster_structure_errors(item, arxiv_id),
        submit_payload_schema=roster_payload_json_schema(),
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
    return RosterReviewOutcome(
        payload=payload,
        calls=unit.calls,
        served_model=unit.served_model,
        failure_reason=unit.failure_reason,
        stop_reason=unit.stop_reason,
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
    sealed_roster_anchors: list[dict] | None = None,
) -> ReviewOutcome:
    """Run Method C's bounded read-tool reviewer agent."""

    unit = ReactUnit(
        name="review",
        kind="review",
        system_prompt=build_agentic_reviewer_system_prompt(
            workspace, task_surface
        ),
        task_prompt=review_task_prompt(
            document, task_surface, sealed_roster_anchors=sealed_roster_anchors
        ),
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
    if payload is not None:
        payload = normalize_review_payload(payload)
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
