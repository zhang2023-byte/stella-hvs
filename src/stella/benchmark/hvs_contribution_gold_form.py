"""Contribution gold migration form mechanics.

The original 50-paper migration uses temporary AI-assisted drafts followed by
paper-level expert approval. Only the approved YAML/JSON twin is written to the
external private gold store; known migration work artifacts are deleted after
that save succeeds.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from stella.benchmark.hvs_contribution_gold import (
    CONTRIBUTION_MIGRATION_PROTOCOL,
    HvsContributionGoldAnnotation,
    compact_contribution_annotation_document,
    contribution_gold_json_document,
    lint_contribution_annotation,
)
from stella.benchmark.gold import validate_annotator_handle
from stella.lit.arxiv_ids import validate_unversioned_arxiv_id
from pydantic import ValidationError

CONTRIBUTION_GOLD_NOTICE = (
    "AI-assisted contribution migration: the final save records paper-level "
    "expert approval. PDF locators are the scientific evidence; production "
    "extractor outputs, runs, and scorecards are forbidden gold inputs."
)


class ContributionGoldFormError(ValueError):
    """One structured contribution-form failure."""


def build_empty_contribution_payload(
    *,
    arxiv_id: str = "",
    annotator: str = "",
    guideline_version: str = "",
    annotated_at: str = "",
) -> dict[str, Any]:
    """The blank editor-shaped draft payload (not schema-valid until filled)."""

    return {
        "schema": {"name": "benchmark.hvs_contribution_annotation", "version": 1},
        "arxiv_id": arxiv_id,
        "annotator": annotator,
        "annotated_at": annotated_at or date.today().isoformat(),
        "guideline_version": guideline_version,
        "evidence_basis": "pdf",
        "annotation_process": {
            "protocol": CONTRIBUTION_MIGRATION_PROTOCOL,
            "preannotation_agent": "",
            "preannotation_model": "",
            "reconciliation_agent": "",
            "reconciliation_model": "",
            "expert_review_scope": "paper_level",
            "process_note": "",
        },
        "status": "contributions_found",
        "contributions": [],
        "reviewed_exclusions": [],
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


def _validated_identity(arxiv_id: str, annotator: str) -> tuple[str, str]:
    try:
        safe_arxiv_id = validate_unversioned_arxiv_id(arxiv_id)
        safe_annotator = validate_annotator_handle(annotator)
    except ValueError as exc:
        raise ContributionGoldFormError(str(exc)) from exc
    return safe_arxiv_id, safe_annotator


def _paper_dir(root: Path, arxiv_id: str) -> Path:
    resolved_root = Path(root).expanduser().resolve()
    target = (resolved_root / arxiv_id).resolve()
    try:
        target.relative_to(resolved_root)
    except ValueError as exc:
        raise ContributionGoldFormError("paper path escapes its artifact root") from exc
    return target


def draft_path(work_dir: Path, arxiv_id: str, annotator: str) -> Path:
    safe_arxiv_id, safe_annotator = _validated_identity(arxiv_id, annotator)
    return _paper_dir(work_dir, safe_arxiv_id) / f"draft_{safe_annotator}.json"


def annotation_paths(
    gold_dir: Path, arxiv_id: str, annotator: str
) -> tuple[Path, Path]:
    safe_arxiv_id, safe_annotator = _validated_identity(arxiv_id, annotator)
    paper_dir = _paper_dir(gold_dir, safe_arxiv_id)
    stem = f"annotation_{safe_annotator}"
    return paper_dir / f"{stem}.yaml", paper_dir / f"{stem}.json"


def save_draft(payload: dict[str, Any], work_dir: Path) -> dict[str, Any]:
    """Persist one annotator-scoped draft (work state, never formal gold)."""

    arxiv_id = str(payload.get("arxiv_id") or "").strip()
    annotator = str(payload.get("annotator") or "").strip()
    if not arxiv_id or not annotator:
        raise ContributionGoldFormError("draft requires arxiv_id and annotator")
    path = draft_path(Path(work_dir), arxiv_id, annotator)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return {"path": str(path), "status": "draft_saved"}


def load_draft(work_dir: Path, arxiv_id: str, annotator: str) -> dict[str, Any]:
    path = draft_path(Path(work_dir), arxiv_id, annotator)
    if not path.is_file():
        raise ContributionGoldFormError(f"no draft for {arxiv_id}/{annotator}")
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def cleanup_migration_artifacts(
    work_dir: Path, arxiv_id: str, annotator: str
) -> list[str]:
    """Delete only the known temporary files for one approved paper."""

    safe_arxiv_id, safe_annotator = _validated_identity(arxiv_id, annotator)
    paper_dir = _paper_dir(work_dir, safe_arxiv_id)
    paths = (
        paper_dir / "preannotation.json",
        paper_dir / "conflict_report.json",
        paper_dir / f"draft_{safe_annotator}.json",
    )
    deleted: list[str] = []
    for path in paths:
        if path.is_file():
            path.unlink()
            deleted.append(str(path))
    if paper_dir.is_dir() and not any(paper_dir.iterdir()):
        paper_dir.rmdir()
    return deleted


def save_expert_annotation(
    payload: dict[str, Any],
    gold_dir: Path,
    *,
    work_dir: Path | None = None,
    expected_arxiv_id: str = "",
    expected_annotator: str = "",
    expert_approved: bool = False,
) -> dict[str, Any]:
    """Validate and atomically write an expert-approved contribution twin."""

    if not expert_approved:
        raise ContributionGoldFormError(
            "final save requires explicit paper-level expert approval"
        )
    if expected_arxiv_id and payload.get("arxiv_id") != expected_arxiv_id:
        raise ContributionGoldFormError("payload arxiv_id does not match selected paper")
    if expected_annotator and payload.get("annotator") != expected_annotator:
        raise ContributionGoldFormError(
            "payload annotator does not match selected expert"
        )
    annotation = validate_contribution_payload(payload)
    document = compact_contribution_annotation_document(annotation)
    json_document = contribution_gold_json_document(annotation)
    yaml_text = yaml_text_for_document(document)
    roundtrip = yaml.safe_load(yaml_text)
    if not isinstance(roundtrip, dict):
        raise ContributionGoldFormError("YAML roundtrip did not produce a mapping")
    validate_contribution_payload(roundtrip)
    yaml_path, json_path = annotation_paths(
        Path(gold_dir), annotation.arxiv_id, annotation.annotator
    )
    _atomic_write_text(yaml_path, yaml_text)
    _atomic_write_text(
        json_path,
        json.dumps(json_document, ensure_ascii=False, indent=2) + "\n",
    )
    deleted = (
        cleanup_migration_artifacts(
            Path(work_dir), annotation.arxiv_id, annotation.annotator
        )
        if work_dir is not None
        else []
    )
    return {
        "status": "annotation_saved",
        "yaml_path": str(yaml_path),
        "json_path": str(json_path),
        "deleted_temporary_artifacts": deleted,
        "lint_warnings": lint_contribution_annotation(annotation),
    }


def draft_artifact_summary(work_dir: Path, arxiv_id: str, annotator: str) -> dict[str, Any]:
    path = draft_path(Path(work_dir), arxiv_id, annotator)
    return {
        "exists": path.is_file(),
        "path": str(path),
        "is_reservation_marker": False,
        "formal_input": False,
    }


def validate_and_lint(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate plus lint without writing anything."""

    annotation = validate_contribution_payload(payload)
    return {
        "valid": True,
        "lint_warnings": lint_contribution_annotation(annotation),
        "notice": CONTRIBUTION_GOLD_NOTICE,
    }


