"""Value-free integrity checks for public benchmark gold snapshots."""

from __future__ import annotations

from typing import Any

from stella.schema_registry import require_schema


def _records_by_paper(manifest: dict[str, Any]) -> dict[str, dict[str, str]]:
    require_schema(manifest, "benchmark.gold_manifest")
    records: dict[str, dict[str, str]] = {}
    files = manifest.get("files")
    if not isinstance(files, list):
        raise ValueError("gold manifest files must be a list")
    for record in files:
        if not isinstance(record, dict) or not str(record.get("arxiv_id") or ""):
            raise ValueError("gold manifest records require arxiv_id")
        arxiv_id = str(record["arxiv_id"])
        relative = str(record.get("file") or "")
        digest = str(record.get("sha256") or "")
        if not relative or not digest:
            raise ValueError(f"gold manifest paper {arxiv_id} records require file and sha256")
        paper_records = records.setdefault(arxiv_id, {})
        if relative in paper_records:
            raise ValueError(f"duplicate gold manifest file for {arxiv_id}: {relative}")
        paper_records[relative] = digest
    return records


def validate_append_only_gold_manifest(
    previous: dict[str, Any], proposed: dict[str, Any]
) -> None:
    """Reject deletion or mutation of every already-snapshotted file.

    A later expert may append a new immutable YAML/JSON twin to an existing
    paper. Previously recorded files remain byte-addressed by their digest.
    """

    before = _records_by_paper(previous)
    after = _records_by_paper(proposed)
    for arxiv_id, old_records in before.items():
        new_records = after.get(arxiv_id)
        if new_records is None:
            raise ValueError(f"gold manifest paper {arxiv_id} was removed")
        for relative, old_digest in old_records.items():
            if relative not in new_records:
                raise ValueError(
                    f"gold manifest file was removed for {arxiv_id}: {relative}"
                )
            if new_records[relative] != old_digest:
                raise ValueError(
                    f"gold manifest paper {arxiv_id} hash changed: {relative}"
                )
