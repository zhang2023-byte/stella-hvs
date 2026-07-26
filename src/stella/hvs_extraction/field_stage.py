"""extract_candidate_fields_and_evidence stage with targeted repair.

One field-extraction call per frozen candidate, mutually independent and
parallel. Each candidate sees only its assigned frozen identity; code
associates the returned payload with the hidden record_id. Every
candidate gets one initial request, at most one format correction, and at
most one drift-guarded evidence correction — never more than three requests
. Success is immutable; one candidate's failure never invalidates the
roster or other candidates. No post-field scientific review.
"""

from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stella.hvs_extraction.bounded_call import (
    OK,
    ProviderRequestBudget,
    Transport,
    execute_with_evidence_correction,
    execute_with_format_correction,
)
from stella.hvs_extraction.cleaning import strip_tex_comments
from stella.hvs_extraction.ecsv import (
    parse_ecsv_structure,
    resolve_paper_ecsv_path,
)
from stella.hvs_extraction.field_prompts import build_field_prompts
from stella.hvs_extraction.field_schema import (
    SUBMIT_CANDIDATE_FIELDS,
    build_field_submission_schema,
)
from stella.hvs_extraction.field_validate import (
    BIBLIOGRAPHY_UNRESOLVED,
    FieldValidationContext,
    hydrate_field_submission,
    resolve_bibliography_key,
    validate_field_submission,
)
from stella.hvs_extraction.method_config import HvsExtractionMethodConfig
from stella.hvs_extraction.prepare import (
    RUNS_RELATIVE_DIR,
    estimate_tokens,
    render_ecsv_block,
)
from stella.hvs_extraction.ecsv import SelectedEcsv
from stella.hvs_extraction.roster_stage import (
    ROSTER_COMPLETE,
    _atomic_write_json,
    _route_kwargs,
)
from stella.hvs_extraction.tex_graph import resolve_tex_graph
from stella.lit.extraction_rules import rule_profile_sha256
from stella.schema_registry import schema_ref

FIELDS_COMPLETE = "fields_complete"
FIELD_EXTRACTION_FAILED = "field_extraction_failed"
FIELD_STAGE_COMPLETE = "field_stage_complete"
NO_TRUSTED_ROSTER = "no_trusted_roster"

MODE_FULL = "full"
MODE_TEX_ONLY = "tex_only_due_to_context_budget"
MODE_FIELD_TOO_LARGE = "field_input_too_large"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def field_allowed_roots(issues: list[Any]) -> set[str]:
    """Smallest replaceable field-level subtree per issue."""

    roots: set[str] = set()
    for issue in issues:
        path = issue.path
        if path.startswith("$.core."):
            parts = path.split(".")
            roots.add(".".join(parts[:4]))
        elif path.startswith("$.candidate_origin"):
            roots.add("$.candidate_origin")
        elif path.startswith("$.provenance_conflicts["):
            roots.add(path.split("].")[0] + "]")
        else:
            roots.add(path)
    return roots


