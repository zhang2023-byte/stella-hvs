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
    ContributionGoldAnnotation,
    contribution_gold_json_document,
    lint_contribution_annotation,
    validate_contribution_gold_annotation,
)
from stella.benchmark.paths import validate_path_segment


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


def revision_backup_path(work_dir: Path, paper_id: str, annotator: str) -> Path:
    """Return the ignored rollback backup path for one in-flight revision."""

    lock = revision_lock_path(work_dir, paper_id, annotator)
    return lock.with_suffix(".previous.json")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


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


def _write_revision_backup_once(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ContributionGoldRevisionError(
            "a prior revision rollback backup still exists"
        ) from error
    _fsync_directory(path.parent)


def _remove_revision_backup(path: Path) -> None:
    path.unlink(missing_ok=True)
    _fsync_directory(path.parent)


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
) -> ContributionGoldAnnotation:
    try:
        annotation = validate_contribution_gold_annotation(document)
    except Exception as error:
        raise ContributionGoldRevisionError(
            f"{label} is not valid contribution Gold"
        ) from error
    if annotation.arxiv_id != paper_id or annotation.annotator != annotator:
        raise ContributionGoldRevisionError(f"{label} identity mismatch")
    return annotation


def _require_active_in_private_head(
    repo: Path, active: Path, active_bytes: bytes
) -> str:
    try:
        relative = active.resolve().relative_to(repo).as_posix()
    except ValueError as error:
        raise ContributionGoldRevisionError(
            "active contribution Gold is outside its private Git repository"
        ) from error
    clean = _git(repo, "diff", "--quiet", "HEAD", "--", relative)
    if clean.returncode != 0:
        raise ContributionGoldRevisionError(
            "active contribution Gold must match private Git HEAD before revision"
        )
    committed = _git(repo, "show", f"HEAD:{relative}")
    if committed.returncode != 0 or committed.stdout != active_bytes:
        raise ContributionGoldRevisionError(
            "active contribution Gold must already be committed in private Git HEAD"
        )
    head = _git(repo, "rev-parse", "HEAD")
    if head.returncode != 0:
        raise ContributionGoldRevisionError(
            "private Gold revision could not resolve Git HEAD"
        )
    return head.stdout.decode().strip()


def load_selected_contribution_annotation(
    gold_dir: Path, entry: dict[str, Any]
) -> dict[str, Any]:
    """Resolve one contribution selection from the active canonical only."""

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
    if not active.is_file():
        raise ContributionGoldRevisionError(
            f"selected active canonical is missing: {paper_id}/{annotator}"
        )
    payload = active.read_bytes()
    if _sha256_bytes(payload) != declared_sha:
        raise ContributionGoldRevisionError(
            f"selected Gold hash mismatch with active canonical: {paper_id}/{annotator}"
        )
    document = _load_json_bytes(payload, label="selected contribution Gold")
    _validate_contribution_document(
        document,
        paper_id=paper_id,
        annotator=annotator,
        label="selected contribution Gold",
    )
    return document


def revise_contribution_annotation(
    *,
    root: Path,
    gold_dir: Path,
    work_dir: Path,
    paper_id: str,
    annotator: str,
    draft: dict[str, Any],
    expected_current_sha256: str,
    expert_approved: bool,
) -> dict[str, Any]:
    """Revise active Gold after verifying its committed private-Git base."""

    del root
    if not expert_approved:
        raise ContributionGoldRevisionError(
            "final revision requires explicit paper-level expert approval"
        )
    safe_paper = validate_path_segment(paper_id, "paper id")
    safe_expert = validate_annotator_handle(annotator)
    expected_sha = _validated_sha256(
        expected_current_sha256, label="expected current SHA"
    )
    active = _active_path(gold_dir, safe_paper, safe_expert)
    if not active.is_file():
        raise ContributionGoldRevisionError("active contribution Gold is missing")
    try:
        annotation = validate_contribution_gold_annotation(
            draft, require_current=True
        )
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
    replacement_started = False
    backup = revision_backup_path(work_dir, safe_paper, safe_expert)
    backup_created = False
    previous_git_commit = ""

    def rollback_replacement(error: Exception) -> None:
        nonlocal replacement_started
        if not replacement_started:
            return
        if previous is None:
            raise ContributionGoldRevisionError(
                "contribution revision failed without rollback material"
            ) from error
        try:
            rollback_bytes = backup.read_bytes() if backup.is_file() else previous
            _atomic_replace_bytes(active, rollback_bytes)
        except Exception as rollback_error:
            raise ContributionGoldRevisionError(
                "contribution revision failed and canonical rollback failed"
            ) from rollback_error
        if rollback_bytes != previous or active.read_bytes() != previous:
            raise ContributionGoldRevisionError(
                "contribution revision rollback did not restore exact bytes"
            ) from error
        replacement_started = False

    def cleanup_backup() -> None:
        nonlocal backup_created
        if backup_created:
            _remove_revision_backup(backup)
            backup_created = False

    try:
        with _held_revision_lock(
            work_dir=work_dir,
            gold_dir=gold_dir,
            paper_id=safe_paper,
            annotator=safe_expert,
        ):
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
            repo = _private_repo_root(gold_dir)
            previous_git_commit = _require_active_in_private_head(
                repo, active, previous
            )
            _write_revision_backup_once(backup, previous)
            backup_created = True
            if active.read_bytes() != previous:
                raise ContributionGoldRevisionError(
                    "active contribution Gold drifted while the revision lock was held"
                )
            replacement_started = True
            _atomic_replace_bytes(active, replacement)
            if active.read_bytes() != replacement:
                raise ContributionGoldRevisionError(
                    "active contribution replacement did not persist exact bytes"
                )
        cleanup_backup()
    except Exception as error:
        try:
            rollback_replacement(error)
        finally:
            try:
                cleanup_backup()
            except Exception:
                pass
        raise

    return {
        "status": "annotation_revised",
        "annotation_path": str(active),
        "json_path": str(active),
        "previous_sha256": expected_sha,
        "replacement_sha256": replacement_sha,
        "previous_git_commit": previous_git_commit,
        "lint_warnings": lint_warnings,
    }
