"""Contribution gold migration form mechanics.

The original 50-paper migration uses temporary AI-assisted drafts followed by
paper-level expert approval. Only the approved JSON document is written to the
external private Gold store; known migration work artifacts are deleted after
that save succeeds.
"""

from __future__ import annotations

import json
import os
import secrets
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from stella.benchmark.hvs_contribution_gold import (
    CONTRIBUTION_MIGRATION_PROTOCOL,
    ContributionGoldAnnotation,
    compact_contribution_annotation_document,
    contribution_annotation_canary,
    contribution_gold_json_document,
    lint_contribution_annotation,
    validate_contribution_gold_annotation,
)
from stella.benchmark.gold import validate_annotator_handle
from stella.lit.arxiv_ids import validate_unversioned_arxiv_id
from stella.schema_registry import schema_ref
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
        "schema": schema_ref("benchmark.hvs_contribution_annotation"),
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


def validate_contribution_payload(payload: dict[str, Any]) -> ContributionGoldAnnotation:
    """Validate a filled contribution annotation payload."""

    return validate_contribution_gold_annotation(payload, require_current=True)


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


def resolve_paper_pdf(root: Path, arxiv_id: str) -> Path | None:
    """Resolve the canonical paper PDF, with legacy asset-layout fallback."""

    try:
        safe_arxiv_id = validate_unversioned_arxiv_id(arxiv_id)
    except ValueError as exc:
        raise ContributionGoldFormError(str(exc)) from exc
    paper_dir = Path(root) / "literature" / safe_arxiv_id
    canonical = paper_dir / "arxiv.pdf"
    if canonical.is_file():
        return canonical
    assets = paper_dir / "assets"
    if not assets.is_dir():
        return None
    return next(iter(sorted(assets.glob("*.pdf"))), None)


def draft_path(work_dir: Path, arxiv_id: str, annotator: str) -> Path:
    safe_arxiv_id, safe_annotator = _validated_identity(arxiv_id, annotator)
    return _paper_dir(work_dir, safe_arxiv_id) / f"draft_{safe_annotator}.json"


def annotation_json_path(gold_dir: Path, arxiv_id: str, annotator: str) -> Path:
    """The one canonical annotation path per paper and expert (JSON only)."""

    safe_arxiv_id, safe_annotator = _validated_identity(arxiv_id, annotator)
    return (
        _paper_dir(gold_dir, safe_arxiv_id)
        / f"annotation_{safe_annotator}.json"
    )


