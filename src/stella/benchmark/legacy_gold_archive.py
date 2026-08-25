"""Fail-closed archival of manifest-pinned V6 Gold before migration save."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from stella.benchmark.campaign import sha256_file
from stella.benchmark.gold import validate_annotator_handle
from stella.benchmark.gold_selection import validate_annotation_twin
from stella.benchmark.paths import validate_path_segment
from stella.benchmark.run_contract import canonical_sha256
from stella.schema_registry import (
    ACTIVE_BENCHMARK_CAMPAIGN,
    require_schema,
)


_PRESERVATION_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")


class LegacyGoldArchiveError(ValueError):
    """A legacy pair cannot be proven safe to archive or restore."""


@dataclass(frozen=True)
class LegacyGoldArchivePlan:
    """Validated source and destination paths for one legacy Gold pair."""

    selection_id: str
    preservation_ref: str
    yaml_source: Path
    json_source: Path
    yaml_archive: Path
    json_archive: Path

    def summary(self) -> dict[str, str]:
        return {
            "selection_id": self.selection_id,
            "preservation_ref": self.preservation_ref,
            "yaml_path": str(self.yaml_archive),
            "json_path": str(self.json_archive),
        }


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LegacyGoldArchiveError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise LegacyGoldArchiveError(f"{label} must be a JSON object: {path}")
    return payload


def _manifest_records(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    require_schema(manifest, "benchmark.gold_manifest", require_current=True)
    records: dict[str, dict[str, Any]] = {}
    for record in manifest.get("files") or []:
        if not isinstance(record, dict):
            raise LegacyGoldArchiveError("gold manifest files must contain objects")
        relative = str(record.get("file") or "")
        if not relative or relative in records:
            raise LegacyGoldArchiveError(
                f"duplicate or empty gold manifest file: {relative!r}"
            )
        records[relative] = record
    return records


def _validated_preservation_ref(value: str) -> str:
    ref = str(value or "").strip()
    if (
        not _PRESERVATION_REF_RE.fullmatch(ref)
        or ".." in ref
        or "//" in ref
        or ref.endswith(("/", ".", ".lock"))
    ):
        raise LegacyGoldArchiveError("invalid legacy preservation ref")
    return ref


def _git(repo: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise LegacyGoldArchiveError(
            f"private Gold preservation check failed: git {' '.join(args)}"
        ) from exc
    return result.stdout


def _private_repo_root(gold_dir: Path) -> Path:
    rendered = _git(gold_dir, "rev-parse", "--show-toplevel").decode().strip()
    repo = Path(rendered).resolve()
    try:
        gold_dir.resolve().relative_to(repo)
    except ValueError as exc:
        raise LegacyGoldArchiveError(
            "STELLA_GOLD_DIR is outside its private Git repository"
        ) from exc
    return repo


def _verify_ref_blob(
    repo: Path,
    *,
    preservation_ref: str,
    path: Path,
    record: dict[str, Any],
) -> None:
    try:
        relative = path.resolve().relative_to(repo).as_posix()
    except ValueError as exc:
        raise LegacyGoldArchiveError(
            "legacy Gold path is outside the private repository"
        ) from exc
    payload = _git(repo, "show", f"{preservation_ref}:{relative}")
    if hashlib.sha256(payload).hexdigest() != str(record.get("sha256") or ""):
        raise LegacyGoldArchiveError(
            f"preservation ref hash mismatch: {relative}"
        )
    if len(payload) != int(record.get("bytes") or -1):
        raise LegacyGoldArchiveError(
            f"preservation ref byte count mismatch: {relative}"
        )


def resolve_legacy_gold_archive_plan(
    *,
    root: Path,
    gold_dir: Path,
    paper_id: str,
    annotator: str,
    selection_id: str,
    preservation_ref: str,
) -> LegacyGoldArchivePlan:
    """Resolve one exact V6 pair through its frozen selection and Git ref."""

    safe_paper = validate_path_segment(paper_id, "paper id")
    safe_annotator = validate_annotator_handle(annotator)
    safe_selection = validate_path_segment(selection_id, "gold selection id")
    safe_ref = _validated_preservation_ref(preservation_ref)
    manifest_dir = (
        Path(root)
        / "benchmark"
        / "campaigns"
        / ACTIVE_BENCHMARK_CAMPAIGN
        / "manifest"
    )
    campaign_path = manifest_dir / "campaign_manifest.json"
    gold_manifest_path = manifest_dir / "gold_manifest.json"
    selection_path = manifest_dir / "gold_selections" / f"{safe_selection}.json"
    profile = _load_json_object(selection_path, label="gold selection profile")
    require_schema(profile, "benchmark.gold_selection", require_current=True)
    if profile.get("selection_id") != safe_selection:
        raise LegacyGoldArchiveError("gold selection id does not match its filename")
    expected_campaign = {
        "campaign_id": ACTIVE_BENCHMARK_CAMPAIGN,
        "sha256": sha256_file(campaign_path),
    }
    if profile.get("campaign") != expected_campaign:
        raise LegacyGoldArchiveError("gold selection campaign binding mismatch")
    papers = profile.get("papers")
    if not isinstance(papers, list):
        raise LegacyGoldArchiveError("gold selection papers must be a list")
    if profile.get("selected_records_sha256") != canonical_sha256(papers):
        raise LegacyGoldArchiveError("gold selection selected-records hash mismatch")
    if profile.get("source_gold_manifest_sha256") != sha256_file(
        gold_manifest_path
    ):
        raise LegacyGoldArchiveError("gold selection source manifest hash mismatch")
    matches = [
        paper
        for paper in papers
        if isinstance(paper, dict) and paper.get("arxiv_id") == safe_paper
    ]
    if len(matches) != 1:
        raise LegacyGoldArchiveError(
            f"gold selection must resolve exactly one record for {safe_paper}"
        )
    selected = matches[0]
    if selected.get("annotator") != safe_annotator:
        raise LegacyGoldArchiveError(
            f"gold selection annotator mismatch for {safe_paper}"
        )
    manifest = _load_json_object(gold_manifest_path, label="gold manifest")
    records = _manifest_records(manifest)
    selected_records: dict[str, dict[str, Any]] = {}
    for kind in ("yaml", "json"):
        record = selected.get(kind)
        if not isinstance(record, dict):
            raise LegacyGoldArchiveError(
                f"gold selection is missing the legacy {kind} record"
            )
        expected = f"{safe_paper}/annotation_{safe_annotator}.{kind}"
        if record.get("file") != expected:
            raise LegacyGoldArchiveError(
                f"selected legacy {kind} path must be {expected}"
            )
        current = records.get(expected)
        if current is None or any(
            record.get(field) != current.get(field)
            for field in ("arxiv_id", "file", "sha256", "bytes")
        ):
            raise LegacyGoldArchiveError(
                f"selected legacy record does not match gold manifest: {expected}"
            )
        selected_records[kind] = current
    resolved_gold_dir = Path(gold_dir).expanduser().resolve()
    validate_annotation_twin(
        resolved_gold_dir,
        arxiv_id=safe_paper,
        annotator=safe_annotator,
        yaml_record=selected_records["yaml"],
        json_record=selected_records["json"],
    )
    yaml_source = resolved_gold_dir / str(selected_records["yaml"]["file"])
    json_source = resolved_gold_dir / str(selected_records["json"]["file"])
    repo = _private_repo_root(resolved_gold_dir)
    _git(repo, "rev-parse", "--verify", f"{safe_ref}^{{commit}}")
    _verify_ref_blob(
        repo,
        preservation_ref=safe_ref,
        path=yaml_source,
        record=selected_records["yaml"],
    )
    _verify_ref_blob(
        repo,
        preservation_ref=safe_ref,
        path=json_source,
        record=selected_records["json"],
    )
    archive_dir = repo / "legacy-v6" / safe_paper
    yaml_archive = archive_dir / f"annotation_{safe_annotator}_old.yaml"
    json_archive = archive_dir / f"annotation_{safe_annotator}_old.json"
    for path in (yaml_archive, json_archive):
        if path.exists():
            raise LegacyGoldArchiveError(f"legacy archive already exists: {path}")
    return LegacyGoldArchivePlan(
        selection_id=safe_selection,
        preservation_ref=safe_ref,
        yaml_source=yaml_source,
        json_source=json_source,
        yaml_archive=yaml_archive,
        json_archive=json_archive,
    )


def _remove_empty_archive_dirs(plan: LegacyGoldArchivePlan) -> None:
    paper_dir = plan.yaml_archive.parent
    archive_root = paper_dir.parent
    if paper_dir.is_dir() and not any(paper_dir.iterdir()):
        paper_dir.rmdir()
    if archive_root.is_dir() and not any(archive_root.iterdir()):
        archive_root.rmdir()


def _restore_legacy_pair(plan: LegacyGoldArchivePlan) -> None:
    errors: list[str] = []
    for source, archive in (
        (plan.yaml_source, plan.yaml_archive),
        (plan.json_source, plan.json_archive),
    ):
        temporary = source.with_name(
            f".{source.name}.{uuid.uuid4().hex}.legacy-rollback"
        )
        try:
            if not archive.is_file():
                raise FileNotFoundError(f"missing rollback archive: {archive}")
            os.link(archive, temporary)
            os.replace(temporary, source)
        except OSError as exc:
            errors.append(f"restore {source}: {exc}")
        finally:
            temporary.unlink(missing_ok=True)
    if not errors:
        for archive in (plan.yaml_archive, plan.json_archive):
            archive.unlink(missing_ok=True)
        _remove_empty_archive_dirs(plan)
    if errors:
        raise LegacyGoldArchiveError(
            "legacy rollback failed: " + "; ".join(errors)
        )


@contextmanager
def archived_legacy_pair(
    plan: LegacyGoldArchivePlan,
) -> Iterator[dict[str, str]]:
    """Archive both files, restoring them if publication raises."""

    plan.yaml_archive.parent.mkdir(parents=True, exist_ok=True)
    try:
        for source, archive in (
            (plan.yaml_source, plan.yaml_archive),
            (plan.json_source, plan.json_archive),
        ):
            os.link(source, archive)
        plan.yaml_source.unlink()
        plan.json_source.unlink()
        yield plan.summary()
    except Exception:
        try:
            _restore_legacy_pair(plan)
        except Exception as rollback_error:
            raise LegacyGoldArchiveError(
                f"legacy archival failed and rollback did not complete: {rollback_error}"
            ) from rollback_error
        raise
