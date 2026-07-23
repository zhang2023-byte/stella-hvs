"""confirm_hvs_candidate_roster stage orchestration (D008-D024, D047, D052).

Ensemble variant: three blind low-temperature extractor proposals from one
frozen route, adjudicated by a distinct deterministic reviewer family that
submits the final roster. Single variant: one extractor slot, frozen after
local validation without adjudication. Only a locally validated final roster
moves downstream; invalid proposals never reach the adjudicator and proposals
are never mechanically merged.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from stella.benchmark.scratch.bounded_call import (
    EVIDENCE_VALIDATION_FAILURE,
    OK,
    BoundedSubmission,
    Transport,
    execute_with_evidence_correction,
    execute_with_format_correction,
)
from stella.benchmark.scratch.prepare import RUNS_RELATIVE_DIR, estimate_tokens
from stella.benchmark.scratch.roster_prompts import (
    PROPOSAL_LABELS,
    build_adjudicator_prompts,
    build_extractor_prompts,
)
from stella.benchmark.scratch.roster_validate import (
    hydrate_source_refs,
    validate_roster_submission,
)
from stella.benchmark.scratch.cleaning import strip_tex_comments
from stella.benchmark.scratch.method_config import ScratchMethodConfig, ScratchModelRoute
from stella.benchmark.scratch.submission_schema import (
    SUBMIT_CANDIDATE_ROSTER,
    SUBMIT_FINAL_CANDIDATE_ROSTER,
    build_roster_submission_schema,
)
from stella.benchmark.scratch.tex_graph import resolve_tex_graph
from stella.benchmark.structured_output import (
    apply_structured_output_request,
    resolve_structured_output_contract,
)
from stella.dyn.dynamics import parse_gaia_source_id
from stella.lit.extraction_rules import rule_profile_sha256
from stella.schema_registry import schema_ref

VARIANT_ENSEMBLE = "ensemble"
VARIANT_SINGLE = "single"
ROSTER_COMPLETE = "roster_complete"
ROSTER_FAILED = "roster_failed"

ENSEMBLE_SLOTS = 3
ENSEMBLE_MINIMUM_VALID = 2


def _utc_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


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
    route: ScratchModelRoute,
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
    return {
        "api_key": api_key,
        "base_url": base_url,
        "model": route.model,
        "temperature": route.temperature,
        "max_tokens": max_tokens,
        "timeout_seconds": 600,
        "attempts": 1,
        "extra_body": extra_body,
    }


def _slot_failure(reason: BoundedSubmission, status: str) -> dict[str, Any]:
    return {
        "status": status,
        "initial_errors": reason.initial_errors,
        "correction_errors": reason.correction_errors,
        "attempts": reason.attempts,
        "transport_error": reason.transport_error,
    }


class _RosterStage:
    def __init__(
        self,
        workspace: Path,
        run_id: str,
        arxiv_id: str,
        *,
        config: ScratchMethodConfig,
        variant: str,
        transport: Transport,
        api_key: str,
        base_url: str,
        sleep,
    ) -> None:
        self.workspace = workspace
        self.run_id = run_id
        self.arxiv_id = arxiv_id
        self.config = config
        self.variant = variant
        self.transport = transport
        self.api_key = api_key
        self.base_url = base_url
        self.sleep = sleep
        self.run_dir = workspace / RUNS_RELATIVE_DIR / run_id
        self.paper_dir = self.run_dir / "papers" / self.arxiv_id

    def load_prepared(self) -> dict[str, Any]:
        path = self.run_dir / "prepared_inputs" / f"{self.arxiv_id}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def failure_artifact(self, code: str, detail: str, **extra: Any) -> dict[str, Any]:
        artifact = {
            "schema": schema_ref("benchmark.hvs_extraction_scratch.roster_final"),
            "generated_at": _utc_now(),
            "paper": {"arxiv_id": self.arxiv_id},
            "run_id": self.run_id,
            "variant": self.variant,
            "status": ROSTER_FAILED,
            "roster_status": None,
            "failure": {"code": code, "detail": detail, **extra},
            "candidates": [],
            "reviewed_exclusions": [],
        }
        _atomic_write_json(self.paper_dir / "roster_final.json", artifact)
        return artifact

    def verify_immutable_context(self, prepared: dict[str, Any]) -> dict[str, Any]:
        """Re-resolve the manuscript graph and fail on any mutation (D049)."""

        paper_dir = self.workspace / "literature" / self.arxiv_id
        graph = resolve_tex_graph(paper_dir / "arxiv_source")
        manifest_files = prepared["manuscript"]["files"]
        for name in prepared["manuscript"]["included"]:
            recorded = manifest_files.get(name)
            current = graph.files.get(name)
            if recorded is None or current is None or recorded["sha256"] != current.sha256:
                raise ValueError(f"context_mutation: {name} changed after preparation")
        return graph

    def request_oversize(self, prompts: dict[str, str], role: str) -> dict[str, Any] | None:
        """Final exact per-request size check (D008, D053): stop, never truncate."""

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
        prompts = build_extractor_prompts(self.workspace, self.manuscript_view)
        proposal: dict[str, Any] = {
            "schema": schema_ref("benchmark.hvs_extraction_scratch.roster_proposal"),
            "generated_at": _utc_now(),
            "paper": {"arxiv_id": self.arxiv_id},
            "run_id": self.run_id,
            "variant": self.variant,
            "slot": slot,
            "seed": seed,
            "provenance": self.provenance(
                self.config.roster_extractor, prompts, SUBMIT_CANDIDATE_ROSTER
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
            self.config.roster_extractor,
            tool_name=SUBMIT_CANDIDATE_ROSTER,
            schema=self.schema,
            api_key=self.api_key,
            base_url=self.base_url,
            seed=seed,
            max_tokens=self.config.roster_context_budget.reserve_output,
        )
        first = execute_with_format_correction(
            transport=self.transport,
            transport_kwargs=kwargs,
            tool_name=SUBMIT_CANDIDATE_ROSTER,
            schema=self.schema,
            messages=messages,
            sleep=self.sleep,
        )
        if first.status != OK:
            proposal["status"] = "failed"
            proposal["submission"] = None
            proposal["failure"] = _slot_failure(first, first.status)
            return proposal
        assert first.payload is not None
        issues = validate_roster_submission(
            first.payload,
            file_line_counts=self.file_line_counts,
            original_texts=self.original_texts,
            cleaned_texts=self.cleaned_texts,
        )
        payload = first.payload
        attempts = first.attempts
        if issues:
            second = execute_with_evidence_correction(
                transport=self.transport,
                transport_kwargs=kwargs,
                tool_name=SUBMIT_CANDIDATE_ROSTER,
                schema=self.schema,
                messages=messages,
                previous_payload=first.payload,
                issues=issues,
                validate_fn=self.validate,
                sleep=self.sleep,
            )
            attempts = [*first.attempts, *second.attempts]
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
                }
                return proposal
            payload = second.payload
        proposal["status"] = "valid"
        proposal["submission"] = hydrate_source_refs(
            payload,
            original_texts=self.original_texts,
            file_sha256=self.file_sha256,
        )
        proposal["failure"] = None
        proposal["attempts"] = attempts
        return proposal

    def run_adjudicator(self, labeled: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
        prompts = build_adjudicator_prompts(
            self.workspace, self.manuscript_view, labeled
        )
        oversize = self.request_oversize(prompts, "adjudicator")
        if oversize is not None:
            return {"status": "input_too_large", "failure": oversize}
        messages = [
            {"role": "system", "content": prompts["system"]},
            {"role": "user", "content": prompts["user"]},
        ]
        kwargs = _route_kwargs(
            self.config.roster_adjudicator,
            tool_name=SUBMIT_FINAL_CANDIDATE_ROSTER,
            schema=self.schema,
            api_key=self.api_key,
            base_url=self.base_url,
            seed=None,
            max_tokens=self.config.roster_context_budget.reserve_output,
        )
        first = execute_with_format_correction(
            transport=self.transport,
            transport_kwargs=kwargs,
            tool_name=SUBMIT_FINAL_CANDIDATE_ROSTER,
            schema=self.schema,
            messages=messages,
            sleep=self.sleep,
        )
        if first.status != OK:
            return {"status": first.status, "failure": _slot_failure(first, first.status)}
        assert first.payload is not None
        issues = validate_roster_submission(
            first.payload,
            file_line_counts=self.file_line_counts,
            original_texts=self.original_texts,
            cleaned_texts=self.cleaned_texts,
        )
        payload = first.payload
        attempts = first.attempts
        if issues:
            second = execute_with_evidence_correction(
                transport=self.transport,
                transport_kwargs=kwargs,
                tool_name=SUBMIT_FINAL_CANDIDATE_ROSTER,
                schema=self.schema,
                messages=messages,
                previous_payload=first.payload,
                issues=issues,
                validate_fn=self.validate,
                sleep=self.sleep,
            )
            attempts = [*first.attempts, *second.attempts]
            if second.status != OK:
                return {
                    "status": second.status,
                    "failure": {
                        "status": second.status,
                        "initial_errors": second.initial_errors,
                        "correction_errors": second.correction_errors,
                        "unexpected_changes": second.unexpected_changes,
                        "attempts": attempts,
                        "transport_error": second.transport_error,
                    },
                }
            payload = second.payload
        return {
            "status": OK,
            "payload": payload,
            "attempts": attempts,
            "provenance": self.provenance(
                self.config.roster_adjudicator, prompts, SUBMIT_FINAL_CANDIDATE_ROSTER
            ),
        }

    def validate(self, payload: dict[str, Any]):
        return validate_roster_submission(
            payload,
            file_line_counts=self.file_line_counts,
            original_texts=self.original_texts,
            cleaned_texts=self.cleaned_texts,
        )

    def provenance(
        self, route: ScratchModelRoute, prompts: dict[str, str], tool_name: str
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
        self.schema = build_roster_submission_schema(list(graph.included))
        self.schema_hash = _sha256_text(
            json.dumps(self.schema, ensure_ascii=False, sort_keys=True)
        )
        self.rule_profile_hash = rule_profile_sha256(
            self.workspace, "hvs_roster_scratch"
        )

        slots = ENSEMBLE_SLOTS if self.variant == VARIANT_ENSEMBLE else 1
        seeds = (
            list(self.config.roster_extractor_seeds[:slots])
            if self.config.roster_extractor.seed_honored
            else [None] * slots
        )
        if slots > 1:
            with ThreadPoolExecutor(max_workers=slots) as pool:
                proposals = list(
                    pool.map(lambda item: self.run_extractor_slot(*item), enumerate(seeds))
                )
        else:
            proposals = [self.run_extractor_slot(0, seeds[0])]
        for proposal in proposals:
            _atomic_write_json(
                self.paper_dir / f"roster_proposal-slot-{proposal['slot']}.json",
                proposal,
            )

        valid = [item for item in proposals if item["status"] == "valid"]

        if self.variant == VARIANT_SINGLE:
            if not valid:
                return self.failure_artifact(
                    "extractor_terminal_failure",
                    "the single extractor slot reached a terminal failure",
                    slot_failures=[
                        {"slot": item["slot"], "failure": item["failure"]}
                        for item in proposals
                    ],
                )
            final_payload = _submission_payload(valid[0])
            adjudication = None
            degraded = False
            label_mapping: dict[str, int] | None = None
        else:
            if len(valid) < ENSEMBLE_MINIMUM_VALID:
                return self.failure_artifact(
                    "insufficient_valid_proposals",
                    f"only {len(valid)} of {slots} extractor proposals are locally valid",
                    slot_failures=[
                        {"slot": item["slot"], "failure": item["failure"]}
                        for item in proposals
                    ],
                )
            shuffle_seed = hashlib.sha256(
                (
                    f"{self.run_id}|{self.arxiv_id}|{self.variant}|"
                    + ",".join(str(item["slot"]) for item in valid)
                ).encode("utf-8")
            ).hexdigest()
            rng = random.Random(int(shuffle_seed[:16], 16))
            shuffled = list(valid)
            rng.shuffle(shuffled)
            labeled = [
                (PROPOSAL_LABELS[index], _submission_payload(item))
                for index, item in enumerate(shuffled)
            ]
            label_mapping = {
                label: item["slot"] for (label, _), item in zip(labeled, shuffled)
            }
            degraded = len(valid) < slots
            adjudication = self.run_adjudicator(labeled)
            if adjudication["status"] != OK:
                code = (
                    "input_too_large"
                    if adjudication["status"] == "input_too_large"
                    else "adjudicator_terminal_failure"
                )
                return self.failure_artifact(
                    code,
                    "the roster adjudicator reached a terminal failure"
                    if code != "input_too_large"
                    else adjudication["failure"]["detail"],
                    adjudicator_failure=adjudication.get("failure"),
                    label_mapping=label_mapping,
                )
            final_payload = adjudication["payload"]

        candidates, exclusions, roster_status = finalize_roster(
            final_payload,
            original_texts=self.original_texts,
            file_sha256=self.file_sha256,
        )
        artifact = {
            "schema": schema_ref("benchmark.hvs_extraction_scratch.roster_final"),
            "generated_at": _utc_now(),
            "paper": {"arxiv_id": self.arxiv_id},
            "run_id": self.run_id,
            "variant": self.variant,
            "degraded_ensemble": degraded,
            "status": ROSTER_COMPLETE,
            "roster_status": roster_status,
            "failure": None,
            "candidates": candidates,
            "reviewed_exclusions": exclusions,
            "proposals": {
                "slots": [
                    {"slot": item["slot"], "status": item["status"], "seed": item["seed"]}
                    for item in proposals
                ],
                "label_mapping": label_mapping,
            },
            "provenance": {
                "extractor": proposals[0]["provenance"] if proposals else None,
                "adjudicator": adjudication.get("provenance") if adjudication else None,
                "adjudicator_attempts": adjudication.get("attempts") if adjudication else None,
            },
        }
        _atomic_write_json(self.paper_dir / "roster_final.json", artifact)
        return artifact


def _submission_payload(proposal: dict[str, Any]) -> dict[str, Any]:
    """The model-submitted (hydrated) roster payload of one valid proposal."""

    submission = proposal["submission"]
    return {
        "candidates": submission["candidates"],
        "reviewed_exclusions": submission["reviewed_exclusions"],
    }


def finalize_roster(
    payload: dict[str, Any],
    *,
    original_texts: dict[str, str],
    file_sha256: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    """Program-owned mechanics (D010, D011): ids, status, Gaia, display name."""

    hydrated = hydrate_source_refs(
        payload, original_texts=original_texts, file_sha256=file_sha256
    )
    candidates: list[dict[str, Any]] = []
    for index, candidate in enumerate(hydrated["candidates"], 1):
        identifiers = []
        display_name = None
        for item in candidate["identifiers"]:
            gaia = parse_gaia_source_id(item["value"])
            recognition = (
                {"kind": "gaia", "release": gaia.release, "source_id": gaia.source_id}
                if gaia is not None
                else {"kind": "other"}
            )
            if display_name is None and gaia is None:
                display_name = item["value"]
            identifiers.append(
                {
                    "value": item["value"],
                    "source_refs": item["source_refs"],
                    "recognition": recognition,
                }
            )
        if display_name is None and identifiers:
            display_name = identifiers[0]["value"]
        candidates.append(
            {
                "record_id": f"candidate-{index:03d}",
                "display_name": display_name,
                "identifiers": identifiers,
                "qualification": candidate["qualification"],
            }
        )
    roster_status = "candidates_found" if candidates else "no_candidates"
    return candidates, hydrated["reviewed_exclusions"], roster_status


def run_roster_stage(
    workspace: Path,
    run_id: str,
    arxiv_id: str,
    *,
    config: ScratchMethodConfig,
    variant: str,
    transport: Transport,
    api_key: str = "",
    base_url: str = "",
    sleep=time.sleep,
) -> dict[str, Any]:
    """Run the roster stage for one paper and persist the roster artifacts."""

    if variant not in (VARIANT_ENSEMBLE, VARIANT_SINGLE):
        raise ValueError(f"unknown roster variant: {variant!r}")
    config.assert_frozen()
    stage = _RosterStage(
        workspace,
        run_id,
        arxiv_id,
        config=config,
        variant=variant,
        transport=transport,
        api_key=api_key,
        base_url=base_url,
        sleep=sleep,
    )
    return stage.execute()