class _FieldStage:
    def __init__(
        self,
        workspace: Path,
        run_id: str,
        arxiv_id: str,
        *,
        config: HvsExtractionMethodConfig,
        transport: Transport,
        api_key: str,
        base_url: str,
        sleep,
        max_workers: int,
        progress=None,
    ) -> None:
        self.workspace = workspace
        self.run_id = run_id
        self.arxiv_id = arxiv_id
        self.config = config
        self.transport = transport
        self.api_key = api_key
        self.base_url = base_url
        self.sleep = sleep
        self.max_workers = max_workers
        self.progress = progress
        self.run_dir = workspace / RUNS_RELATIVE_DIR / run_id
        self.paper_dir = self.run_dir / "papers" / arxiv_id
        self.candidates_dir = self.paper_dir / "candidates"

    def execute(self) -> dict[str, Any]:
        roster = json.loads((self.paper_dir / "roster_final.json").read_text(encoding="utf-8"))
        if roster["status"] != ROSTER_COMPLETE:
            return {
                "status": NO_TRUSTED_ROSTER,
                "paper": {"arxiv_id": self.arxiv_id},
                "candidates": {},
            }
        prepared = json.loads(
            (self.run_dir / "prepared_inputs" / f"{self.arxiv_id}.json").read_text(
                encoding="utf-8"
            )
        )
        self.prepared = prepared
        self.roster = roster
        graph = resolve_tex_graph(
            self.workspace / "literature" / self.arxiv_id / "arxiv_source"
        )
        self.verify_immutable_context(graph, prepared)

        candidates = roster["candidates"]
        mode = prepared["context"]["field_context_mode"]
        if mode == MODE_FIELD_TOO_LARGE:
            for candidate in candidates:
                self.write_candidate_artifact(
                    candidate,
                    status=FIELD_EXTRACTION_FAILED,
                    fields=None,
                    failure={
                        "code": MODE_FIELD_TOO_LARGE,
                        "detail": "the paper-level field source context exceeds the frozen budget",
                        "attempts": [],
                    },
                    provenance=None,
                )
            return self.summary(candidates)

        tex_paths = list(graph.included)
        self.tex_texts = {name: graph.texts[name] for name in tex_paths}
        self.tex_sha256 = {name: graph.files[name].sha256 for name in tex_paths}
        self.tex_line_counts = {
            name: graph.files[name].line_count for name in tex_paths
        }

        ecsv_selected = prepared["ecsv"]["selected"] if mode == MODE_FULL else []
        ecsv_paths = [item["ecsv_path"] for item in ecsv_selected]
        self.ecsv_structures = {}
        self.ecsv_texts = {}
        paper_literature_dir = self.workspace / "literature" / self.arxiv_id
        for item in ecsv_selected:
            path = resolve_paper_ecsv_path(
                paper_literature_dir, item["ecsv_path"]
            )
            text = path.read_text(encoding="utf-8")
            structure = parse_ecsv_structure(path)
            if structure.sha256 != item["sha256"]:
                raise ValueError(
                    f"context_mutation: {item['ecsv_path']} changed after preparation"
                )
            self.ecsv_structures[item["ecsv_path"]] = structure
            self.ecsv_texts[item["ecsv_path"]] = text
        ecsv_blocks = [
            render_ecsv_block(
                SelectedEcsv(
                    ecsv_path=item["ecsv_path"],
                    source_tex_path=item["source_tex_path"],
                    source_tex_start_line=item["source_tex_start_line"],
                    source_tex_end_line=item["source_tex_end_line"],
                    label=item["label"],
                    structure=self.ecsv_structures[item["ecsv_path"]],
                ),
                self.ecsv_texts[item["ecsv_path"]],
            )
            for item in ecsv_selected
        ]

        self.validation_context = FieldValidationContext(
            tex_line_counts=self.tex_line_counts,
            tex_texts=self.tex_texts,
            ecsv_structures=self.ecsv_structures,
            ecsv_texts=self.ecsv_texts,
        )
        self.schema = build_field_submission_schema(tex_paths, ecsv_paths)
        self.schema_hash = _sha256_text(
            json.dumps(self.schema, ensure_ascii=False, sort_keys=True)
        )
        self.manuscript_view = prepared["manuscript"]["view"]
        self.ecsv_blocks = ecsv_blocks
        self.bibliography_sources = prepared["bibliography"]
        self.source_dir = paper_literature_dir / "arxiv_source"

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            list(pool.map(self.run_candidate, candidates))
        return self.summary(candidates)

    def verify_immutable_context(self, graph, prepared: dict[str, Any]) -> None:
        manifest_files = prepared["manuscript"]["files"]
        for name in prepared["manuscript"]["included"]:
            recorded = manifest_files.get(name)
            current = graph.files.get(name)
            if recorded is None or current is None or recorded["sha256"] != current.sha256:
                raise ValueError(f"context_mutation: {name} changed after preparation")

    def model_visible_candidate(self, candidate: dict[str, Any]) -> str:
        def trim_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [
                {
                    "path": ref["path"],
                    "start_line": ref["start_line"],
                    "end_line": ref["end_line"],
                    "resolved_text": ref["resolved_text"],
                }
                for ref in refs
            ]

        visible = {
            "identifiers": [
                {"value": item["value"], "source_refs": trim_refs(item["source_refs"])}
                for item in candidate["identifiers"]
            ],
            "qualification": {
                "reason": candidate["qualification"]["reason"],
                "source_refs": trim_refs(candidate["qualification"]["source_refs"]),
            },
        }
        return json.dumps(visible, ensure_ascii=False, indent=2)

    def run_candidate(self, candidate: dict[str, Any]) -> None:
        started = time.monotonic()
        if self.progress is not None:
            self.progress(
                "candidate_start",
                arxiv_id=self.arxiv_id,
                stage="field",
                candidate=candidate["record_id"],
            )
        try:
            self._run_candidate(candidate)
        finally:
            path = self.candidates_dir / f"{candidate['record_id']}.json"
            status = "harness_failure"
            tokens = 0
            if path.is_file():
                artifact = json.loads(path.read_text(encoding="utf-8"))
                status = artifact["status"]
                tokens = sum(
                    int(usage.get("total_tokens") or 0)
                    for usage in artifact.get("usages") or []
                    if isinstance(usage, dict)
                )
            if self.progress is not None:
                self.progress(
                    "candidate_end",
                    arxiv_id=self.arxiv_id,
                    stage="field",
                    candidate=candidate["record_id"],
                    status=status,
                    duration_seconds=time.monotonic() - started,
                    tokens=tokens,
                )

    def _run_candidate(self, candidate: dict[str, Any]) -> None:
        record_id = candidate["record_id"]
        field_mode = str(self.config.core_field_model.structured_output_mode)
        if field_mode != "tool_submission":
            raise ValueError(
                "json_object mode is scoped to the roster extractor; the field "
                "stage supports only tool_submission"
            )
        prompts = build_field_prompts(
            self.workspace,
            manuscript_view=self.manuscript_view,
            ecsv_blocks=self.ecsv_blocks,
            assigned_candidate_json=self.model_visible_candidate(candidate),
        )
        provenance = {
            "model": self.config.core_field_model.model,
            "provider": self.config.core_field_model.provider,
            "structured_output_mode": self.config.core_field_model.structured_output_mode,
            "temperature": self.config.core_field_model.temperature,
            "submission_function": SUBMIT_CANDIDATE_FIELDS,
            "rule_profile": prompts["profile"],
            "rule_profile_sha256": rule_profile_sha256(self.workspace, prompts["profile"]),
            "system_prompt_sha256": prompts["system_sha256"],
            "user_prompt_sha256": prompts["user_sha256"],
            "submission_schema_sha256": self.schema_hash,
            "field_shared_prefix_sha256": self.prepared["context"][
                "field_shared_prefix_sha256"
            ],
            "request_policy": {
                "scope": "per_candidate_field_stage",
                "max_physical_provider_requests": 3,
                "shared_across": [
                    "initial",
                    "transport_retry",
                    "format_correction",
                    "evidence_correction",
                ],
            },
        }
        estimate = estimate_tokens(prompts["system"] + prompts["user"])
        budget = self.config.field_context_budget.input_budget()
        if estimate > budget:
            self.write_candidate_artifact(
                candidate,
                status=FIELD_EXTRACTION_FAILED,
                fields=None,
                failure={
                    "code": "input_too_large",
                    "detail": (
                        f"candidate request is {estimate} estimated tokens, over "
                        f"the field input budget {budget}; no API request was made"
                    ),
                    "attempts": [],
                },
                provenance=provenance,
            )
            return
        messages = [
            {"role": "system", "content": prompts["system"]},
            {"role": "user", "content": prompts["user"]},
        ]
        kwargs = _route_kwargs(
            self.config.core_field_model,
            tool_name=SUBMIT_CANDIDATE_FIELDS,
            schema=self.schema,
            api_key=self.api_key,
            base_url=self.base_url,
            seed=None,
            max_tokens=self.config.field_context_budget.reserve_output,
        )
        request_budget = ProviderRequestBudget(limit=3)
        first = execute_with_format_correction(
            transport=self.transport,
            transport_kwargs=kwargs,
            tool_name=SUBMIT_CANDIDATE_FIELDS,
            schema=self.schema,
            messages=messages,
            sleep=self.sleep,
            mode=field_mode,
            request_budget=request_budget,
            input_token_budget=budget,
            progress=self.progress,
            progress_context={
                "arxiv_id": self.arxiv_id,
                "stage": "field",
                "candidate": record_id,
            },
        )
        if first.status != OK:
            self.write_candidate_artifact(
                candidate,
                status=FIELD_EXTRACTION_FAILED,
                fields=None,
                failure={
                    "code": first.status,
                    "initial_errors": first.initial_errors,
                    "correction_errors": first.correction_errors,
                    "attempts": first.attempts,
                    "transport_error": first.transport_error,
                    "detail": first.other_error,
                },
                provenance=provenance,
                attempts=first.attempts,
                usages=list(first.usages),
                repair_history=list(first.repair_history),
            )
            return
        assert first.payload is not None
        issues = validate_field_submission(first.payload, self.validation_context)
        payload = first.payload
        attempts = first.attempts
        usages = list(first.usages)
        repair_history = list(first.repair_history)
        if issues:
            second = execute_with_evidence_correction(
                transport=self.transport,
                transport_kwargs=kwargs,
                tool_name=SUBMIT_CANDIDATE_FIELDS,
                schema=self.schema,
                messages=messages,
                previous_payload=first.payload,
                issues=issues,
                validate_fn=self.validate,
                sleep=self.sleep,
                allowed_roots_fn=field_allowed_roots,
                mode=field_mode,
                request_budget=request_budget,
                input_token_budget=budget,
                progress=self.progress,
                progress_context={
                    "arxiv_id": self.arxiv_id,
                    "stage": "field",
                    "candidate": record_id,
                },
            )
            attempts = [*first.attempts, *second.attempts]
            usages.extend(second.usages)
            repair_history.extend(second.repair_history)
            if second.status != OK:
                self.write_candidate_artifact(
                    candidate,
                    status=FIELD_EXTRACTION_FAILED,
                    fields=None,
                    failure={
                        "code": second.status,
                        "initial_errors": second.initial_errors,
                        "correction_errors": second.correction_errors,
                        "unexpected_changes": second.unexpected_changes,
                        "attempts": attempts,
                        "transport_error": second.transport_error,
                        "detail": second.other_error,
                    },
                    provenance=provenance,
                    attempts=attempts,
                    usages=usages,
                    repair_history=repair_history,
                )
                return
            payload = second.payload
        hydrated = hydrate_field_submission(
            payload, self.validation_context, tex_sha256=self.tex_sha256
        )
        bibliography = self.resolve_origin_bibliography(hydrated)
        self.write_candidate_artifact(
            candidate,
            status=FIELDS_COMPLETE,
            fields=hydrated,
            failure=None,
            provenance=provenance,
            bibliography=bibliography,
            attempts=attempts,
            usages=usages,
            repair_history=repair_history,
        )

    def validate(self, payload: dict[str, Any]):
        return validate_field_submission(payload, self.validation_context)

    def resolve_origin_bibliography(self, hydrated: dict[str, Any]) -> dict[str, Any]:
        origin = hydrated["candidate_origin"]
        derived = {
            "origin_type": origin["origin_type"],
            "paper_reassesses_unbound_status": origin["origin_type"]
            == "cited_from_literature",
        }
        if origin["origin_type"] != "cited_from_literature":
            return {**derived, "resolution": None}
        resolution = resolve_bibliography_key(
            origin["bibkey"], self.bibliography_sources, self.source_dir
        )
        return {
            **derived,
            "resolution": {
                "status": resolution.status,
                "bibkey": resolution.bibkey,
                "reason": resolution.reason,
                "reference": resolution.reference,
                "diagnostics": resolution.diagnostics,
            },
        }

    def write_candidate_artifact(
        self,
        candidate: dict[str, Any],
        *,
        status: str,
        fields: dict[str, Any] | None,
        failure: dict[str, Any] | None,
        provenance: dict[str, Any] | None,
        bibliography: dict[str, Any] | None = None,
        attempts: list[dict[str, Any]] | None = None,
        usages: list[dict[str, Any] | None] | None = None,
        repair_history: list[dict[str, Any]] | None = None,
    ) -> None:
        artifact = {
            "schema": schema_ref("hvs_extraction.candidate_fields"),
            "generated_at": _utc_now(),
            "paper": {"arxiv_id": self.arxiv_id},
            "run_id": self.run_id,
            "record_id": candidate["record_id"],
            "status": status,
            "fields": fields,
            "bibliography": bibliography,
            "failure": failure,
            "attempts": attempts or (failure or {}).get("attempts", []),
            "usages": usages or [],
            "repair_history": repair_history or [],
            "provenance": provenance,
        }
        _atomic_write_json(
            self.candidates_dir / f"{candidate['record_id']}.json", artifact
        )

    def summary(self, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        statuses: dict[str, str] = {}
        for candidate in candidates:
            path = self.candidates_dir / f"{candidate['record_id']}.json"
            artifact = json.loads(path.read_text(encoding="utf-8"))
            statuses[candidate["record_id"]] = artifact["status"]
        return {
            "status": FIELD_STAGE_COMPLETE,
            "paper": {"arxiv_id": self.arxiv_id},
            "candidates": statuses,
        }


def run_field_stage(
    workspace: Path,
    run_id: str,
    arxiv_id: str,
    *,
    config: HvsExtractionMethodConfig,
    transport: Transport,
    api_key: str = "",
    base_url: str = "",
    sleep=time.sleep,
    max_workers: int = 4,
    progress=None,
) -> dict[str, Any]:
    """Run per-candidate field extraction for one paper."""

    config.assert_frozen()
    stage = _FieldStage(
        workspace,
        run_id,
        arxiv_id,
        config=config,
        transport=transport,
        api_key=api_key,
        base_url=base_url,
        sleep=sleep,
        max_workers=max_workers,
        progress=progress,
    )
    return stage.execute()
