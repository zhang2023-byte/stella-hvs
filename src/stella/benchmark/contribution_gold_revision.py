"""Transactional revisions for already-migrated contribution Gold."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from stella.benchmark.gold import validate_annotator_handle
from stella.benchmark.hvs_contribution_gold import (
    HvsContributionGoldAnnotation,
    contribution_gold_json_document,
    lint_contribution_annotation,
)
from stella.benchmark.paths import validate_path_segment
from stella.schema_registry import require_schema, schema_ref


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ContributionGoldRevisionError(ValueError):
    """An existing contribution annotation cannot be revised safely."""


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            check=False,
            capture_output=True,
        )
    except OSError as error:
        raise ContributionGoldRevisionError(
            "private Gold revision requires a Git repository"
        ) from error


def _private_repo_root(gold_dir: Path) -> Path:
    result = _git(gold_dir, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        raise ContributionGoldRevisionError(
            "private Gold revision requires a Git repository"
        )
    repo = Path(result.stdout.decode().strip()).resolve()
    try:
        Path(gold_dir).expanduser().resolve().relative_to(repo)
    except ValueError as error:
        raise ContributionGoldRevisionError(
            "private Gold directory is outside its Git repository"
        ) from error
    return repo


def _validated_sha256(value: str, *, label: str) -> str:
    rendered = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(rendered):
        raise ContributionGoldRevisionError(f"{label} must be a lowercase SHA256")
    return rendered


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _active_relative(paper_id: str, annotator: str) -> str:
    return f"{paper_id}/annotation_{annotator}.json"


def _active_path(gold_dir: Path, paper_id: str, annotator: str) -> Path:
    safe_paper = validate_path_segment(paper_id, "paper id")
    safe_expert = validate_annotator_handle(annotator)
    return Path(gold_dir).expanduser().resolve() / _active_relative(
        safe_paper, safe_expert
    )


def contribution_history_object_path(gold_dir: Path, sha256: str) -> Path:
    """Return the private, content-addressed location for one prior JSON."""

    digest = _validated_sha256(sha256, label="history SHA")
    return _private_repo_root(Path(gold_dir)) / "contribution-history" / "objects" / f"{digest}.json"


def revision_lock_path(work_dir: Path, paper_id: str, annotator: str) -> Path:
    """Return the paper-scoped private work lock used by one revision."""

    safe_paper = validate_path_segment(paper_id, "paper id")
    safe_expert = validate_annotator_handle(annotator)
    return (
        Path(work_dir).expanduser().resolve()
        / safe_paper
        / "locks"
        / f"revision_{safe_expert}.lock"
    )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_content_addressed_once(
    path: Path, payload: bytes
) -> tuple[Path, bool]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ContributionGoldRevisionError(
                "content-addressed private history collision"
            )
        return path, False
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    created = False

    def cleanup_uncommitted_target() -> None:
        nonlocal created
        if not created:
            return
        path.unlink(missing_ok=True)
        created = False
        try:
            _fsync_directory(path.parent)
        except Exception:  # noqa: BLE001 - best effort after a failed write
            pass

    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
            created = True
        except FileExistsError:
            if path.read_bytes() != payload:
                raise ContributionGoldRevisionError(
                    "content-addressed private history collision"
                )
        _fsync_directory(path.parent)
    except Exception:
        try:
            cleanup_uncommitted_target()
        except Exception as cleanup_error:
            raise ContributionGoldRevisionError(
                "failed content-addressed write left an uncommitted target"
            ) from cleanup_error
        raise
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except Exception as error:
            try:
                cleanup_uncommitted_target()
            except Exception as cleanup_error:
                raise ContributionGoldRevisionError(
                    "failed temporary cleanup left an uncommitted target"
                ) from cleanup_error
            raise
    return path, created


def _write_history_object_once(gold_dir: Path, payload: bytes) -> Path:
    digest = _sha256_bytes(payload)
    path, _ = _write_content_addressed_once(
        contribution_history_object_path(gold_dir, digest), payload
    )
    return path


def _receipt_document(
    *,
    paper_id: str,
    annotator: str,
    base_selection_id: str,
    previous_sha256: str,
    replacement_sha256: str,
) -> dict[str, str]:
    return {
        "operation": "contribution_gold_revision",
        "paper_id": paper_id,
        "annotator": annotator,
        "base_selection_id": base_selection_id,
        "previous_sha256": previous_sha256,
        "replacement_sha256": replacement_sha256,
        "active_annotation_file": _active_relative(paper_id, annotator),
    }


def _write_receipt_once(
    gold_dir: Path, receipt: dict[str, str]
) -> tuple[Path, bool]:
    payload = (
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    digest = _sha256_bytes(payload)
    path = (
        _private_repo_root(Path(gold_dir))
        / "contribution-history"
        / "receipts"
        / f"{digest}.json"
    )
    return _write_content_addressed_once(path, payload)


def _remove_created_receipt(path: Path) -> None:
    """Remove a receipt created by a transaction that was rolled back."""

    try:
        path.unlink()
    except FileNotFoundError:
        pass
    _fsync_directory(path.parent)


def _atomic_replace_bytes(path: Path, payload: bytes) -> None:
    """Replace one active file via same-directory temp, fsync, and rename."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _held_revision_lock(
    *, work_dir: Path, gold_dir: Path, paper_id: str, annotator: str
) -> Iterator[Path]:
    repo = _private_repo_root(gold_dir)
    lock = revision_lock_path(work_dir, paper_id, annotator)
    try:
        relative = lock.relative_to(repo)
    except ValueError as error:
        raise ContributionGoldRevisionError(
            "revision lock must be inside the private Git repository"
        ) from error
    ignored = _git(repo, "check-ignore", "-q", "--", relative.as_posix())
    if ignored.returncode != 0:
        raise ContributionGoldRevisionError(
            "revision lock path must be inside a private Git-ignored work tree"
        )
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise ContributionGoldRevisionError(
            "another contribution revision holds the paper lock"
        ) from error
    try:
        os.fsync(descriptor)
        os.close(descriptor)
        yield lock
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
        lock.unlink(missing_ok=True)