# --- Unified workflow runtime adapters -------------------------------------

_expert_save_annotation = save_expert_annotation


def _gold_authority(payload: dict) -> bool:
    return bool((payload or {}).get("authorities", {}).get("gold_private"))


def _annotation_work_dir() -> Path:
    import os

    return Path(os.environ.get("STELLA_GOLD_WORK_DIR") or (Path(os.environ["STELLA_GOLD_DIR"]) / "work"))


def open_annotation(payload: dict, *, root: Path, paper_id: str | None = None) -> dict:
    """gold.open_annotation adapter: PDF-only contribution form draft."""

    import os

    from stella.workflows import operation_complete, operation_failed

    if not _gold_authority(payload):
        return operation_failed(
            "opening the contribution form requires private gold authority",
            kind="authority",
            blockers=["gold_private"],
        )
    if paper_id is None:
        return operation_failed(
            "annotation is a per-paper operation", kind="precondition"
        )
    if not os.environ.get("STELLA_GOLD_DIR"):
        return operation_failed(
            "STELLA_GOLD_DIR must point at the external private gold repository",
            kind="precondition",
        )
    paper_assets = Path(root) / "literature" / paper_id / "assets"
    pdf = next(iter(sorted(paper_assets.glob("*.pdf"))), None)
    if pdf is None:
        return operation_failed(
            "the contribution gold form is PDF-only; no paper PDF is archived",
            kind="precondition",
        )
    annotator = str(payload.get("expert") or "")
    if not annotator:
        return operation_failed(
            "an expert annotator handle is required", kind="precondition"
        )
    work_dir = _annotation_work_dir()
    work_dir.mkdir(parents=True, exist_ok=True)
    document = build_empty_contribution_payload(
        arxiv_id=paper_id, annotator=annotator
    )
    summary = save_draft(document, work_dir)
    return operation_complete(
        annotator=annotator,
        pdf=str(pdf),
        draft_path=summary.get("draft_path")
        or str(draft_path(work_dir, paper_id, annotator)),
    )


