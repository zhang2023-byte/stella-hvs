"""Object-level contribution timeline catalog.

Reads only ``literature_hvs_contributions`` documents and groups their
paper-object contributions into per-object timelines using the stable
name/Gaia identity tiers. The timeline preserves every contribution in
chronological paper order (arXiv ids sort chronologically), including
follow_up records whose ``paper_boundness.status`` is bound. No
authoritative global boundness state is created, values are never flattened
to one per object, and scientifically distinct prior-work values reported by
different papers are never silently deduplicated.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stella.lit.hvs_contributions_index import load_contribution_documents
from stella.lit.hvs_candidate_catalog import (
    UnionFind,
    _is_weak_identifier,
    _normalized_alias,
    _unique_values_preserving_order,
    normalize_gaia_source_id,
    safe_slug,
)
from stella.schema_registry import schema_ref


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _contribution_identifiers(contribution: dict[str, Any]) -> list[str]:
    identifiers = contribution.get("identifiers") or {}
    values = [contribution.get("display_name") or ""]
    values.append(identifiers.get("gaia_source_id") or "")
    for item in identifiers.get("all") or []:
        values.append(item.get("value") or "")
    return _unique_values_preserving_order([value for value in values if value])


def _contribution_gaia_keys(contribution: dict[str, Any]) -> list[str]:
    identifiers = contribution.get("identifiers") or {}
    keys = []
    gaia_source_id = identifiers.get("gaia_source_id") or ""
    if gaia_source_id:
        keys.append(normalize_gaia_source_id(gaia_source_id))
    for item in identifiers.get("all") or []:
        key = normalize_gaia_source_id(item.get("value") or "")
        if key.startswith("gaia "):
            keys.append(key)
    return _unique_values_preserving_order(keys)


def _contribution_strong_aliases(contribution: dict[str, Any]) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()
    for value in _contribution_identifiers(contribution):
        key = _normalized_alias(value)
        if not value or key in seen or _is_weak_identifier(value):
            continue
        seen.add(key)
        aliases.append(value)
    return aliases


def _timeline_entry(arxiv_id: str, contribution: dict[str, Any]) -> dict[str, Any]:
    """One timeline entry preserves the complete contribution record."""

    return {
        "arxiv_id": arxiv_id,
        "record_id": contribution.get("record_id"),
        "display_name": contribution.get("display_name"),
        "identifiers": contribution.get("identifiers"),
        "contribution_type": contribution.get("contribution_type"),
        "contribution_note": contribution.get("contribution_note"),
        "contribution_evidence": contribution.get("contribution_evidence"),
        "paper_boundness": contribution.get("paper_boundness"),
        "measurement_status": contribution.get("measurement_status"),
        "measurements": contribution.get("measurements") or [],
        "failure": contribution.get("failure"),
    }


def build_contribution_catalog(
    literature_dir: Path,
) -> dict[str, Any]:
    """Group all paper-object contributions into object timelines."""

    documents, _skipped = load_contribution_documents(literature_dir)
    entries: list[dict[str, Any]] = []
    for _path, payload in sorted(
        documents, key=lambda item: str(item[1]["paper"]["arxiv_id"])
    ):
        arxiv_id = payload["paper"]["arxiv_id"]
        for contribution in payload.get("object_contributions") or []:
            entries.append(
                {
                    "arxiv_id": arxiv_id,
                    "source_json_path": str(_path),
                    "contribution": contribution,
                }
            )

    union = UnionFind(len(entries))
    by_gaia: dict[str, list[int]] = {}
    by_alias: dict[str, list[int]] = {}
    for index, entry in enumerate(entries):
        contribution = entry["contribution"]
        for key in _contribution_gaia_keys(contribution):
            by_gaia.setdefault(key, []).append(index)
        for alias in _contribution_strong_aliases(contribution):
            by_alias.setdefault(_normalized_alias(alias), []).append(index)
    # Tier 1: shared normalized Gaia source id.
    for indices in by_gaia.values():
        for index in indices[1:]:
            union.union(indices[0], index)
    # Tier 2: shared strong alias (paper-boundness never participates).
    for indices in by_alias.values():
        for index in indices[1:]:
            union.union(indices[0], index)

    groups: dict[int, list[int]] = {}
    for index in range(len(entries)):
        groups.setdefault(union.find(index), []).append(index)

    objects: list[dict[str, Any]] = []
    for members in groups.values():
        ordered = sorted(
            members,
            key=lambda index: (
                entries[index]["arxiv_id"],
                str(entries[index]["contribution"].get("record_id") or ""),
            ),
        )
        aliases: list[str] = []
        gaia_keys: list[str] = []
        for index in ordered:
            contribution = entries[index]["contribution"]
            for alias in _contribution_strong_aliases(contribution):
                if _normalized_alias(alias) not in {
                    _normalized_alias(item) for item in aliases
                }:
                    aliases.append(alias)
            for key in _contribution_gaia_keys(contribution):
                if key not in gaia_keys:
                    gaia_keys.append(key)
        timeline = [
            _timeline_entry(entries[index]["arxiv_id"], entries[index]["contribution"])
            for index in ordered
        ]
        objects.append(
            {
                "object_id": "",
                "display_name": aliases[0] if aliases else timeline[0]["display_name"],
                "aliases": aliases,
                "gaia_source_keys": gaia_keys,
                "timeline": timeline,
            }
        )

    objects.sort(
        key=lambda item: (
            str(item["display_name"] or ""),
            item["timeline"][0]["arxiv_id"],
        )
    )
    used: set[str] = set()
    for item in objects:
        base = safe_slug(item["display_name"])
        object_id = base
        suffix = 2
        while object_id in used:
            object_id = f"{base}-{suffix}"
            suffix += 1
        used.add(object_id)
        item["object_id"] = f"hvc-{object_id}"

    return {
        "schema": schema_ref("hvs_contribution_catalog.index"),
        "generated_at": _utc_now(),
        "object_count": len(objects),
        "contribution_count": len(entries),
        "objects": [
            {
                "object_id": item["object_id"],
                "display_name": item["display_name"],
                "timeline_length": len(item["timeline"]),
                "first_arxiv_id": item["timeline"][0]["arxiv_id"],
                "last_arxiv_id": item["timeline"][-1]["arxiv_id"],
            }
            for item in objects
        ],
        "_objects": objects,
    }


def object_record(catalog: dict[str, Any], object_id: str) -> dict[str, Any]:
    for item in catalog["_objects"]:
        if item["object_id"] == object_id:
            timeline = item["timeline"]
            return {
                "schema": schema_ref("hvs_contribution_catalog.object"),
                "generated_at": catalog["generated_at"],
                "object_id": object_id,
                "display_name": item["display_name"],
                "aliases": item["aliases"],
                "gaia_source_keys": item["gaia_source_keys"],
                "timeline": timeline,
                "display_note": (
                    "Any 'latest' status shown by a view is the latest paper "
                    "report, not a Stella truth; this record stores no "
                    "authoritative global boundness state."
                ),
            }
    raise KeyError(f"unknown object_id: {object_id}")


def write_contribution_catalog(
    literature_dir: Path,
    *,
    output_dir: Path,
) -> dict[str, Any]:
    """Write per-object records plus the catalog index."""

    catalog = build_contribution_catalog(literature_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for item in catalog["_objects"]:
        record = object_record(catalog, item["object_id"])
        (output_dir / f"{item['object_id']}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    index_record = {key: value for key, value in catalog.items() if key != "_objects"}
    index_path = output_dir / "index.json"
    index_path.write_text(
        json.dumps(index_record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "index_record": index_record,
        "index_path": str(index_path),
        "object_count": len(catalog["_objects"]),
        "output_dir": str(output_dir),
    }
