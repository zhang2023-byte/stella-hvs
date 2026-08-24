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
    safe_slug,
)
from stella.lit.hvs_contribution_models import derived_identifier_display_name
from stella.schema_registry import schema_ref
from stella.benchmark.hvs_contribution_scoring import identity_from_contribution
from stella.benchmark.identity import match_identities, parse_gaia_id


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _contribution_identifiers(contribution: dict[str, Any]) -> list[str]:
    values = [
        item.get("value") or ""
        for item in contribution.get("identifiers") or []
        if isinstance(item, dict)
    ]
    return _unique_values_preserving_order([value for value in values if value])


def _contribution_gaia_keys(contribution: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for value in _contribution_identifiers(contribution):
        gaia = parse_gaia_id(value)
        if gaia:
            keys.append(f"gaia {gaia[0].lower()} {gaia[1]}")
    return _unique_values_preserving_order(keys)


def _contribution_strong_identifiers(contribution: dict[str, Any]) -> list[str]:
    identifiers: list[str] = []
    seen: set[str] = set()
    for value in _contribution_identifiers(contribution):
        if parse_gaia_id(value) is not None:
            continue
        key = _normalized_alias(value)
        if not value or key in seen or _is_weak_identifier(value):
            continue
        seen.add(key)
        identifiers.append(value)
    return identifiers


def _timeline_entry(arxiv_id: str, contribution: dict[str, Any]) -> dict[str, Any]:
    """One timeline entry preserves the complete contribution record."""

    return {
        "arxiv_id": arxiv_id,
        "record_id": contribution.get("record_id"),
        "display_name": derived_identifier_display_name(
            contribution.get("identifiers") or [],
            fallback=str(contribution.get("record_id") or ""),
        ),
        "identifiers": contribution.get("identifiers"),
        "contribution_type": contribution.get("contribution_type"),
        "contribution_summary": contribution.get("contribution_summary"),
        "contribution_evidence": contribution.get("contribution_evidence"),
        "paper_boundness": contribution.get("paper_boundness"),
        "quantity_extraction_status": contribution.get("quantity_extraction_status"),
        "quantities": contribution.get("quantities") or [],
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
    identities = [
        identity_from_contribution(entry["contribution"]) for entry in entries
    ]
    component_gaia: dict[int, dict[str, set[str]]] = {}
    for index, identity in enumerate(identities):
        component_gaia[index] = {}
        if identity.gaia:
            release, source_id = identity.gaia
            component_gaia[index][release] = {source_id}

    def union_without_gaia_conflict(left: int, right: int) -> bool:
        left_root = union.find(left)
        right_root = union.find(right)
        if left_root == right_root:
            return True
        left_gaia = component_gaia[left_root]
        right_gaia = component_gaia[right_root]
        for release in left_gaia.keys() & right_gaia.keys():
            if left_gaia[release] != right_gaia[release]:
                return False
        merged = {
            release: set(source_ids)
            for release, source_ids in left_gaia.items()
        }
        for release, source_ids in right_gaia.items():
            merged.setdefault(release, set()).update(source_ids)
        union.union(left_root, right_root)
        new_root = union.find(left_root)
        component_gaia[new_root] = merged
        if right_root != new_root:
            component_gaia.pop(right_root, None)
        return True

    by_gaia: dict[str, list[int]] = {}
    by_identifier: dict[str, list[int]] = {}
    for index, entry in enumerate(entries):
        contribution = entry["contribution"]
        for key in _contribution_gaia_keys(contribution):
            by_gaia.setdefault(key, []).append(index)
        for identifier in _contribution_strong_identifiers(contribution):
            by_identifier.setdefault(_normalized_alias(identifier), []).append(index)
    # Tier 1: shared normalized Gaia source id.
    for indices in by_gaia.values():
        for index in indices[1:]:
            union_without_gaia_conflict(indices[0], index)
    # Tier 2: shared strong identifier, unless a same-release Gaia conflict vetoes it.
    for indices in by_identifier.values():
        for index in indices[1:]:
            union_without_gaia_conflict(indices[0], index)
    # Tier 3: unique coordinate facets. Ambiguous multivalue coordinates are
    # absent from the identity adapter and therefore never guessed here.
    coordinate_pairs: list[tuple[float, int, int]] = []
    for left in range(len(entries)):
        for right in range(left + 1, len(entries)):
            if union.find(left) == union.find(right):
                continue
            match = match_identities(identities[left], identities[right])
            if match.matched and match.method == "coordinates":
                coordinate_pairs.append(
                    (match.separation_arcsec or 0.0, left, right)
                )
    for _separation, left, right in sorted(coordinate_pairs):
        union_without_gaia_conflict(left, right)

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
        identifiers: list[str] = []
        for index in ordered:
            contribution = entries[index]["contribution"]
            for identifier in _contribution_identifiers(contribution):
                if _normalized_alias(identifier) not in {
                    _normalized_alias(item) for item in identifiers
                }:
                    identifiers.append(identifier)
        timeline = [
            _timeline_entry(entries[index]["arxiv_id"], entries[index]["contribution"])
            for index in ordered
        ]
        objects.append(
            {
                "object_id": "",
                "display_name": derived_identifier_display_name(
                    [{"value": value} for value in identifiers],
                    fallback=str(timeline[0].get("record_id") or "object"),
                ),
                "identifiers": identifiers,
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
                "identifiers": item["identifiers"],
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
    current_names = {
        f"{item['object_id']}.json" for item in catalog["_objects"]
    }
    for item in catalog["_objects"]:
        record = object_record(catalog, item["object_id"])
        (output_dir / f"{item['object_id']}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    removed_stale = []
    for path in sorted(output_dir.glob("hvc-*.json")):
        if path.name not in current_names:
            path.unlink()
            removed_stale.append(str(path))
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
        "removed_stale": removed_stale,
    }
