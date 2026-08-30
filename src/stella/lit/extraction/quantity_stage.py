"""Per-object grouped-quantity extraction stage.

One failed object quantity stage does not delete its L1 contribution:
the artifact records ``failed`` with an explicit failure object and an
empty quantities list, keeping null scientific
judgment and failed delivery distinct.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from stella.lit.extraction.bounded_call import (
    EVIDENCE_VALIDATION_FAILURE,
    OK,
    ProviderRequestBudget,
    Transport,
    execute_with_evidence_correction,
    execute_with_format_correction,
)
from stella.lit.extraction.prepare import estimate_tokens
from stella.lit.extraction.field_validate import FieldValidationContext
from stella.lit.extraction.ecsv import (
    SelectedEcsv,
    parse_ecsv_structure,
    resolve_paper_ecsv_path,
)
from stella.lit.extraction.prepare import render_ecsv_block
from stella.lit.extraction.tex_graph import resolve_frozen_tex_graph
from stella.lit.extraction.quantity_prompts import (
    build_quantity_prompts,
)
from stella.lit.extraction.quantity_schema import (
    SUBMIT_OBJECT_QUANTITIES,
    build_quantity_submission_schema,
)
from stella.lit.extraction.quantity_validate import (
    hydrate_quantity_submission,
    quantity_allowed_roots,
    validate_quantity_submission,
)
from stella.lit.extraction.method_config import (
    CONTRIBUTION_RULE_PROFILE,
    HvsContributionMethodConfig,
    HvsModelRoute,
)
from stella.lit.extraction.roster_stage import _route_kwargs
from stella.lit.extraction_rules import rule_profile_sha256
from stella.schema_registry import schema_ref
from stella.lit.extraction.run_policy import assert_contribution_run_dir

QUANTITY_EXTRACTION_COMPLETE = "complete"
QUANTITY_EXTRACTION_FAILED = "failed"
NO_TRUSTED_ROSTER = "no_trusted_roster"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def model_visible_contribution(contribution: dict[str, Any]) -> str:
    """The assigned contribution as model-visible JSON (no program metadata)."""

    def trim_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "path": ref.get("path"),
                "start_line": ref.get("start_line"),
                "end_line": ref.get("end_line"),
            }
            for ref in refs or []
        ]

    visible = {
        "record_id": contribution["record_id"],
        "identifiers": [
            {"value": item["value"]}
            for item in contribution.get("identifiers") or []
        ],
        "contribution_type": contribution["contribution_type"],
        "contribution_summary": contribution["contribution_summary"],
        "contribution_evidence": trim_refs(contribution.get("contribution_evidence")),
        "paper_boundness": {
            "status": (contribution.get("paper_boundness") or {}).get("status"),
            "evidence": trim_refs((contribution.get("paper_boundness") or {}).get("evidence")),
        },
    }
    return json.dumps(visible, ensure_ascii=False, indent=2)


class _QuantityStage:
    def __init__(
        self,
        workspace: Path,
        run_id: str,
        arxiv_id: str,
        *,
        config: HvsContributionMethodConfig,
        transport: Transport,
        api_key: str,
        base_url: str,
        sleep,
        progress=None,
        transport_factory: Callable[[], Transport] | None = None,
        quantity_concurrency: int = 1,
        record_ids: set[str] | None = None,
        run_dir: Path,
    ) -> None:
        self.workspace = workspace
        self.run_id = run_id
        self.arxiv_id = arxiv_id
        self.config = config
        self.transport = transport
        self.api_key = api_key
        self.base_url = base_url
        self.sleep = sleep
        self.progress = progress
        self.transport_factory = transport_factory
        self.quantity_concurrency = max(1, int(quantity_concurrency))
        self.record_ids = frozenset(record_ids) if record_ids is not None else None
        self.run_dir = assert_contribution_run_dir(workspace, run_id, run_dir)
        self.paper_dir = self.run_dir / "papers" / arxiv_id
        self.objects_dir = self.paper_dir / "object_quantities"

    def execute(self) -> dict[str, Any]:
        roster = json.loads(
            (self.paper_dir / "contribution_roster_final.json").read_text(encoding="utf-8")
        )
        if roster["status"] != "roster_complete":
            return {
                "status": NO_TRUSTED_ROSTER,
                "paper": {"arxiv_id": self.arxiv_id},
                "objects": {},
            }
        prepared = json.loads(
            (self.run_dir / "prepared_inputs" / f"{self.arxiv_id}.json").read_text(
                encoding="utf-8"
            )
        )
        self.prepared = prepared
        graph = resolve_frozen_tex_graph(
            self.workspace / "literature" / self.arxiv_id / "arxiv_source",
            prepared["manuscript"],
        )
        tex_paths = list(graph.included)
        self.tex_texts = {name: graph.texts[name] for name in tex_paths}
        self.tex_sha256 = {name: graph.files[name].sha256 for name in tex_paths}
        self.tex_line_counts = {name: graph.files[name].line_count for name in tex_paths}

        ecsv_selected = prepared.get("ecsv", {}).get("selected") or []
        ecsv_paths = [item["ecsv_path"] for item in ecsv_selected]
        self.ecsv_structures = {}
        self.ecsv_texts = {}
        paper_literature_dir = self.workspace / "literature" / self.arxiv_id
        for item in ecsv_selected:
            path = resolve_paper_ecsv_path(paper_literature_dir, item["ecsv_path"])
            text = path.read_text(encoding="utf-8")
            structure = parse_ecsv_structure(path)
            if structure.sha256 != item["sha256"]:
                raise ValueError(
                    f"context_mutation: {item['ecsv_path']} changed after preparation"
                )
            self.ecsv_structures[item["ecsv_path"]] = structure
            self.ecsv_texts[item["ecsv_path"]] = text
        self.ecsv_blocks = [
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
        self.schema = build_quantity_submission_schema(tex_paths, ecsv_paths)
        self.schema_hash = _sha256_text(
            json.dumps(self.schema, ensure_ascii=False, sort_keys=True)
        )
        self.manuscript_view = prepared["manuscript"]["view"]
        self.rule_profile_hash = rule_profile_sha256(
            self.workspace, CONTRIBUTION_RULE_PROFILE
        )

        contributions = [
            contribution
            for contribution in roster["object_contributions"]
            if self.record_ids is None
            or contribution["record_id"] in self.record_ids
        ]
        results: dict[str, str] = {}
        if self.quantity_concurrency == 1 or len(contributions) <= 1:
            for contribution in contributions:
                results[contribution["record_id"]] = self.run_object(contribution)
        else:
            from concurrent.futures import ThreadPoolExecutor

            workers = min(self.quantity_concurrency, len(contributions))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    contribution["record_id"]: pool.submit(
                        self.run_object, contribution
                    )
                    for contribution in contributions
                }
                for contribution in contributions:
                    record_id = contribution["record_id"]
                    results[record_id] = futures[record_id].result()
        status = "complete"
        if any(value != QUANTITY_EXTRACTION_COMPLETE for value in results.values()):
            status = "complete_with_failures"
        if roster["object_contributions"] and all(
            value != QUANTITY_EXTRACTION_COMPLETE for value in results.values()
        ):
            status = "all_objects_failed"
        return {"status": status, "paper": {"arxiv_id": self.arxiv_id}, "objects": results}

    def run_object(self, contribution: dict[str, Any]) -> str:
        record_id = contribution["record_id"]
        transport = (
            self.transport_factory()
            if self.transport_factory is not None
            else self.transport
        )
        mode = str(self.config.quantity_model.structured_output_mode)
        if mode != "tool_submission":
            raise ValueError(
                "json_object mode is scoped to the roster extractor; the "
                "quantity stage supports only tool_submission"
            )
        prompts = build_quantity_prompts(
            self.workspace,
            manuscript_view=self.manuscript_view,
            ecsv_blocks=self.ecsv_blocks,
            assigned_contribution_json=model_visible_contribution(contribution),
        )
        provenance = {
            "model": self.config.quantity_model.model,
            "provider": self.config.quantity_model.provider,
            "structured_output_mode": self.config.quantity_model.structured_output_mode,
            "temperature": self.config.quantity_model.temperature,
            "submission_function": SUBMIT_OBJECT_QUANTITIES,
            "rule_profile": CONTRIBUTION_RULE_PROFILE,
            "rule_profile_sha256": self.rule_profile_hash,
            "system_prompt_sha256": prompts["system_sha256"],
            "user_prompt_sha256": prompts["user_sha256"],
            "submission_schema_sha256": self.schema_hash,
            "request_policy": self.config.quantity_request_policy.model_dump(
                mode="json", by_alias=True
            ),
        }
        estimate = estimate_tokens(prompts["system"] + prompts["user"])
        budget = self.config.quantity_context_budget.input_budget()
        if estimate > budget:
            return self.write_artifact(
                contribution,
                status=QUANTITY_EXTRACTION_FAILED,
                quantities=[],
                failure={
                    "code": "input_too_large",
                    "detail": (
                        f"object request is {estimate} estimated tokens, over "
                        f"the quantity input budget {budget}; no API request was made"
                    ),
                    "attempts": [],
                },
                provenance=provenance,
            )
        messages = [
            {"role": "system", "content": prompts["system"]},
            {"role": "user", "content": prompts["user"]},
        ]
        kwargs = _route_kwargs(
            self.config.quantity_model,
            tool_name=SUBMIT_OBJECT_QUANTITIES,
            schema=self.schema,
            api_key=self.api_key,
            base_url=self.base_url,
            seed=None,
            max_tokens=self.config.quantity_context_budget.reserve_output,
        )
        request_policy = self.config.quantity_request_policy
        request_budget = ProviderRequestBudget(
            limit=request_policy.max_scientific_requests,
            transport_retry_limit=request_policy.max_transport_retries_per_call,
            total_limit=request_policy.max_total_physical_requests,
        )
        first = execute_with_format_correction(
            transport=transport,
            transport_kwargs=kwargs,
            tool_name=SUBMIT_OBJECT_QUANTITIES,
            schema=self.schema,
            messages=messages,
            sleep=self.sleep,
            mode=mode,
            request_budget=request_budget,
            input_token_budget=budget,
            max_correction_rounds=request_policy.max_format_correction_rounds,
            progress=self.progress,
            progress_context={
                "arxiv_id": self.arxiv_id,
                "stage": "contribution_quantity",
                "record_id": record_id,
            },
        )
        if first.status != OK:
            return self.write_artifact(
                contribution,
                status=QUANTITY_EXTRACTION_FAILED,
                quantities=[],
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
        assert first.payload is not None
        issues = validate_quantity_submission(first.payload, self.validation_context)
        payload = first.payload
        attempts = first.attempts
        usages = list(first.usages)
        repair_history = list(first.repair_history)
        if issues:
            second = execute_with_evidence_correction(
                transport=transport,
                transport_kwargs=kwargs,
                tool_name=SUBMIT_OBJECT_QUANTITIES,
                schema=self.schema,
                messages=messages,
                previous_payload=first.payload,
                issues=issues,
                validate_fn=self.validate,
                sleep=self.sleep,
                allowed_roots_fn=quantity_allowed_roots,
                mode=mode,
                request_budget=request_budget,
                input_token_budget=budget,
                progress=self.progress,
                progress_context={
                    "arxiv_id": self.arxiv_id,
                    "stage": "contribution_quantity",
                    "record_id": record_id,
                },
            )
            attempts = [*first.attempts, *second.attempts]
            usages.extend(second.usages)
            repair_history.extend(second.repair_history)
            if second.status != OK:
                return self.write_artifact(
                    contribution,
                    status=QUANTITY_EXTRACTION_FAILED,
                    quantities=[],
                    failure={
                        "code": (
                            second.status
                            if second.status != EVIDENCE_VALIDATION_FAILURE
                            else "evidence_validation_failure"
                        ),
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
            payload = second.payload
        hydrated = hydrate_quantity_submission(
            payload, self.validation_context, tex_sha256=self.tex_sha256
        )
        return self.write_artifact(
            contribution,
            status=QUANTITY_EXTRACTION_COMPLETE,
            quantities=hydrated["quantities"],
            failure=None,
            provenance=provenance,
            attempts=attempts,
            usages=usages,
            repair_history=repair_history,
        )

    def validate(self, payload: dict[str, Any]):
        return validate_quantity_submission(payload, self.validation_context)

    def write_artifact(
        self,
        contribution: dict[str, Any],
        *,
        status: str,
        quantities: list[dict[str, Any]],
        failure: dict[str, Any] | None,
        provenance: dict[str, Any] | None,
        attempts: list[dict[str, Any]] | None = None,
        usages: list[dict[str, Any]] | None = None,
        repair_history: list[dict[str, Any]] | None = None,
    ) -> str:
        artifact = {
            "schema": schema_ref("hvs_contribution_extraction.object_quantities"),
            "generated_at": _utc_now(),
            "paper": {"arxiv_id": self.arxiv_id},
            "run_id": self.run_id,
            "record_id": contribution["record_id"],
            "contribution_type": contribution["contribution_type"],
            "status": status,
            "quantities": quantities,
            "failure": failure,
            "provenance": provenance,
            "attempts": attempts or [],
            "usages": usages or [],
            "repair_history": repair_history or [],
        }
        _atomic_write_json(self.objects_dir / f"{contribution['record_id']}.json", artifact)
        return status


def run_quantity_stage(
    workspace: Path,
    run_id: str,
    arxiv_id: str,
    *,
    config: HvsContributionMethodConfig,
    transport: Transport,
    api_key: str = "",
    base_url: str = "",
    sleep=time.sleep,
    progress=None,
    transport_factory: Callable[[], Transport] | None = None,
    quantity_concurrency: int = 1,
    record_ids: set[str] | None = None,
    run_dir: Path | None = None,
) -> dict[str, Any]:
    """Run per-object quantity extraction inside the caller-owned run."""

    config.assert_frozen()
    stage = _QuantityStage(
        workspace,
        run_id,
        arxiv_id,
        config=config,
        transport=transport,
        api_key=api_key,
        base_url=base_url,
        sleep=sleep,
        progress=progress,
        transport_factory=transport_factory,
        quantity_concurrency=quantity_concurrency,
        record_ids=record_ids,
        run_dir=run_dir,
    )
    return stage.execute()


def _quantity_failure_is_retryable(artifact: dict[str, Any]) -> bool:
    failure = artifact.get("failure") or {}
    if failure.get("code") == "transport_failure":
        return True
    transport_error = failure.get("transport_error") or {}
    return bool(
        transport_error.get("automatic_retryable")
        or transport_error.get("manual_retry_eligible")
    )


def retryable_quantity_record_ids(paper_dir: Path) -> list[str]:
    """Return retryable quantity objects in the frozen roster order."""

    paper_dir = Path(paper_dir)
    roster = json.loads(
        (paper_dir / "contribution_roster_final.json").read_text(encoding="utf-8")
    )
    retryable: list[str] = []
    for contribution in roster.get("object_contributions") or []:
        record_id = str(contribution["record_id"])
        path = paper_dir / "object_quantities" / f"{record_id}.json"
        if not path.is_file():
            continue
        artifact = json.loads(path.read_text(encoding="utf-8"))
        if _quantity_failure_is_retryable(artifact):
            retryable.append(record_id)
    return retryable


def _archive_quantity_failures(
    paper_dir: Path, record_ids: list[str]
) -> None:
    """Preserve each replaced failed object as an append-only attempt."""

    paper_dir = Path(paper_dir)
    for record_id in record_ids:
        source = paper_dir / "object_quantities" / f"{record_id}.json"
        attempts_dir = paper_dir / "object_quantity_attempts" / record_id
        attempts_dir.mkdir(parents=True, exist_ok=True)
        index = len(list(attempts_dir.glob("attempt-*.json"))) + 1
        target = attempts_dir / f"attempt-{index}.json"
        with target.open("x", encoding="utf-8") as stream:
            stream.write(source.read_text(encoding="utf-8"))


def resume_quantity_stage(
    workspace: Path,
    run_id: str,
    arxiv_id: str,
    *,
    config: HvsContributionMethodConfig,
    transport: Transport,
    api_key: str = "",
    base_url: str = "",
    sleep=time.sleep,
    progress=None,
    transport_factory: Callable[[], Transport] | None = None,
    quantity_concurrency: int = 1,
    run_dir: Path,
) -> dict[str, Any]:
    """Retry only network-failed quantity objects in one active benchmark attempt."""

    paper_dir = Path(run_dir) / "papers" / arxiv_id
    record_ids = retryable_quantity_record_ids(paper_dir)
    if not record_ids:
        return {
            "status": "nothing_to_resume",
            "paper": {"arxiv_id": arxiv_id},
            "objects": {},
            "resumed_record_ids": [],
        }
    _archive_quantity_failures(paper_dir, record_ids)
    result = run_quantity_stage(
        workspace,
        run_id,
        arxiv_id,
        config=config,
        transport=transport,
        api_key=api_key,
        base_url=base_url,
        sleep=sleep,
        progress=progress,
        transport_factory=transport_factory,
        quantity_concurrency=quantity_concurrency,
        record_ids=set(record_ids),
        run_dir=run_dir,
    )
    result["resumed_record_ids"] = record_ids
    return result
