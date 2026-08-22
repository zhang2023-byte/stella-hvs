"""Confirm one paper's contribution roster with one frozen model route.

The contribution pipeline never writes into a benchmark campaign: an
explicit ``run_dir`` is required, so every artifact lands in the caller's
non-formal contribution run root. A failed roster produces no trusted
contributions.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stella.hvs_extraction.bounded_call import (
    EVIDENCE_VALIDATION_FAILURE,
    OK,
    BoundedSubmission,
    ProviderRequestBudget,
    Transport,
    execute_with_evidence_correction,
    execute_with_format_correction,
)
from stella.hvs_extraction.prepare import estimate_tokens
from stella.hvs_extraction.range_expand import expand_range_notation
from stella.hvs_extraction.roster_stage import (
    manuscript_gaia_release,
    recognize_identifier,
)
from stella.hvs_contribution_extraction.method_config import (
    CONTRIBUTION_RULE_PROFILE,
    HvsContributionMethodConfig,
    HvsModelRoute,
)
from stella.hvs_contribution_extraction.roster_prompts import (
    build_contribution_roster_prompts,
)
from stella.hvs_contribution_extraction.roster_validate import (
    hydrate_contribution_source_refs,
    validate_contribution_roster_submission,
)
from stella.hvs_contribution_extraction.submission_schema import (
    SUBMIT_CONTRIBUTION_ROSTER,
    build_contribution_roster_submission_schema,
)
from stella.hvs_extraction.cleaning import strip_tex_comments
from stella.hvs_extraction.tex_graph import resolve_frozen_tex_graph
from stella.benchmark.structured_output import (
    apply_structured_output_request,
    resolve_structured_output_contract,
)
from stella.lit.extraction_rules import rule_profile_sha256
from stella.schema_registry import schema_ref

ROSTER_COMPLETE = "roster_complete"
ROSTER_FAILED = "roster_failed"


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


def _route_kwargs(
    route: HvsModelRoute,
    *,
    tool_name: str,
    schema: dict[str, Any],
    api_key: str,
    base_url: str,
    seed: int | None,
    max_tokens: int | None,
) -> dict[str, Any]:
    contract = resolve_structured_output_contract(
        model=str(route.model),
        provider={"only": [str(route.provider)]},
        mode=str(route.structured_output_mode),
    )
    base: dict[str, Any] = {}
    if route.top_p is not None:
        base["top_p"] = route.top_p
    if seed is not None:
        base["seed"] = seed
    extra_body = apply_structured_output_request(
        base, contract=contract, schema=schema, tool_name=tool_name
    )
    for key, value in (route.request_overrides or {}).items():
        if key in extra_body:
            raise ValueError(
                f"route request override conflicts with contract field: {key}"
            )
        extra_body[key] = value
    return {
        "api_key": api_key,
        "base_url": base_url,
        "model": route.model,
        "temperature": route.temperature,
        "max_tokens": max_tokens,
        "timeout_seconds": 1800 if route.stream else 600,
        "attempts": 1,
        "extra_body": extra_body,
        "stream": bool(route.stream),
    }


def _slot_failure(reason: BoundedSubmission, status: str) -> dict[str, Any]:
    return {
        "status": status,
        "initial_errors": reason.initial_errors,
        "correction_errors": reason.correction_errors,
        "attempts": reason.attempts,
        "transport_error": reason.transport_error,
        "detail": reason.other_error,
        "repair_history": reason.repair_history,
    }


class _ContributionRosterStage:
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
        run_dir: Path,
    ) -> None:
        if run_dir is None:
            raise ValueError("run_dir is required: the contribution pipeline never writes into a benchmark campaign")
        self.workspace = workspace
        self.run_id = run_id
        self.arxiv_id = arxiv_id
        self.config = config
        self.transport = transport
        self.api_key = api_key
        self.base_url = base_url
        self.sleep = sleep
        self.progress = progress
        self.run_dir = Path(run_dir)
        self.paper_dir = self.run_dir / "papers" / self.arxiv_id

    def load_prepared(self) -> dict[str, Any]:
        path = self.run_dir / "prepared_inputs" / f"{self.arxiv_id}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def failure_artifact(
        self,
        code: str,
        detail: str,
        **extra: Any,
    ) -> dict[str, Any]:
        artifact = {
            "schema": schema_ref("hvs_contribution_extraction.roster_final"),
            "generated_at": _utc_now(),
            "paper": {"arxiv_id": self.arxiv_id},
            "run_id": self.run_id,
            "status": ROSTER_FAILED,
            "roster_status": None,
            "failure": {"code": code, "detail": detail, **extra},
            "object_contributions": [],
            "reviewed_exclusions": [],
        }
        _atomic_write_json(self.paper_dir / "contribution_roster_final.json", artifact)
        return artifact

    def verify_immutable_context(self, prepared: dict[str, Any]) -> dict[str, Any]:
        """Re-resolve the manuscript graph and fail on any mutation."""

        paper_dir = self.workspace / "literature" / self.arxiv_id
        return resolve_frozen_tex_graph(
            paper_dir / "arxiv_source", prepared["manuscript"]
        )

    def request_oversize(self, prompts: dict[str, str], role: str) -> dict[str, Any] | None:
        estimate = estimate_tokens(prompts["system"] + prompts["user"])
        budget = self.config.roster_context_budget.input_budget()
        if estimate <= budget:
            return None
        return {
            "status": "input_too_large",
            "detail": (
                f"{role} request is {estimate} estimated tokens, over the "
                f"roster input budget {budget}; no API request was made"
            ),
            "initial_errors": [],
            "correction_errors": [],
            "attempts": [],
            "transport_error": None,
        }

    def run_extractor_slot(self, slot: int, seed: int | None) -> dict[str, Any]:
        route = self.config.roster_model
        mode = str(route.structured_output_mode)
        prompts = build_contribution_roster_prompts(
            self.workspace,
            self.manuscript_view,
            mode=mode,
            schema=self.schema if mode == "json_object" else None,
        )
        proposal: dict[str, Any] = {
            "schema": schema_ref("hvs_contribution_extraction.roster_proposal"),
            "generated_at": _utc_now(),
            "paper": {"arxiv_id": self.arxiv_id},
            "run_id": self.run_id,
            "slot": slot,
            "seed": seed,
            "provenance": self.provenance(
                self.config.roster_model, prompts, SUBMIT_CONTRIBUTION_ROSTER
            ),
        }
        oversize = self.request_oversize(prompts, f"extractor slot {slot}")
        if oversize is not None:
            proposal["status"] = "failed"
            proposal["submission"] = None
            proposal["failure"] = oversize
            return proposal
        messages = [
            {"role": "system", "content": prompts["system"]},
            {"role": "user", "content": prompts["user"]},
        ]
        kwargs = _route_kwargs(
            route,
            tool_name=SUBMIT_CONTRIBUTION_ROSTER,
            schema=self.schema,
            api_key=self.api_key,
            base_url=self.base_url,
            seed=seed,
            max_tokens=self.config.roster_context_budget.reserve_output,
        )
        request_policy = self.config.roster_request_policy
        request_budget = ProviderRequestBudget(
            limit=request_policy.max_scientific_requests,
            transport_retry_limit=request_policy.max_transport_retries_per_call,
            total_limit=request_policy.max_total_physical_requests,
        )
        first = execute_with_format_correction(
            transport=self.transport,
            transport_kwargs=kwargs,
            tool_name=SUBMIT_CONTRIBUTION_ROSTER,
            schema=self.schema,
            messages=messages,
            sleep=self.sleep,
            mode=mode,
            request_budget=request_budget,
            max_correction_rounds=request_policy.max_format_correction_rounds,
            input_token_budget=self.config.roster_context_budget.input_budget(),
            progress=self.progress,
            progress_context={
                "arxiv_id": self.arxiv_id,
                "stage": "contribution_roster",
                "slot": slot,
            },
        )
        if first.status != OK:
            proposal["status"] = "failed"
            proposal["submission"] = None
            proposal["failure"] = _slot_failure(first, first.status)
            proposal["attempts"] = first.attempts
            proposal["usages"] = list(first.usages)
            proposal["repair_history"] = list(first.repair_history)
            return proposal
        assert first.payload is not None
        issues = self.validate(first.payload)
        payload = first.payload
        attempts = first.attempts
        usages = list(first.usages)
        repair_history = list(first.repair_history)
        if issues:
            second = execute_with_evidence_correction(
                transport=self.transport,
                transport_kwargs=kwargs,
                tool_name=SUBMIT_CONTRIBUTION_ROSTER,
                schema=self.schema,
                messages=messages,
                previous_payload=first.payload,
                issues=issues,
                validate_fn=self.validate,
                sleep=self.sleep,
                mode=mode,
                request_budget=request_budget,
                input_token_budget=self.config.roster_context_budget.input_budget(),
                progress=self.progress,
                progress_context={
                    "arxiv_id": self.arxiv_id,
                    "stage": "contribution_roster",
                    "slot": slot,
                },
            )
            attempts = [*first.attempts, *second.attempts]
            usages.extend(second.usages)
            repair_history.extend(second.repair_history)
            if second.status != OK:
                proposal["status"] = "failed"
                proposal["submission"] = None
                proposal["failure"] = {
                    "status": second.status
                    if second.status != EVIDENCE_VALIDATION_FAILURE
                    else "evidence_validation_failure",
                    "initial_errors": second.initial_errors,
                    "correction_errors": second.correction_errors,
                    "unexpected_changes": second.unexpected_changes,
                    "attempts": attempts,
                    "transport_error": second.transport_error,
                    "repair_history": repair_history,
                }
                proposal["attempts"] = attempts
                proposal["usages"] = usages
                proposal["repair_history"] = repair_history
                return proposal
            payload = second.payload
        proposal["status"] = "valid"
        proposal["submission"] = hydrate_contribution_source_refs(
            payload,
            original_texts=self.original_texts,
            file_sha256=self.file_sha256,
        )
        proposal["failure"] = None
        proposal["attempts"] = attempts
        proposal["usages"] = usages
        proposal["repair_history"] = repair_history
        return proposal

    def validate(self, payload: dict[str, Any]):
        return validate_contribution_roster_submission(
            payload,
            file_line_counts=self.file_line_counts,
            original_texts=self.original_texts,
            cleaned_texts=self.cleaned_texts,
        )

    def provenance(
        self, route: HvsModelRoute, prompts: dict[str, str], tool_name: str
    ) -> dict[str, Any]:
        return {
            "model": route.model,
            "provider": route.provider,
            "structured_output_mode": route.structured_output_mode,
            "temperature": route.temperature,
            "top_p": route.top_p,
            "submission_function": tool_name,
            "rule_profile_sha256": self.rule_profile_hash,
            "system_prompt_sha256": prompts["system_sha256"],
            "user_prompt_sha256": prompts["user_sha256"],
            "submission_schema_sha256": self.schema_hash,
            "manuscript_view_sha256": self.prepared["manuscript"]["view_sha256"],
            "request_policy": self.config.roster_request_policy.model_dump(
                mode="json", by_alias=True
            ),
        }

    def execute(self) -> dict[str, Any]:
        self.prepared = self.load_prepared()
        if self.prepared["status"] != "prepared":
            return self.failure_artifact(
                "prepared_input_not_usable",
                f"prepared input status is {self.prepared['status']}",
            )
        try:
            graph = self.verify_immutable_context(self.prepared)
        except ValueError as exc:
            return self.failure_artifact("context_mutation", str(exc))

        self.manuscript_view = self.prepared["manuscript"]["view"]
        self.original_texts = {name: graph.texts[name] for name in graph.included}
        self.cleaned_texts = {
            name: strip_tex_comments(graph.texts[name]) for name in graph.included
        }
        self.file_line_counts = {
            name: graph.files[name].line_count for name in graph.included
        }
        self.file_sha256 = {name: graph.files[name].sha256 for name in graph.included}
        self.schema = build_contribution_roster_submission_schema(list(graph.included))
        self.schema_hash = _sha256_text(
            json.dumps(self.schema, ensure_ascii=False, sort_keys=True)
        )
        self.rule_profile_hash = rule_profile_sha256(
            self.workspace, CONTRIBUTION_RULE_PROFILE
        )

        proposals = [self.run_extractor_slot(0, None)]
        for proposal in proposals:
            _atomic_write_json(
                self.paper_dir / f"contribution_roster_proposal-slot-{proposal['slot']}.json",
                proposal,
            )

        valid = [item for item in proposals if item["status"] == "valid"]

        if not valid:
            return self.failure_artifact(
                "extractor_terminal_failure",
                "the contribution roster model reached a terminal failure",
                proposal_failures=[
                    {"slot": item["slot"], "failure": item["failure"]}
                    for item in proposals
                ],
            )
        final_payload = valid[0]["submission"]

        contributions, exclusions, roster_status = finalize_contribution_roster(
            final_payload,
            original_texts=self.original_texts,
            file_sha256=self.file_sha256,
        )
        artifact = {
            "schema": schema_ref("hvs_contribution_extraction.roster_final"),
            "generated_at": _utc_now(),
            "paper": {"arxiv_id": self.arxiv_id},
            "run_id": self.run_id,
            "status": ROSTER_COMPLETE,
            "roster_status": roster_status,
            "failure": None,
            "object_contributions": contributions,
            "reviewed_exclusions": exclusions,
            "proposals": {
                "slots": [
                    {"slot": item["slot"], "status": item["status"], "seed": item["seed"]}
                    for item in proposals
                ],
            },
            "provenance": {
                "extractor": proposals[0]["provenance"],
                "extractor_attempts": [
                    {"slot": item["slot"], "attempts": item.get("attempts") or []}
                    for item in proposals
                ],
                "extractor_usages": [
                    {"slot": item["slot"], "usages": item.get("usages") or []}
                    for item in proposals
                ],
                "extractor_repair_history": [
                    {"slot": item["slot"], "repair_history": item.get("repair_history") or []}
                    for item in proposals
                ],
            },
        }
        _atomic_write_json(self.paper_dir / "contribution_roster_final.json", artifact)
        return artifact


def finalize_contribution_roster(
    payload: dict[str, Any],
    *,
    original_texts: dict[str, str],
    file_sha256: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    """Program-owned mechanics: record ids, display names, Gaia, range expansion.

    ``record_id`` and ``display_name`` are generated here after validation;
    they are never model-authored and never matching or scoring keys.
    """

    bare_release = manuscript_gaia_release(original_texts)
    hydrated = hydrate_contribution_source_refs(
        payload, original_texts=original_texts, file_sha256=file_sha256
    )
    contributions: list[dict[str, Any]] = []

    def append_contribution(
        identifiers: list[dict[str, Any]],
        contribution: dict[str, Any],
    ) -> None:
        display_name = None
        recognized = []
        for item in identifiers:
            recognition = recognize_identifier(item["value"], bare_release)
            if display_name is None and recognition["kind"] != "gaia":
                display_name = item["value"]
            recognized.append({**item, "recognition": recognition})
        if display_name is None and recognized:
            display_name = recognized[0]["value"]
        contributions.append(
            {
                "record_id": f"obj-{len(contributions) + 1:03d}",
                "display_name": display_name,
                "identifiers": recognized,
                "contribution_type": contribution["contribution_type"],
                "contribution_note": contribution["contribution_note"],
                "contribution_evidence": contribution["contribution_evidence"],
                "paper_boundness": contribution["paper_boundness"],
            }
        )

    for contribution in hydrated["object_contributions"]:
        append_contribution(contribution["identifiers"], contribution)

    existing = {
        identifier["value"]
        for contribution in contributions
        for identifier in contribution["identifiers"]
    }
    reviewed_exclusions = list(hydrated["reviewed_exclusions"])
    for group in hydrated.get("range_groups") or []:
        expansion = expand_range_notation(group["range_notation"])
        if expansion.error:
            continue  # invalid rosters never reach finalization
        for value in expansion.identifiers:
            if value in existing:
                continue
            existing.add(value)
            append_contribution(
                [
                    {
                        "value": value,
                        "source_refs": group["source_refs"],
                        "range_expanded": True,
                        "range_notation": group["range_notation"],
                    }
                ],
                group,
            )
        if expansion.remainder:
            reviewed_exclusions.append(
                {
                    "note": (
                        f"{group['range_notation']}: {expansion.remainder} are not "
                        "individually identifiable from the manuscript range notation."
                    ),
                    "source_refs": group["source_refs"],
                }
            )
    roster_status = "contributions_found" if contributions else "no_contributions"
    return contributions, reviewed_exclusions, roster_status


def run_contribution_roster_stage(
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
    run_dir: Path | None = None,
) -> dict[str, Any]:
    """Run the contribution roster stage for one paper inside a non-formal run."""

    config.assert_frozen()
    stage = _ContributionRosterStage(
        workspace,
        run_id,
        arxiv_id,
        config=config,
        transport=transport,
        api_key=api_key,
        base_url=base_url,
        sleep=sleep,
        progress=progress,
        run_dir=run_dir,
    )
    return stage.execute()