def validate_open(payload: dict, result: dict, *, root: Path) -> list[str]:
    """A completed open must leave a loadable draft for one paper and expert."""

    if result.get("status") != "complete":
        return []
    detail = result.get("detail") or {}
    draft = detail.get("draft_path")
    if not draft or not Path(draft).is_file():
        return ["open reported complete but its draft file is missing"]
    if not detail.get("annotator"):
        return ["open result does not name its annotator"]
    return []


def validate_annotation(payload: dict, *, root: Path, paper_id: str | None = None) -> dict:
    """gold.validate_annotation adapter: validate-before-save gate."""

    from stella.workflows import operation_complete, operation_failed

    if not _gold_authority(payload):
        return operation_failed(
            "validation requires private gold authority",
            kind="authority",
            blockers=["gold_private"],
        )
    if paper_id is None:
        return operation_failed(
            "annotation is a per-paper operation", kind="precondition"
        )
    annotator = str(payload.get("expert") or "")
    try:
        draft = load_draft(_annotation_work_dir(), paper_id, annotator)
    except Exception as error:  # noqa: BLE001
        return operation_failed(
            f"draft not loadable: {error}", kind="precondition"
        )
    try:
        result = validate_and_lint(draft)
    except Exception as error:  # noqa: BLE001 - a blocked save is the point
        return operation_failed(
            f"draft failed validation; save is blocked: {error}",
            kind="validation",
        )
    if result.get("ok") is False or result.get("errors"):
        return operation_failed(
            "draft failed validation; save is blocked",
            kind="validation",
            errors=result.get("errors"),
        )
    return operation_complete(annotator=annotator)


def validate_draft_gate(payload: dict, result: dict, *, root: Path) -> list[str]:
    """A completed validate gate must be re-checkable from its draft."""

    if result.get("status") != "complete":
        return []
    paper_id = result.get("paper_id")
    annotator = (result.get("detail") or {}).get("annotator") or payload.get("expert")
    if not paper_id or not annotator:
        return ["validate result does not identify its paper and annotator"]
    try:
        draft = load_draft(_annotation_work_dir(), paper_id, annotator)
    except Exception as error:  # noqa: BLE001
        return [f"validated draft is no longer loadable: {error}"]
    outcome = validate_and_lint(draft)
    if outcome.get("ok") is False or outcome.get("errors"):
        return ["validated draft no longer passes its own gate"]
    return []


def save_annotation(payload: dict, *, root: Path, paper_id: str | None = None) -> dict:
    """gold.save_annotation adapter: one JSON per paper/expert after validation."""

    import os

    from stella.workflows import operation_complete, operation_failed

    if not _gold_authority(payload):
        return operation_failed(
            "saving requires private gold authority",
            kind="authority",
            blockers=["gold_private"],
        )
    if paper_id is None:
        return operation_failed(
            "annotation is a per-paper operation", kind="precondition"
        )
    gate = validate_annotation(payload, root=root, paper_id=paper_id)
    if gate["status"] != "complete":
        return operation_failed(
            "validate-before-save gate failed",
            kind="validation",
            errors=(gate.get("detail") or {}).get("errors"),
        )
    gold_dir = os.environ.get("STELLA_GOLD_DIR", "")
    if not gold_dir:
        return operation_failed(
            "STELLA_GOLD_DIR is required for saving", kind="precondition"
        )
    annotator = str(payload.get("expert") or "")
    expert_approved = bool(payload.get("expert_approved"))
    summary = _expert_save_annotation(
        load_draft(_annotation_work_dir(), paper_id, annotator),
        Path(gold_dir),
        work_dir=_annotation_work_dir(),
        expected_arxiv_id=paper_id,
        expected_annotator=annotator,
        expert_approved=expert_approved,
    )
    return operation_complete(save=summary)


def validate_save_gate(payload: dict, result: dict, *, root: Path) -> list[str]:
    """A completed save must have written exactly one JSON annotation."""

    import os

    if result.get("status") != "complete":
        return []
    paper_id = result.get("paper_id")
    if not paper_id:
        return ["save result does not identify its paper"]
    detail = result.get("detail") or {}
    saved = (detail.get("save") or {}).get("annotation_path")
    if saved is None:
        return ["save result does not report its annotation path"]
    path = Path(saved)
    if not path.is_file():
        return [f"save reported complete but {path} is missing"]
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except ValueError as error:
        return [f"saved annotation is not parseable: {error}"]
    if path.suffix.lower() != ".json":
        return [f"saved annotation must be JSON: {path}"]
    return []
