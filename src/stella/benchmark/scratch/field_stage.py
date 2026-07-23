"""extract_candidate_fields_and_evidence stage with targeted repair.

One field-extraction call per frozen candidate, mutually independent and
parallel (D025). Each candidate sees only its assigned frozen identity; code
associates the returned payload with the hidden record_id (D026). Every
candidate gets one initial request, at most one format correction, and at
most one drift-guarded evidence correction — never more than three requests
(D046). Success is immutable; one candidate's failure never invalidates the
roster or other candidates (D045). No post-field scientific review (D044).
"""

from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from stella.benchmark.scratch.bounded_call import (
    OK,
    Transport,
    execute_with_evidence_correction,
    execute_with_format_correction,
)
from stella.benchmark.scratch.cleaning import strip_tex_comments
from stella.benchmark.scratch.ecsv import parse_ecsv_structure
from stella.benchmark.scratch.field_prompts import build_field_prompts
from stella.benchmark.scratch.field_schema import (
    SUBMIT_CANDIDATE_FIELDS,
    build_field_submission_schema,
)
from stella.benchmark.scratch.field_validate import (
    BIBLIOGRAPHY_UNRESOLVED,
    FieldValidationContext,
    hydrate_field_submission,
    resolve_bibliography_key,
    validate_field_submission,
)
from stella.benchmark.scratch.method_config import ScratchMethodConfig
from stella.benchmark.scratch.prepare import (
    RUNS_RELATIVE_DIR,
    estimate_tokens,
    render_ecsv_block,
)
from stella.benchmark.scratch.ecsv import SelectedEcsv
from stella.benchmark.scratch.roster_stage import (
    ROSTER_COMPLETE,
    _atomic_write_json,
    _route_kwargs,
)
from stella.benchmark.scratch.tex_graph import resolve_tex_graph
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
    return datetime.now().isoformat(timespec="seconds")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def field_allowed_roots(issues: list[Any]) -> set[str]:
    """Smallest replaceable field-level subtree per issue (D046)."""

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
        config: ScratchMethodConfig,
        transport: Transport,
        api_key: str,
        base_url: str,
        sleep,
        max_workers: int,
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
            path = paper_literature_dir / item["ecsv_path"]
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
        record_id = candidate["record_id"]
        prompts = build_field_prompts(
            self.workspace,
            manuscript_view=self.manuscript_view,
            ecsv_blocks=self.ecsv_blocks,
            assigned_candidate_json=self.model_visible_candidate(candidate),
        )
        provenance = {
            "model": self.config.field_extractor.model,
            "provider": self.config.field_extractor.provider,
            "structured_output_mode": self.config.field_extractor.structured_output_mode,
            "temperature": self.config.field_extractor.temperature,
            "submission_function": SUBMIT_CANDIDATE_FIELDS,
            "rule_profile": prompts["profile"],
            "rule_profile_sha256": rule_profile_sha256(self.workspace, prompts["profile"]),
            "system_prompt_sha256": prompts["system_sha256"],
            "user_prompt_sha256": prompts["user_sha256"],
            "submission_schema_sha256": self.schema_hash,
            "field_shared_prefix_sha256": self.prepared["context"][
                "field_shared_prefix_sha256"
            ],
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
            self.config.field_extractor,
            tool_name=SUBMIT_CANDIDATE_FIELDS,
            schema=self.schema,
            api_key=self.api_key,
            base_url=self.base_url,
            seed=None,
            max_tokens=self.config.field_context_budget.reserve_output,
        )
        first = execute_with_format_correction(
            transport=self.transport,
            transport_kwargs=kwargs,
            tool_name=SUBMIT_CANDIDATE_FIELDS,
            schema=self.schema,
            messages=messages,
            sleep=self.sleep,
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
                },
                provenance=provenance,
            )
            return
        assert first.payload is not None
        issues = validate_field_submission(first.payload, self.validation_context)
        payload = first.payload
        attempts = first.attempts
        usages = [first.usage] if first.usage else []
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
            )
            attempts = [*first.attempts, *second.attempts]
            if second.usage:
                usages.append(second.usage)
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
                    },
                    provenance=provenance,
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
    ) -> None:
        artifact = {
            "schema": schema_ref("benchmark.hvs_extraction_scratch.candidate_fields"),
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
    config: ScratchMethodConfig,
    transport: Transport,
    api_key: str = "",
    base_url: str = "",
    sleep=time.sleep,
    max_workers: int = 4,
) -> dict[str, Any]:
    """Run per-candidate field extraction for one paper (D025, D044-D046)."""

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
    )
    return stage.execute()
