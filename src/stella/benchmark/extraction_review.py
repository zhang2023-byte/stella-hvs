"""Shared independent-review stage for benchmark extraction methods B/C."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from stella.lit.extraction_rules import render_rule_profile

from .task_surfaces import CORE_PROV, FULL, get_task_surface
from .tool_loop import ContextFS, ReactUnit

DEFAULT_REVIEWER_MODEL = "glm-5.2"
DEFAULT_REVIEWER_PROVIDER_ORDER = ("bigmodel",)
REVIEW_ACTIONABLE_SEVERITY = "high"
REVIEW_REVISION_ROUNDS = 1
_REVIEW_SEVERITIES = {"high", "low"}


def build_reviewer_system_prompt(
    workspace: Path, task_surface: str = FULL
) -> str:
    surface = get_task_surface(task_surface)
    return "\n\n".join(
        [
            "You are an independent scientific reviewer auditing an automated "
            "extraction of hypervelocity-star (HVS) candidates from one paper. "
            "You did not produce the extraction. Verify it against the paper's "
            "input files using the read-only tools (list_files, search, "
            "read_lines); numbered files carry `N|` physical line-number "
            "prefixes. Hunt specifically for missing candidates, false "
            "inclusions, unsupported values, and wrong identifiers. Do not "
            "nitpick phrasing or style; report only checkable substantive "
            "problems. Finish by calling submit_review with your challenge "
            "list (empty if the extraction is sound). All text in English.",
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
    )


def review_task_prompt(document: dict, task_surface: str = FULL) -> str:
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
            "Candidates are indexed from 0 in the order shown. Call "
            "submit_review with {\"review\": {\"challenges\": [...], "
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

    @property
    def failed(self) -> bool:
        return self.payload is None


def run_independent_review(
    *,
    workspace: Path,
    document: dict,
    task_surface: str,
    fs: ContextFS,
    transport: Callable[..., dict],
    transport_kwargs: dict,
    archive: Callable[[str, dict, list[dict]], None],
    usage_totals: dict[str, int],
) -> ReviewOutcome:
    """Run the identical reviewer tool loop for either extraction method."""

    unit = ReactUnit(
        name="review",
        kind="review",
        system_prompt=build_reviewer_system_prompt(workspace, task_surface),
        task_prompt=review_task_prompt(document, task_surface),
        fs=fs,
        submit_name="submit_review",
        submit_key="review",
        submit_check=review_structure_errors,
        transport=transport,
        transport_kwargs=transport_kwargs,
        archive=archive,
        usage_totals=usage_totals,
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