def _load_json_bytes(payload: bytes, *, label: str) -> dict[str, Any]:
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContributionGoldRevisionError(f"{label} is not valid JSON") from error
    if not isinstance(document, dict):
        raise ContributionGoldRevisionError(f"{label} must be a JSON object")
    return document


def _validate_contribution_document(
    document: dict[str, Any], *, paper_id: str, annotator: str, label: str
) -> HvsContributionGoldAnnotation:
    try:
        annotation = HvsContributionGoldAnnotation.model_validate(document)
    except Exception as error:
        raise ContributionGoldRevisionError(
            f"{label} is not valid contribution Gold"
        ) from error
    if annotation.arxiv_id != paper_id or annotation.annotator != annotator:
        raise ContributionGoldRevisionError(f"{label} identity mismatch")
    return annotation


def load_selected_contribution_annotation(
    gold_dir: Path, entry: dict[str, Any]
) -> dict[str, Any]:
    """Resolve one immutable contribution selection by its declared SHA."""

    paper_id = validate_path_segment(str(entry.get("arxiv_id") or ""), "paper id")
    annotator = validate_annotator_handle(
        str(entry.get("selected_expert") or "")
    )
    expected_file = f"annotation_{annotator}.json"
    if entry.get("annotation_file") != expected_file:
        raise ContributionGoldRevisionError(
            f"selected annotation path must be {expected_file}"
        )
    declared_sha = _validated_sha256(
        str(entry.get("sha256") or ""), label="selected annotation SHA"
    )
    active = _active_path(gold_dir, paper_id, annotator)
    payload: bytes | None = None
    if active.is_file():
        candidate = active.read_bytes()
        if _sha256_bytes(candidate) == declared_sha:
            payload = candidate
    if payload is None:
        try:
            history = contribution_history_object_path(gold_dir, declared_sha)
        except ContributionGoldRevisionError as error:
            raise ContributionGoldRevisionError(
                f"selected Gold hash mismatch and history is unavailable: {paper_id}/{annotator}"
            ) from error
        if not history.is_file():
            raise ContributionGoldRevisionError(
                f"selected Gold hash mismatch; declared bytes are absent from active and history: {paper_id}/{annotator}"
            )
        candidate = history.read_bytes()
        if _sha256_bytes(candidate) != declared_sha:
            raise ContributionGoldRevisionError(
                f"selected history hash mismatch: {paper_id}/{annotator}"
            )
        payload = candidate
    document = _load_json_bytes(payload, label="selected contribution Gold")
    _validate_contribution_document(
        document,
        paper_id=paper_id,
        annotator=annotator,
        label="selected contribution Gold",
    )
    return document


def _validate_base_selection(
    *,
    root: Path,
    base_selection_id: str,
    paper_id: str,
    annotator: str,
    expected_current_sha256: str,
) -> dict[str, Any]:
    selection_id = validate_path_segment(base_selection_id, "base selection id")
    path = Path(root) / "benchmark" / "gold_selections" / f"{selection_id}.json"
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContributionGoldRevisionError(
            "base selection is missing or invalid"
        ) from error
    if not isinstance(profile, dict):
        raise ContributionGoldRevisionError("base selection must be a JSON object")
    try:
        require_schema(
            profile,
            "benchmark.hvs_contribution_gold_selection",
            require_current=True,
        )
    except ValueError as error:
        raise ContributionGoldRevisionError("base selection schema mismatch") from error
    if profile.get("selection_id") != selection_id:
        raise ContributionGoldRevisionError("base selection id mismatch")
    if profile.get("target_schema") != schema_ref(
        "benchmark.hvs_contribution_annotation"
    ):
        raise ContributionGoldRevisionError("base selection target schema mismatch")
    matches = [
        entry
        for entry in profile.get("papers") or []
        if isinstance(entry, dict) and entry.get("arxiv_id") == paper_id
    ]
    if len(matches) != 1:
        raise ContributionGoldRevisionError(
            "base selection must contain the paper exactly once"
        )
    entry = matches[0]
    if entry.get("selected_expert") != annotator:
        raise ContributionGoldRevisionError("base selection expert mismatch")
    if entry.get("annotation_file") != f"annotation_{annotator}.json":
        raise ContributionGoldRevisionError("base selection annotation file mismatch")
    selected_sha = _validated_sha256(
        str(entry.get("sha256") or ""), label="base selection SHA"
    )
    if selected_sha != expected_current_sha256:
        raise ContributionGoldRevisionError(
            "base selection SHA does not match expected current SHA"
        )
    return entry