def annotation_paths(
    gold_dir: Path, arxiv_id: str, annotator: str
) -> tuple[Path, Path]:
    """Legacy read-only pair helper for historical twin-shaped stores."""

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
    """Atomically publish a new final artifact without replacing one."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise ContributionGoldFormError(
                f"final annotation already exists: {path}"
            ) from error
    finally:
        temporary.unlink(missing_ok=True)


def migration_artifact_paths(
    work_dir: Path, arxiv_id: str, annotator: str
) -> tuple[Path, ...]:
    """Return the known paper-scoped migration artifacts."""

    safe_arxiv_id, safe_annotator = _validated_identity(arxiv_id, annotator)
    paper_dir = _paper_dir(work_dir, safe_arxiv_id)
    return (
        paper_dir / "preannotation.json",
        paper_dir / "conflict_report.json",
        paper_dir / f"draft_{safe_annotator}.json",
    )


def existing_migration_artifacts(
    work_dir: Path, arxiv_id: str, annotator: str
) -> list[str]:
    """List known migration artifacts that currently exist."""

    return [
        str(path)
        for path in migration_artifact_paths(work_dir, arxiv_id, annotator)
        if path.is_file()
    ]


def cleanup_migration_artifacts(
    work_dir: Path, arxiv_id: str, annotator: str
) -> list[str]:
    """Delete only the known temporary files for one approved paper."""

    paths = migration_artifact_paths(work_dir, arxiv_id, annotator)
    paper_dir = paths[0].parent
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
    """Validate and atomically publish an expert-approved JSON annotation."""

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
    json_document = contribution_gold_json_document(annotation)
    json_path = annotation_json_path(
        Path(gold_dir), annotation.arxiv_id, annotation.annotator
    )
    lint_warnings = lint_contribution_annotation(annotation)
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
        "annotation_path": str(json_path),
        "json_path": str(json_path),
        "deleted_temporary_artifacts": deleted,
        "lint_warnings": lint_warnings,
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

    work_dir = os.environ.get("STELLA_GOLD_WORK_DIR")
    if work_dir:
        return Path(work_dir).expanduser()
    return Path(os.environ["STELLA_GOLD_DIR"]).expanduser() / "work"


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
    pdf = resolve_paper_pdf(root, paper_id)
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
        form_url=f"http://127.0.0.1:8765/papers/{paper_id}",
        serve_command=(
            "python -m stella gold-form serve "
            f"--paper {paper_id} --expert {annotator}"
        ),
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
            errors=[f"{type(error).__name__}: {error}"],
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
    retain_migration_work = bool(payload.get("retain_migration_work"))
    if not expert_approved:
        return operation_failed(
            "final save requires explicit paper-level expert approval",
            kind="precondition",
        )
    resolved_gold_dir = Path(gold_dir).expanduser().resolve()
    final_json = annotation_json_path(resolved_gold_dir, paper_id, annotator)
    legacy_yaml = annotation_paths(resolved_gold_dir, paper_id, annotator)[0]
    draft = load_draft(_annotation_work_dir(), paper_id, annotator)
    superseded_previous_sha256: str | None = None
    if final_json.exists():
        authorities = (payload or {}).get("authorities") or {}
        if not authorities.get("supersede"):
            return operation_failed(
                "existing Gold requires explicit supersede authority",
                kind="authority",
                blockers=["supersede"],
            )
        try:
            active_document = json.loads(final_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            return operation_failed(
                f"existing Gold is not valid JSON: {error}", kind="validation"
            )
        active_schema = (
            active_document.get("schema")
            if isinstance(active_document, dict)
            else None
        )
        is_contribution = (
            isinstance(active_schema, dict)
            and active_schema.get("name")
            == "benchmark.hvs_contribution_annotation"
        )
        if is_contribution:
            if legacy_yaml.exists():
                return operation_failed(
                    "active contribution Gold must not have a YAML twin",
                    kind="validation",
                )
            if not retain_migration_work:
                return operation_failed(
                    "contribution revision requires retained migration work",
                    kind="precondition",
                )
            try:
                retained_migration_artifacts = existing_migration_artifacts(
                    _annotation_work_dir(), paper_id, annotator
                )
            except Exception as error:  # noqa: BLE001 - fail before transaction
                return operation_failed(
                    f"contribution revision could not inspect retained migration work: {error}",
                    kind="validation",
                    errors=[f"{type(error).__name__}: {error}"],
                )
            expected_current_sha256 = str(
                payload.get("expected_current_sha256") or ""
            )
            if not expected_current_sha256:
                return operation_failed(
                    "contribution revision requires an expected current SHA",
                    kind="precondition",
                )
            try:
                from stella.benchmark.contribution_gold_revision import (
                    revise_contribution_annotation,
                )

                summary = revise_contribution_annotation(
                    root=root,
                    gold_dir=resolved_gold_dir,
                    work_dir=_annotation_work_dir(),
                    paper_id=paper_id,
                    annotator=annotator,
                    draft=draft,
                    expected_current_sha256=expected_current_sha256,
                    expert_approved=expert_approved,
                )
                superseded_previous_sha256 = str(
                    summary.get("previous_sha256") or ""
                )
                summary["retained_migration_artifacts"] = (
                    retained_migration_artifacts
                )
                summary["deleted_temporary_artifacts"] = []
            except Exception as error:  # noqa: BLE001 - rollback is internal
                return operation_failed(
                    f"contribution revision failed: {error}",
                    kind="validation",
                    errors=[f"{type(error).__name__}: {error}"],
                )
        else:
            if not legacy_yaml.exists():
                return operation_failed(
                    "partial legacy Gold pair blocks JSON-only save",
                    kind="validation",
                )
            selection_id = str(payload.get("legacy_selection_id") or "")
            preservation_ref = str(payload.get("legacy_preservation_ref") or "")
            if not selection_id or not preservation_ref:
                return operation_failed(
                    "legacy replacement requires selection id and preservation ref",
                    kind="precondition",
                )
            try:
                from stella.benchmark.legacy_gold_archive import (
                    archived_legacy_pair,
                    resolve_legacy_gold_archive_plan,
                )

                archive_plan = resolve_legacy_gold_archive_plan(
                    root=root,
                    gold_dir=resolved_gold_dir,
                    paper_id=paper_id,
                    annotator=annotator,
                    selection_id=selection_id,
                    preservation_ref=preservation_ref,
                )
                with archived_legacy_pair(archive_plan) as archive_summary:
                    summary = _expert_save_annotation(
                        draft,
                        resolved_gold_dir,
                        expected_arxiv_id=paper_id,
                        expected_annotator=annotator,
                        expert_approved=expert_approved,
                    )
                if retain_migration_work:
                    summary["retained_migration_artifacts"] = (
                        existing_migration_artifacts(
                            _annotation_work_dir(), paper_id, annotator
                        )
                    )
                else:
                    summary["deleted_temporary_artifacts"] = (
                        cleanup_migration_artifacts(
                            _annotation_work_dir(), paper_id, annotator
                        )
                    )
                summary["legacy_archive"] = archive_summary
            except Exception as error:  # noqa: BLE001 - preserve legacy pair
                return operation_failed(
                    f"legacy archival replacement failed: {error}",
                    kind="validation",
                    errors=[f"{type(error).__name__}: {error}"],
                )
    else:
        if legacy_yaml.exists():
            return operation_failed(
                "partial legacy Gold pair blocks JSON-only save",
                kind="validation",
            )
        try:
            summary = _expert_save_annotation(
                draft,
                resolved_gold_dir,
                work_dir=None if retain_migration_work else _annotation_work_dir(),
                expected_arxiv_id=paper_id,
                expected_annotator=annotator,
                expert_approved=expert_approved,
            )
            if retain_migration_work:
                summary["retained_migration_artifacts"] = (
                    existing_migration_artifacts(
                        _annotation_work_dir(), paper_id, annotator
                    )
                )
        except Exception as error:  # noqa: BLE001 - operation failure is structured
            return operation_failed(
                f"annotation save failed: {error}",
                kind="validation",
                errors=[f"{type(error).__name__}: {error}"],
            )
    detail: dict[str, Any] = {"save": summary}
    if superseded_previous_sha256:
        detail["superseded_previous_sha256"] = superseded_previous_sha256
    return operation_complete(**detail)


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
    if path.suffix.lower() != ".json":
        return [f"saved annotation must be JSON: {path}"]
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        validate_contribution_payload(document)
    except (ValueError, ValidationError) as error:
        return [f"saved annotation does not revalidate: {error}"]
    if document.get("canary") != contribution_annotation_canary(document):
        return ["saved annotation canary does not match its validated content"]
    if payload.get("retain_migration_work"):
        save_detail = detail.get("save") or {}
        reported = set(save_detail.get("retained_migration_artifacts") or [])
        if detail.get("superseded_previous_sha256"):
            if not reported:
                return [
                    "contribution revision did not report retained migration work"
                ]
        else:
            expected = set(
                existing_migration_artifacts(
                    _annotation_work_dir(), paper_id, str(payload.get("expert") or "")
                )
            )
            if not expected:
                return ["save requested migration-work retention but no artifacts remain"]
            if reported != expected:
                return ["save retention summary does not match migration-work on disk"]
    annotator = str(payload.get("expert") or "")
    if annotator:
        yaml_path = annotation_paths(path.parents[1], paper_id, annotator)[0]
        if yaml_path.exists():
            return [f"saved contribution annotation has a YAML twin: {yaml_path}"]
    return []
