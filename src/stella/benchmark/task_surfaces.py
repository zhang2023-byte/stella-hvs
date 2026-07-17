"""Stable generation-task surfaces for benchmark HVS extraction."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stella.lit.schema_templates import empty_candidate_enrichment

FULL = "full"
CORE_PROV = "core_prov"
TASK_SURFACE_IDS = (FULL, CORE_PROV)
ENRICHMENT_FIELDS = tuple(empty_candidate_enrichment())


@dataclass(frozen=True)
class TaskSurface:
    id: str
    candidate_fields: tuple[str, ...]
    instruction: str
    schema_reference: str


_SURFACES = {
    FULL: TaskSurface(
        id=FULL,
        candidate_fields=(
            "identifiers",
            "inclusion_assessment",
            "candidate_origin",
            "core",
            *ENRICHMENT_FIELDS,
        ),
        instruction=(
            "Generate the complete current CandidateRecord, including every applicable "
            "core and enrichment group, with paper-grounded source evidence and method lineage."
        ),
        schema_reference="skills/hvs-candidates-extraction/references/schema.md",
    ),
    CORE_PROV: TaskSurface(
        id=CORE_PROV,
        candidate_fields=(
            "identifiers",
            "inclusion_assessment",
            "candidate_origin",
            "core",
        ),
        instruction=(
            "Generate only candidate identity, inclusion assessment, candidate origin, the "
            "19 core quantities, source evidence, candidate_groups_considered, and the minimum "
            "method_chain/method_refs lineage needed by populated core quantities. Do not "
            "generate photometry, spectroscopy, stellar parameters, abundances, quality flags, "
            "orbit, astrophysical-origin metrics, or extra quantities; code supplies their "
            "canonical empty defaults."
        ),
        schema_reference=(
            "skills/hvs-candidates-extraction/references/schema-core-provenance.md"
        ),
    ),
}


def get_task_surface(task_surface: str) -> TaskSurface:
    try:
        return _SURFACES[task_surface]
    except KeyError as exc:
        raise ValueError(
            f"unknown task surface {task_surface!r}; expected one of {TASK_SURFACE_IDS}"
        ) from exc


def task_surface_schema_view(workspace: Path, task_surface: str) -> str:
    surface = get_task_surface(task_surface)
    return (workspace / surface.schema_reference).read_text(encoding="utf-8")


def task_surface_sha256(workspace: Path, task_surface: str) -> str:
    """Hash field scope, prompt instruction, and generated schema view."""

    surface = get_task_surface(task_surface)
    payload = {
        "id": surface.id,
        "candidate_fields": list(surface.candidate_fields),
        "instruction": surface.instruction,
        "schema_view": task_surface_schema_view(workspace, task_surface),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def hydrate_surface_document(document: dict[str, Any], task_surface: str) -> dict[str, Any]:
    """Hydrate omitted CORE enrichment fields without hiding model output."""

    get_task_surface(task_surface)
    if task_surface == FULL:
        return document
    defaults = empty_candidate_enrichment()
    for candidate in document.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        for field, empty_value in defaults.items():
            candidate.setdefault(field, json.loads(json.dumps(empty_value)))
    return document


def core_projection(document: dict[str, Any]) -> dict[str, Any]:
    """Return the scored CORE view of a FULL document.

    The projection is a deep copy in which every candidate's enrichment
    groups are replaced by the code-owned canonical empty defaults. Core
    identity, inclusion assessment, candidate origin, the scored core
    quantities, source evidence, and method lineage are preserved exactly.
    Validating the projection under the CORE_PROV surface contract is what
    makes non-scored enrichment findings non-blocking for L1/L2 delivery
    while the FULL document keeps its own strict validation for the
    enrichment product.
    """

    projection = copy.deepcopy(document)
    if not isinstance(projection, dict):
        return projection
    candidates = projection.get("candidates")
    if not isinstance(candidates, list):
        return projection
    defaults = empty_candidate_enrichment()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for field, empty_value in defaults.items():
            candidate[field] = copy.deepcopy(empty_value)
    return projection


def validate_surface_document(
    document: Any, task_surface: str
) -> list[str]:
    """Return surface violations; FULL intentionally adds no extra checks."""

    get_task_surface(task_surface)
    if task_surface == FULL:
        return []
    if not isinstance(document, dict):
        return ["$: task-surface document must be an object"]
    defaults = empty_candidate_enrichment()
    errors: list[str] = []
    candidates = document.get("candidates")
    if not isinstance(candidates, list):
        return ["$.candidates: task-surface candidates must be a list"]
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            continue
        for field, expected in defaults.items():
            if candidate.get(field) != expected:
                errors.append(
                    f"$.candidates[{index}].{field}: CORE+PROV requires the "
                    "code-generated empty default"
                )
    return errors


def validate_generated_candidate(candidate: Any, task_surface: str) -> list[str]:
    """Reject model-supplied CORE enrichment while allowing omitted fields."""

    get_task_surface(task_surface)
    if task_surface == FULL or not isinstance(candidate, dict):
        return []
    defaults = empty_candidate_enrichment()
    errors: list[str] = []
    for field, expected in defaults.items():
        if field in candidate and candidate[field] != expected:
            errors.append(
                f"candidate.{field}: CORE+PROV may not generate non-empty enrichment"
            )
    return errors


def surface_binding(workspace: Path, task_surface: str) -> dict[str, str]:
    return {
        "task_surface": get_task_surface(task_surface).id,
        "task_surface_sha256": task_surface_sha256(workspace, task_surface),
    }