def revise_contribution_annotation(
    *,
    root: Path,
    gold_dir: Path,
    work_dir: Path,
    paper_id: str,
    annotator: str,
    draft: dict[str, Any],
    base_selection_id: str,
    expected_current_sha256: str,
    expert_approved: bool,
) -> dict[str, Any]:
    """Revise active contribution Gold while preserving its selected base."""

    if not expert_approved:
        raise ContributionGoldRevisionError(
            "final revision requires explicit paper-level expert approval"
        )
    safe_paper = validate_path_segment(paper_id, "paper id")
    safe_expert = validate_annotator_handle(annotator)
    selection_id = validate_path_segment(base_selection_id, "base selection id")
    expected_sha = _validated_sha256(
        expected_current_sha256, label="expected current SHA"
    )
    active = _active_path(gold_dir, safe_paper, safe_expert)
    if not active.is_file():
        raise ContributionGoldRevisionError("active contribution Gold is missing")
    try:
        annotation = HvsContributionGoldAnnotation.model_validate(draft)
    except Exception as error:
        raise ContributionGoldRevisionError("revision draft is invalid") from error
    if annotation.arxiv_id != safe_paper or annotation.annotator != safe_expert:
        raise ContributionGoldRevisionError("revision draft identity mismatch")
    replacement_document = contribution_gold_json_document(annotation)
    replacement = (
        json.dumps(replacement_document, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    replacement_sha = _sha256_bytes(replacement)
    lint_warnings = lint_contribution_annotation(annotation)

    previous: bytes | None = None
    history: Path | None = None
    replacement_started = False
    receipt_path: Path | None = None
    receipt_created = False

    def rollback_replacement(error: Exception) -> None:
        nonlocal replacement_started
        if not replacement_started:
            return
        if previous is None or history is None:
            raise ContributionGoldRevisionError(
                "contribution revision failed without rollback material"
            ) from error
        try:
            _atomic_replace_bytes(active, history.read_bytes())
        except Exception as rollback_error:
            raise ContributionGoldRevisionError(
                "contribution revision failed and canonical rollback failed"
            ) from rollback_error
        if active.read_bytes() != previous:
            raise ContributionGoldRevisionError(
                "contribution revision rollback did not restore exact bytes"
            ) from error
        replacement_started = False

    def remove_rolled_back_receipt() -> None:
        nonlocal receipt_created
        if receipt_created and receipt_path is not None:
            _remove_created_receipt(receipt_path)
            receipt_created = False

    try:
        with _held_revision_lock(
            work_dir=work_dir,
            gold_dir=gold_dir,
            paper_id=safe_paper,
            annotator=safe_expert,
        ):
            _validate_base_selection(
                root=root,
                base_selection_id=selection_id,
                paper_id=safe_paper,
                annotator=safe_expert,
                expected_current_sha256=expected_sha,
            )
            previous = active.read_bytes()
            if _sha256_bytes(previous) != expected_sha:
                raise ContributionGoldRevisionError(
                    "active contribution Gold drifted from expected current SHA"
                )
            previous_document = _load_json_bytes(
                previous, label="active contribution Gold"
            )
            _validate_contribution_document(
                previous_document,
                paper_id=safe_paper,
                annotator=safe_expert,
                label="active contribution Gold",
            )
            history = _write_history_object_once(gold_dir, previous)
            if active.read_bytes() != previous:
                raise ContributionGoldRevisionError(
                    "active contribution Gold drifted while the revision lock was held"
                )
            try:
                replacement_started = True
                _atomic_replace_bytes(active, replacement)
                if active.read_bytes() != replacement:
                    raise ContributionGoldRevisionError(
                        "active contribution replacement did not persist exact bytes"
                    )
                receipt = _receipt_document(
                    paper_id=safe_paper,
                    annotator=safe_expert,
                    base_selection_id=selection_id,
                    previous_sha256=expected_sha,
                    replacement_sha256=replacement_sha,
                )
                receipt_path, receipt_created = _write_receipt_once(
                    gold_dir, receipt
                )
            except Exception as error:
                try:
                    rollback_replacement(error)
                finally:
                    remove_rolled_back_receipt()
                raise
    except Exception as error:
        try:
            rollback_replacement(error)
        finally:
            remove_rolled_back_receipt()
        raise

    return {
        "status": "annotation_revised",
        "annotation_path": str(active),
        "json_path": str(active),
        "previous_sha256": expected_sha,
        "replacement_sha256": replacement_sha,
        "history_object": str(history),
        "receipt": str(receipt_path),
        "lint_warnings": lint_warnings,
    }
