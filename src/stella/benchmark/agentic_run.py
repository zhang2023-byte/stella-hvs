"""Agentic extraction runs (method C): tool-driven ReAct over packed context.

Pipeline ``stella-agentic-extraction/0.1``. Differences from the staged
direct-API pipeline (``extraction_run``, method B):

- The packed paper context is NOT pasted into the prompt. It becomes a
  read-only virtual file system exposed through tools (``list_files``,
  ``read_lines``, ``search``): the model decides what to look at, and only
  those slices enter the conversation. Everything the model can possibly
  see still comes from the same deterministic pack, so the context
  manifest remains the complete audit surface.
- Candidate selection runs first as a surface-neutral read-only tool agent.
  Its ``submit_roster`` bundle is shared by FULL and CORE only when method,
  model, provider, prompt/rules, context and code provenance match. All
  downstream stages must preserve its candidate identifiers and order.
- Structure correctness is enforced at submission time: units end by
  calling ``submit_roster`` / ``submit_scaffold`` / ``submit_candidate`` /
  ``submit_review``,
  whose payloads are checked immediately (record ids, roster shape,
  method_ref targets) and rejected back into the loop as tool results.
- After the frozen validator gates the merged document, an independent
  reviewer model (default a different family than the extractor) audits
  each paper with bounded read-only tools and files structured challenges;
  repeated reads, output truncation, or research-budget exhaustion switch
  it into a forced-submit phase. Actionable challenges drive one extra
  targeted revision round, then the validator runs again.

Shared with method B: reviewer rule profile and output schema, context packer,
skeleton builder, frozen validator and repair-round budget, provenance
enforcement, usage accounting, and runs archive layout. Reviewer orchestration
is method-specific: only method C may use tools.
Requests are archived alongside responses (large message bodies are
digest-compressed) so a run can be audited without re-execution.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from stella.lit.llm_batch import LLMTransportError, chat_completion_raw
from stella.lit.extraction_rules import render_rule_profile, rule_profile_sha256
from stella.lit.schema_templates import (
    build_core_provenance_candidate_template,
    build_hvs_candidates_template,
)

from .context_pack import pack_paper_context
from .extraction_review import (
    reviewed_delivery_status,
    run_agentic_review,
)
from .extraction_run import (
    batch_structure_errors,
    enforce_pipeline_fields,
    find_cjk_strings,
    load_frozen_validator,
    merge_document,
    route_errors,
    scaffold_step_ids,
    scaffold_structure_errors,
)
from .task_surfaces import (
    CORE_PROV,
    FULL,
    get_task_surface,
    hydrate_surface_document,
    surface_binding,
    task_surface_schema_view,
    validate_generated_candidate,
    validate_surface_document,
)
from .tool_loop import (
    MAX_ERRORS_IN_FEEDBACK,
    MAX_TOOL_CALLS,
    ContextFS,
    ReactUnit,
    archive_request,
)
from .run_trace import RunTrace
from .roster_bundle import (
    canonical_sha256,
    get_or_create_roster_bundle,
    roster_shared_key,
    roster_structure_errors,
    roster_stubs,
)

PIPELINE_NAME = "stella-agentic-extraction"
# 0.2.0: extraction surface moved to schema v0.2 first batch (see
# extraction_run 0.5.0).
# 0.3.0: schema v0.2 second batch (see extraction_run 0.6.0).

DEFAULT_MAX_REPAIR_ROUNDS = 3


# --------------------------------------------------------------------------
# Prompts


def build_agentic_system_prompt(workspace: Path, task_surface: str = FULL) -> str:
    skill_dir = workspace / "skills" / "hvs-candidates-extraction"
    surface = get_task_surface(task_surface)
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
        "===== CANONICAL EXTRACTION RULE PROFILE: hvs_extractor =====",
        render_rule_profile(workspace, "hvs_extractor", "prompt"),
        f"===== TASK SURFACE: {surface.id} =====",
        surface.instruction,
        "===== GENERATIVE SCHEMA REFERENCE =====",
        task_surface_schema_view(workspace, task_surface),
        "===== COORDINATE FRAME REFERENCE =====",
        (skill_dir / "references" / "coordinate_frames.md").read_text(encoding="utf-8"),
    ]
    return "\n\n".join(parts)


def build_agentic_roster_system_prompt(workspace: Path) -> str:
    return "\n\n".join(
        [
            "You are the surface-neutral candidate-roster agent for one HVS paper. "
            "Use only list_files, search, and read_lines. Identify candidates and "
            "their minimum inclusion evidence; do not design method_chain steps, "
            "inspect FULL/CORE field requirements, or call a reviewer. Finish with "
            "submit_roster.",
            "===== ROSTER RULE PROFILE: hvs_roster =====",
            render_rule_profile(workspace, "hvs_roster", "prompt"),
        ]
    )


def agentic_roster_task_prompt(skeleton: dict, fs: ContextFS) -> str:
    return "\n\n".join(
        [
            "===== AVAILABLE INPUT FILES =====",
            json.dumps(fs.list_files(), ensure_ascii=False, indent=2),
            "===== PAPER IDENTITY =====",
            json.dumps(
                {
                    "paper": skeleton.get("paper", {}),
                    "inputs": skeleton.get("inputs", {}),
                },
                ensure_ascii=False,
                indent=2,
            ),
            "===== SURFACE-NEUTRAL ROSTER TASK =====",
            "Call submit_roster with {\"extraction\": {\"status\": "
            "\"candidates_found\"|\"no_candidates\", \"summary\": \"...\"}, "
            "\"candidates\": [...], \"candidate_groups_considered\": [...]}. "
            "Each candidate contains only identifiers and inclusion_anchor. "
            "inclusion_anchor contains summary and source_refs. Do not emit "
            "method_chain or quantities.",
        ]
    )


def plan_task_prompt(
    skeleton: dict,
    fs: ContextFS,
    roster_rules: str,
    task_surface: str = FULL,
    frozen_roster_bundle: dict[str, Any] | None = None,
) -> str:
    frozen_instruction = ""
    if frozen_roster_bundle is not None:
        frozen_instruction = (
            "A separate surface-neutral stage has frozen the roster. submit_scaffold "
            "must preserve these identifier stubs exactly: no additions, deletions, "
            "reordering, or identifier changes. Inclusion anchors are evidence only.\n"
            + json.dumps(
                {
                    "frozen_roster": roster_stubs(frozen_roster_bundle),
                    "inclusion_anchors": [
                        candidate.get("inclusion_anchor", {})
                        for candidate in frozen_roster_bundle.get("candidates", [])
                        if isinstance(candidate, dict)
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return "\n\n".join(
        [
            "===== AVAILABLE INPUT FILES =====",
            json.dumps(fs.list_files(), ensure_ascii=False, indent=2),
            "===== SKELETON =====",
            json.dumps(skeleton, ensure_ascii=False, indent=2),
            "===== ROSTER RULE PROFILE: hvs_roster =====",
            roster_rules,
            "===== STAGE 1: SCAFFOLD AND ROSTER =====",
            frozen_instruction,
            "Explore the paper with the tools, then call submit_scaffold "
            "with the completed skeleton EXCEPT candidate details: fill "
            "`extraction` (status, summary), "
            + (
                "the minimum `method_chain` needed to support candidate inclusion and populated core quantities, "
                if task_surface == CORE_PROV
                else "the full `method_chain`, "
            )
            + "and "
            "`candidate_groups_considered` exactly per the skill. For "
            "`candidates`, provide the frozen roster above when supplied; otherwise provide an EXHAUSTIVE roster of identifier "
            "stubs: one entry per object the paper treats as possibly "
            "unbound from the Milky Way, each containing ONLY the "
            "`identifiers` object (record_id, paper_candidate_id, "
            "gaia_source_id, all[] with source_refs). Apply the roster rule "
            "profile above. Keep `schema`, `paper`, and `inputs` unchanged. "
            "The files listed above ARE the paper's source; do not use status "
            "'source_missing'.",
        ]
    )


def candidate_task_prompt(
    scaffold: dict, stub: dict, task_surface: str = FULL
) -> str:
    scaffold_view = {
        "extraction": scaffold.get("extraction", {}),
        "method_chain": scaffold.get("method_chain", []),
        "candidate_groups_considered": scaffold.get("candidate_groups_considered", []),
    }
    parts = [
            "===== DOCUMENT SCAFFOLD (already fixed) =====",
            json.dumps(scaffold_view, ensure_ascii=False, indent=2),
            "===== STAGE 2: FILL THIS CANDIDATE =====",
            json.dumps({"roster_stub": stub}, ensure_ascii=False, indent=2),
    ]
    if task_surface == CORE_PROV:
        parts.extend(
            [
                "===== CODE-GENERATED CORE CANDIDATE TEMPLATE =====",
                json.dumps(
                    build_core_provenance_candidate_template(stub["identifiers"]),
                    ensure_ascii=False,
                    indent=2,
                ),
            ]
        )
    parts.append(
            "Research this one object in the paper's input files, then call "
            "submit_candidate with one "
            + (
                "complete CORE+PROV candidate record "
                if task_surface == CORE_PROV
                else "COMPLETE CandidateRecord "
            )
            + "for it: "
            "identical record_id, every quantity with raw_value/value, "
            "source_refs pointing at real lines/cells you actually read, "
            "and method_refs referencing the scaffold's existing step ids. "
            "Follow the skill and schema exactly."
    )
    return "\n\n".join(parts)


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
    validator_warning_messages: list[str] = field(default_factory=list)
    validator_findings: list[dict[str, Any]] = field(default_factory=list)
    validator_groups: list[dict[str, Any]] = field(default_factory=list)
    transport_error: dict[str, Any] | None = None
    roster_bundle_id: str = ""
    roster_cache_hit: bool = False
    roster_calls: int = 0
    shared_roster_usage: dict[str, int] = field(default_factory=dict)
    downstream_usage: dict[str, int] = field(default_factory=dict)
    cjk_paths: list[str] = field(default_factory=list)
    usage_totals: dict[str, int] = field(default_factory=dict)
    error: str = ""


def roster_record_id(stub: dict) -> str:
    identifiers = stub.get("identifiers") if isinstance(stub, dict) else None
    return str(identifiers.get("record_id") or "") if isinstance(identifiers, dict) else ""


def reconcile_roster_records(
    old_roster: list[dict],
    old_records: list[list[dict]],
    new_roster: list[dict],
) -> tuple[list[list[dict] | None], list[str], list[str]]:
    """Align candidate records to a reviewer-revised roster by record_id."""

    existing = {
        roster_record_id(stub): records
        for stub, records in zip(old_roster, old_records, strict=True)
    }
    new_ids = [roster_record_id(stub) for stub in new_roster]
    aligned = [existing.get(record_id) for record_id in new_ids]
    added = [record_id for record_id in new_ids if record_id not in existing]
    deleted = [record_id for record_id in existing if record_id not in set(new_ids)]
    return aligned, added, deleted


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
    task_surface: str = FULL,
    method_fingerprint: str = "",
    validator_module=None,
    transport: Callable[..., dict] | None = None,
    trace: RunTrace | None = None,
    stream_responses: bool = False,
    roster_cache_root: Path | None = None,
) -> AgenticResult:
    transport = transport or chat_completion_raw
    validator = validator_module or load_frozen_validator(workspace)
    paper_dir = run_dir / arxiv_id
    attempts_dir = paper_dir / "attempts"
    attempts_dir.mkdir(parents=True, exist_ok=True)

    result = AgenticResult(arxiv_id=arxiv_id, status="failed")
    stage_log: list[dict] = []
    if trace is not None:
        trace.emit(
            "paper.started",
            paper_id=arxiv_id,
            stage="context",
            status="running",
        )

    def emit_paper_completed() -> None:
        if trace is not None:
            trace.emit(
                "paper.completed",
                paper_id=arxiv_id,
                stage="final",
                status=result.status,
                data={
                    "usage_totals": dict(result.usage_totals),
                    "validator_errors": result.validator_errors,
                    "validator_warnings": result.validator_warnings,
                    "error": result.error,
                },
            )

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
    if trace is not None:
        trace.emit(
            "context.packed",
            paper_id=arxiv_id,
            stage="context",
            status="completed",
            data={"files": len(context.files), "chars": len(context.text)},
            payload_kind="context.manifest",
            payload=context.manifest(),
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

    system_prompt = build_agentic_system_prompt(workspace, task_surface)
    roster_rules = render_rule_profile(workspace, "hvs_roster", "prompt")
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
    if stream_responses:
        request_parameters["stream_responses"] = True
    request_parameters["rule_profile_id"] = "hvs_extractor"
    request_parameters["rule_profile_sha256"] = rule_profile_sha256(
        workspace, "hvs_extractor"
    )
    request_parameters["review_rule_profile_id"] = "hvs_reviewer"
    request_parameters["review_rule_profile_sha256"] = rule_profile_sha256(
        workspace, "hvs_reviewer"
    )
    request_parameters.update(surface_binding(workspace, task_surface))
    if request_extra:
        request_parameters.update(request_extra)
    request_parameters["reviewer_model"] = reviewer_model
    if method_fingerprint:
        request_parameters["method_fingerprint"] = method_fingerprint

    served_model = ""
    reviewer_served_model = ""
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
    ) -> ReactUnit:
        return ReactUnit(
            name=name,
            kind=kind,
            system_prompt=system_prompt,
            task_prompt=task_prompt,
            fs=fs,
            submit_name=submit_name,
            submit_key=submit_key,
            submit_check=submit_check,
            transport=transport,
            transport_kwargs=extractor_kwargs,
            archive=archive,
            usage_totals=result.usage_totals,
            trace=trace,
            trace_paper_id=arxiv_id,
            stream_responses=stream_responses,
        )

    try:
        frozen_bundle: dict[str, Any] | None = None
        frozen_stubs: list[dict[str, Any]] | None = None
        if roster_cache_root is not None:
            roster_system = build_agentic_roster_system_prompt(workspace)
            roster_task = agentic_roster_task_prompt(skeleton, fs)
            shared_key, key_components = roster_shared_key(
                method="C",
                arxiv_id=arxiv_id,
                model=model,
                provider=dict(request_extra or {}),
                prompt_sha256=canonical_sha256(
                    {"system": roster_system, "task": roster_task}
                ),
                rule_sha256=rule_profile_sha256(workspace, "hvs_roster"),
                context_sha256=canonical_sha256(
                    {"manifest": context.manifest(), "text": context.text}
                ),
                code_version=prompt_version,
            )

            def produce_roster() -> dict[str, Any]:
                before = dict(result.usage_totals)
                unit = ReactUnit(
                    name="roster",
                    kind="roster",
                    system_prompt=roster_system,
                    task_prompt=roster_task,
                    fs=fs,
                    submit_name="submit_roster",
                    submit_key="roster",
                    submit_check=lambda payload: roster_structure_errors(
                        payload, arxiv_id
                    ),
                    transport=transport,
                    transport_kwargs=extractor_kwargs,
                    archive=archive,
                    usage_totals=result.usage_totals,
                    trace=trace,
                    trace_paper_id=arxiv_id,
                    stream_responses=stream_responses,
                )
                payload = unit.run()
                result.roster_calls = unit.calls
                if payload is None:
                    raise RuntimeError(
                        unit.failure_reason or "roster submission missing"
                    )
                usage = {
                    key: int(result.usage_totals.get(key, 0))
                    - int(before.get(key, 0))
                    for key in result.usage_totals
                    if int(result.usage_totals.get(key, 0))
                    - int(before.get(key, 0))
                }
                return {
                    "method": "C",
                    "arxiv_id": arxiv_id,
                    "producer": {
                        "model": model,
                        "served_model": unit.served_model or model,
                        "provider": dict(request_extra or {}),
                        "code_version": prompt_version,
                    },
                    "extraction": payload.get("extraction", {}),
                    "candidates": payload.get("candidates", []),
                    "candidate_groups_considered": payload.get(
                        "candidate_groups_considered", []
                    ),
                    "usage": usage,
                }

            try:
                frozen_bundle, result.roster_cache_hit = get_or_create_roster_bundle(
                    cache_root=roster_cache_root,
                    shared_key=shared_key,
                    key_components=key_components,
                    paper_dir=paper_dir,
                    producer=produce_roster,
                )
            except LLMTransportError:
                raise
            except Exception as exc:
                result.error = f"roster: {type(exc).__name__}: {exc}"
                result.status = "roster_failed"
                _write_report(paper_dir, result, [], stage_log)
                emit_paper_completed()
                return result
            result.roster_bundle_id = str(frozen_bundle.get("bundle_id") or "")
            result.shared_roster_usage = {
                str(key): int(value)
                for key, value in (frozen_bundle.get("usage") or {}).items()
                if isinstance(value, int)
            }
            frozen_stubs = roster_stubs(frozen_bundle)
            stage_log.append(
                {
                    "stage": "roster",
                    "bundle_id": result.roster_bundle_id,
                    "cache_hit": result.roster_cache_hit,
                    "calls": result.roster_calls,
                    "candidates": len(frozen_stubs),
                }
            )

        # ---- Stage 1: surface-specific plan ------------------------------
        plan_unit = make_unit(
            "plan",
            "plan",
            plan_task_prompt(
                skeleton,
                fs,
                roster_rules,
                task_surface,
                frozen_roster_bundle=frozen_bundle,
            ),
            "submit_scaffold",
            "document",
            lambda payload: scaffold_structure_errors(
                payload, arxiv_id, frozen_roster=frozen_stubs
            ),
        )
        scaffold = plan_unit.run()
        result.plan_calls = plan_unit.calls
        served_model = plan_unit.served_model or served_model
        if scaffold is None:
            result.status = "plan_failed"
            _write_report(paper_dir, result, [], stage_log)
            emit_paper_completed()
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
                candidate_task_prompt(scaffold, stub, task_surface),
                "submit_candidate",
                "candidate",
                lambda payload, s=stub: batch_structure_errors(
                    {"candidates": [payload]}, [s], step_ids
                )
                + validate_generated_candidate(payload, task_surface),
            )
            record = unit.run()
            result.candidate_calls += unit.calls
            served_model = unit.served_model or served_model
            candidate_units.append(unit)
            if record is None:
                result.status = "candidate_failed"
                stage_log.append({"stage": f"cand-{index:03d}", "calls": unit.calls, "failed": True})
                _write_report(paper_dir, result, [], stage_log)
                emit_paper_completed()
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
                pipeline_name=PIPELINE_NAME,
            )
            document = hydrate_surface_document(document, task_surface)
            surface_errors = validate_surface_document(document, task_surface)
            report = validator.validate_hvs_candidates_report(
                document, workspace=workspace, require_complete=True
            )
            errors = surface_errors + list(report.errors)
            warnings = list(report.warnings)
            result.validator_warning_messages = list(warnings)
            result.validator_findings = [
                {
                    "severity": "error",
                    "rule_id": "task_surface.contract",
                    "path": "$",
                    "root_key": "task_surface.contract",
                    "message": error,
                }
                for error in surface_errors
            ] + (
                list(report.finding_dicts())
                if callable(getattr(report, "finding_dicts", None))
                else []
            )
            result.validator_groups = _group_validator_findings(result.validator_findings)
            cjk_paths = find_cjk_strings(document)
            if trace is not None:
                trace.emit(
                    "validation.completed",
                    paper_id=arxiv_id,
                    stage="validation",
                    status="passed" if not errors and not cjk_paths else "needs_repair",
                    data={
                        "errors": len(errors),
                        "warnings": len(warnings),
                        "cjk_paths": len(cjk_paths),
                    },
                    payload_kind="validation.result",
                    payload={"errors": errors, "warnings": warnings, "cjk_paths": cjk_paths},
                )

        def targeted_repair(
            extra_by_candidate: dict[int, list[str]],
            scaffold_extra: list[str],
            label: str,
        ) -> bool:
            nonlocal scaffold, step_ids, served_model, roster
            nonlocal candidate_units, candidate_records
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
                    payload,
                    arxiv_id,
                    repair=True,
                    frozen_roster=frozen_stubs,
                )
                repaired = plan_unit.run(
                    extra_user=feedback, budget=MAX_TOOL_CALLS["repair"]
                )
                result.repair_calls += plan_unit.calls - result.plan_calls
                result.plan_calls = plan_unit.calls
                if repaired is None:
                    return False
                new_roster = repaired.get("candidates", [])
                aligned, added, deleted = reconcile_roster_records(
                    roster, candidate_records, new_roster
                )
                old_units = {
                    roster_record_id(stub): unit
                    for stub, unit in zip(roster, candidate_units, strict=True)
                }
                scaffold = repaired
                step_ids = scaffold_step_ids(scaffold)
                rebuilt_units: list[ReactUnit] = []
                rebuilt_records: list[list[dict]] = []
                for stub, records in zip(new_roster, aligned, strict=True):
                    record_id = roster_record_id(stub)
                    if records is not None:
                        rebuilt_units.append(old_units[record_id])
                        rebuilt_records.append(records)
                        continue
                    unit = make_unit(
                        f"cand-review-{len(rebuilt_units):03d}",
                        "candidate",
                        candidate_task_prompt(scaffold, stub, task_surface),
                        "submit_candidate",
                        "candidate",
                        lambda payload, s=stub: batch_structure_errors(
                            {"candidates": [payload]}, [s], step_ids
                        )
                        + validate_generated_candidate(payload, task_surface),
                    )
                    record = unit.run(budget=MAX_TOOL_CALLS["repair"])
                    result.repair_calls += unit.calls
                    result.candidate_calls += unit.calls
                    served_model = unit.served_model or served_model
                    if record is None:
                        return False
                    rebuilt_units.append(unit)
                    rebuilt_records.append([record])
                candidate_units = rebuilt_units
                candidate_records = rebuilt_records
                roster = list(new_roster)
                stage_log.append(
                    {
                        "stage": "roster_rebuild",
                        "added": added,
                        "deleted": deleted,
                        "retained": len(roster) - len(added),
                    }
                )
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
                else:
                    return False
            return True

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

        # ---- Stage 3: bounded agentic review + one revision ----------------
        review_failed = False
        pre_review_invalid = bool(errors or cjk_paths)
        if pre_review_invalid:
            stage_log.append(
                {
                    "stage": "review",
                    "skipped": True,
                    "reason": "pre_review_validation_failed",
                    "errors": len(errors),
                    "cjk": len(cjk_paths),
                }
            )
        else:
            review_outcome = run_agentic_review(
                workspace=workspace,
                document=document,
                task_surface=task_surface,
                fs=fs,
                transport=transport,
                transport_kwargs=reviewer_kwargs,
                archive=archive,
                usage_totals=result.usage_totals,
                trace=trace,
                trace_paper_id=arxiv_id,
                stream_responses=stream_responses,
            )
            review = review_outcome.payload
            result.review_calls = review_outcome.calls
            reviewer_served_model = review_outcome.served_model
            request_parameters["reviewer_served_model"] = (
                reviewer_served_model or reviewer_model
            )
            if review is not None:
                challenges = review_outcome.challenges
                result.review_challenges = len(challenges)
                (paper_dir / "review.json").write_text(
                    json.dumps(review, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                grouped = dict(review_outcome.actionable_by_candidate)
                document_level = grouped.pop(-1, [])
                result.review_fix_targets = len(grouped) + (
                    1 if document_level else 0
                )
                if grouped or document_level:
                    if not targeted_repair(
                        grouped, document_level, "REVIEWER CHALLENGE"
                    ):
                        review_failed = True
                        result.error = (
                            "review_revision_failed: extractor did not return "
                            "a valid targeted revision"
                        )
                    validate_current()
                stage_log.append(
                    {
                        "stage": "review",
                        "calls": review_outcome.calls,
                        "challenges": len(challenges),
                        "fix_targets": result.review_fix_targets,
                        "stop_reason": review_outcome.stop_reason,
                        "revision_failed": review_failed,
                        "error": result.error if review_failed else "",
                    }
                )
            else:
                review_failed = True
                result.error = review_outcome.failure_reason
                stage_log.append(
                    {
                        "stage": "review",
                        "calls": review_outcome.calls,
                        "failed": True,
                        "error": review_outcome.failure_reason,
                        "stop_reason": review_outcome.stop_reason,
                    }
                )

        # Refresh provenance after the reviewer call so the actual served
        # reviewer model is archived in the validated paper product.
        if not errors and not cjk_paths:
            validate_current()

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
        result.status = (
            "validator_errors"
            if pre_review_invalid
            else reviewed_delivery_status(
                review_failed=review_failed,
                errors=errors,
                cjk_paths=cjk_paths,
            )
        )
    except LLMTransportError as exc:
        result.transport_error = exc.to_dict()
        _write_transport_error(attempts_dir, exc)
        result.error = str(exc)
        result.status = "transport_error"
    except RuntimeError as exc:
        result.error = str(exc)
        result.status = "transport_error"
    except Exception as exc:  # always leave a report behind for debugging
        result.error = f"{type(exc).__name__}: {exc}"
        result.status = "harness_error"
    _write_report(paper_dir, result, errors, stage_log)
    emit_paper_completed()
    return result


def _write_report(
    paper_dir: Path,
    result: AgenticResult,
    errors: list[str],
    stage_log: list[dict],
) -> None:
    paper_dir.mkdir(parents=True, exist_ok=True)
    result.downstream_usage = {
        key: max(
            0,
            int(value)
            - (
                int(result.shared_roster_usage.get(key, 0))
                if not result.roster_cache_hit
                else 0
            ),
        )
        for key, value in result.usage_totals.items()
    }
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
                "validator_warnings": result.validator_warning_messages,
                "validator_warnings_count": result.validator_warnings,
                "validator_findings": result.validator_findings,
                "validator_groups": result.validator_groups,
                "cjk_paths": result.cjk_paths,
                "usage_totals": result.usage_totals,
                "roster_bundle_id": result.roster_bundle_id,
                "roster_cache_hit": result.roster_cache_hit,
                "roster_calls": result.roster_calls,
                "shared_roster_usage": result.shared_roster_usage,
                "downstream_usage": result.downstream_usage,
                "transport_error": result.transport_error,
                "error": result.error,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _group_validator_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for finding in findings:
        key = (str(finding.get("severity") or ""), str(finding.get("root_key") or "validator"))
        grouped.setdefault(key, []).append(finding)
    return [
        {
            "severity": severity,
            "root_key": root_key,
            "count": len(items),
            "rule_ids": sorted({str(item.get("rule_id") or "") for item in items}),
            "paths": sorted({str(item.get("path") or "") for item in items}),
            "messages": sorted({str(item.get("message") or "") for item in items}),
        }
        for (severity, root_key), items in sorted(grouped.items())
    ]


def _write_transport_error(attempts_dir: Path, exc: LLMTransportError) -> None:
    stage = re.sub(r"[^A-Za-z0-9._-]+", "-", exc.stage or "transport")
    call_suffix = exc.call_id.rsplit(":", 1)[-1] if exc.call_id else "1"
    try:
        call_number = int(call_suffix)
    except ValueError:
        call_number = 1
    path = attempts_dir / f"{stage}-call-{call_number:02d}.transport-error.json"
    path.write_text(
        json.dumps(exc.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
