"""Contribution gold annotation form mechanics (pre-activation).

The form renders and validates the contribution annotation shape against
temporary synthetic directories, but formal saving is disabled until the
later expert session approves the contribution guideline version and binds
a benchmark campaign. Drafts are annotator-scoped work state only; no
mechanical migration from V6 gold exists or is permitted.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from stella.benchmark.hvs_contribution_gold import (
    HvsContributionGoldAnnotation,
    lint_contribution_annotation,
)
from pydantic import ValidationError

PRE_ACTIVATION_BANNER = (
    "PRE-ACTIVATION: formal contribution gold annotation is disabled. "
    "Saving a formal annotation requires the later expert-approved "
    "contribution guideline version and an explicit benchmark campaign "
    "binding. Drafts saved here are annotator work state only and are never "
    "a formal scoring input."
)


class ContributionGoldFormError(ValueError):
    """One structured contribution-form failure."""


def build_empty_contribution_payload(
    *, arxiv_id: str = "", annotator: str = ""
) -> dict[str, Any]:
    """The blank editor-shaped draft payload (not schema-valid until filled)."""

    return {
        "schema": {"name": "benchmark.hvs_contribution_annotation", "version": 1},
        "arxiv_id": arxiv_id,
        "annotator": annotator,
        "annotated_at": "",
        "guideline_version": "",
        "evidence_basis": "pdf",
        "status": "contributions_found",
        "contributions": [],
        "reviewed_exclusions": [],
        "notes": "",
    }


def validation_errors(error: ValidationError) -> list[dict[str, Any]]:
    return [
        {"loc": ".".join(str(part) for part in item["loc"]), "msg": item["msg"]}
        for item in error.errors()
    ]


def validate_contribution_payload(payload: dict[str, Any]) -> HvsContributionGoldAnnotation:
    """Validate a filled contribution annotation payload."""

    return HvsContributionGoldAnnotation.model_validate(payload)


def yaml_text_for_document(document: dict[str, Any]) -> str:
    return yaml.safe_dump(document, allow_unicode=True, sort_keys=False)


def draft_path(gold_dir: Path, arxiv_id: str, annotator: str) -> Path:
    return Path(gold_dir) / arxiv_id / f"draft_{annotator}.json"


def annotation_path(gold_dir: Path, arxiv_id: str, annotator: str) -> Path:
    return Path(gold_dir) / arxiv_id / f"annotation_{annotator}.yaml"


def save_draft(payload: dict[str, Any], gold_dir: Path) -> dict[str, Any]:
    """Persist one annotator-scoped draft (work state, never formal gold)."""

    arxiv_id = str(payload.get("arxiv_id") or "").strip()
    annotator = str(payload.get("annotator") or "").strip()
    if not arxiv_id or not annotator:
        raise ContributionGoldFormError("draft requires arxiv_id and annotator")
    path = draft_path(Path(gold_dir), arxiv_id, annotator)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return {"path": str(path), "status": "draft_saved"}


def load_draft(gold_dir: Path, arxiv_id: str, annotator: str) -> dict[str, Any]:
    path = draft_path(Path(gold_dir), arxiv_id, annotator)
    if not path.is_file():
        raise ContributionGoldFormError(f"no draft for {arxiv_id}/{annotator}")
    return json.loads(path.read_text(encoding="utf-8"))


def save_annotation(payload: dict[str, Any], gold_dir: Path) -> dict[str, Any]:
    """Formal saving is disabled before activation; fail closed."""

    raise ContributionGoldFormError(PRE_ACTIVATION_BANNER)


def draft_artifact_summary(gold_dir: Path, arxiv_id: str, annotator: str) -> dict[str, Any]:
    path = draft_path(Path(gold_dir), arxiv_id, annotator)
    return {
        "exists": path.is_file(),
        "path": str(path),
        "is_reservation_marker": False,
        "formal_input": False,
    }


def validate_and_lint(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate plus lint without writing anything (pre-activation safe)."""

    annotation = validate_contribution_payload(payload)
    return {
        "valid": True,
        "lint_warnings": lint_contribution_annotation(annotation),
        "banner": PRE_ACTIVATION_BANNER,
    }
