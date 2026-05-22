"""Build object-level HVS candidate catalog files from paper-level extractions."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import astropy.units as u
from astropy.coordinates import SkyCoord

from high_velocity_lit.catalog_review import read_json, relative_path, write_json
from high_velocity_lit.hvs_candidates_index import HVS_CANDIDATES_FILENAME, iter_hvs_candidates_paths
from high_velocity_lit.schema_models import LiteratureHvsCandidatesRecord


OBJECT_SCHEMA_VERSION = "stella.hvs_candidate_catalog.object.v1"
INDEX_SCHEMA_VERSION = "stella.hvs_candidate_catalog.index.v1"
INDEX_JSON_FILENAME = "hvs_candidates_index.json"
INDEX_MARKDOWN_FILENAME = "hvs_candidates_index.md"
MATCH_RADIUS_ARCSEC = 5.0

GAIA_SOURCE_ID_RE = re.compile(r"^Gaia\s+((?:E)?DR\d+)\s+(\d+)$", re.IGNORECASE)
UNSAFE_SLUG_RE = re.compile(r"[^A-Za-z0-9]+")


@dataclass(frozen=True)
class Contribution:
    """One paper-level candidate contribution to an object-level catalog record."""

    paper: dict[str, Any]
    source_json_path: str
    record_id: str
    paper_candidate_id: str
    gaia_source_id: str
    method_steps: list[dict[str, Any]]
    core: dict[str, Any]
    coordinate: SkyCoord | None = field(default=None, compare=False)
    coordinate_error: str = ""

    @property
    def gaia_match_key(self) -> str:
        return normalize_gaia_source_id(self.gaia_source_id)

    @property
    def identity(self) -> tuple[str, str]:
        return (self.source_json_path, self.record_id)


@dataclass
class CatalogObject:
    """Internal object group before source IDs and output filenames are assigned."""

    contributions: list[Contribution]
    warnings: list[dict[str, Any]]
    match_strategy: str


class UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, item: int) -> int:
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def normalize_gaia_source_id(value: Any) -> str:
    """Return a stable Gaia source id key for matching."""
    text = " ".join(str(value or "").strip().split())
    if not text:
        return ""
    match = GAIA_SOURCE_ID_RE.match(text)
    if not match:
        return text.casefold()
    return f"gaia {match.group(1).upper()} {match.group(2)}"


def safe_slug(value: Any) -> str:
    """Return a filesystem-safe slug while preserving readable ASCII tokens."""
    slug = UNSAFE_SLUG_RE.sub("_", str(value or "").strip()).strip("_")
    return slug or "candidate"


def _source_sort_key(contribution: Contribution) -> tuple[str, str, str, str]:
    paper = contribution.paper
    return (
        str(paper.get("month") or "9999-99"),
        str(paper.get("arxiv_id") or ""),
        contribution.record_id,
        contribution.source_json_path,
    )


def _candidate_ref(contribution: Contribution) -> dict[str, str]:
    return {
        "record_id": contribution.record_id,
        "paper_candidate_id": contribution.paper_candidate_id,
        "gaia_source_id": contribution.gaia_source_id,
        "source_json_path": contribution.source_json_path,
    }


def _remove_source_refs(value: Any) -> Any:
    """Recursively remove source_refs while preserving the rest of the record."""
    if isinstance(value, dict):
        return {key: _remove_source_refs(item) for key, item in value.items() if key != "source_refs"}
    if isinstance(value, list):
        return [_remove_source_refs(item) for item in value]
    return value


def _simplify_quantity(record: Any) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        return None
    simplified: dict[str, Any] = {
        "value": str(record.get("value") or ""),
        "unit": str(record.get("unit") or ""),
        "method_refs": [str(item) for item in record.get("method_refs") or []],
    }
    for key in ("error", "lower_error", "upper_error"):
        value = record.get(key)
        if value not in (None, ""):
            simplified[key] = str(value)
    return simplified


def simplify_core(core: Any) -> dict[str, Any]:
    """Keep only object-catalog quantity fields requested by the merge workflow."""
    source_core = core if isinstance(core, dict) else {}
    simplified: dict[str, Any] = {}
    for group_name in ("observed_phase_space", "derived_kinematics", "bound_assessment"):
        group = source_core.get(group_name)
        output_group: dict[str, Any] = {}
        if isinstance(group, dict):
            for field_name, quantity in group.items():
                simplified_quantity = _simplify_quantity(quantity)
                if simplified_quantity is not None:
                    output_group[field_name] = simplified_quantity
        simplified[group_name] = output_group
    return simplified


def _normalize_coordinate_text(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^([+-])\s+", r"\1", text)
    text = re.sub(r"\s*:\s*", ":", text)
    return text


def parse_candidate_coordinate(core: Any) -> tuple[SkyCoord | None, str]:
    """Parse RA/Dec from an original or simplified candidate core."""
    if not isinstance(core, dict):
        return None, ""
    observed = core.get("observed_phase_space")
    if not isinstance(observed, dict):
        return None, ""
    ra = observed.get("ra")
    dec = observed.get("dec")
    if not isinstance(ra, dict) or not isinstance(dec, dict):
        return None, ""

    ra_value = _normalize_coordinate_text(ra.get("value"))
    dec_value = _normalize_coordinate_text(dec.get("value"))
    if not ra_value or not dec_value:
        return None, ""

    ra_unit_text = str(ra.get("unit") or "").strip().lower()
    ra_format = str(ra.get("coordinate_format") or "").strip()
    try:
        ra_unit = u.deg
        if (
            ra_unit_text == "hourangle"
            or ra_format == "sexagesimal_hms"
            or (":" in ra_value and ra_unit_text not in {"deg", "degree", "degrees"})
        ):
            ra_unit = u.hourangle
        return SkyCoord(ra=ra_value, dec=dec_value, unit=(ra_unit, u.deg), frame="icrs"), ""
    except Exception as exc:  # pragma: no cover - astropy exception types vary.
        return None, f"{type(exc).__name__}: {exc}"


def _load_paper_payload(path: Path, *, workspace: Path) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    try:
        payload = read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        return None, {"path": relative_path(path, workspace=workspace), "error": f"{type(exc).__name__}: {exc}"}
    try:
        LiteratureHvsCandidatesRecord.model_validate(payload)
    except Exception as exc:
        return None, {"path": relative_path(path, workspace=workspace), "error": f"{type(exc).__name__}: {exc}"}
    return payload, None


def contributions_from_paper_path(path: Path, *, workspace: Path) -> tuple[list[Contribution], dict[str, str] | None]:
    """Load and validate one paper-level extraction JSON."""
    payload, skipped = _load_paper_payload(path, workspace=workspace)
    if payload is None:
        return [], skipped

    paper = payload.get("paper") if isinstance(payload.get("paper"), dict) else {}
    method_steps = _remove_source_refs(payload.get("method_chain") or [])
    source_json_path = relative_path(path, workspace=workspace)
    contributions: list[Contribution] = []
    for candidate in payload.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        identifiers = candidate.get("identifiers") if isinstance(candidate.get("identifiers"), dict) else {}
        core = simplify_core(candidate.get("core") or {})
        coordinate, coordinate_error = parse_candidate_coordinate(candidate.get("core") or {})
        contributions.append(
            Contribution(
                paper=dict(paper),
                source_json_path=source_json_path,
                record_id=str(identifiers.get("record_id") or ""),
                paper_candidate_id=str(identifiers.get("paper_candidate_id") or ""),
                gaia_source_id=str(identifiers.get("gaia_source_id") or ""),
                method_steps=list(method_steps),
                core=core,
                coordinate=coordinate,
                coordinate_error=coordinate_error,
            )
        )
    return contributions, None


def _separation_arcsec(left: Contribution, right: Contribution) -> float | None:
    if left.coordinate is None or right.coordinate is None:
        return None
    return float(left.coordinate.separation(right.coordinate).arcsec)


def _pair_warning(kind: str, message: str, left: Contribution, right: Contribution, sep: float) -> dict[str, Any]:
    return {
        "type": kind,
        "message": message,
        "separation_arcsec": round(sep, 6),
        "records": [_candidate_ref(left), _candidate_ref(right)],
    }


def merge_contributions(contributions: list[Contribution]) -> list[CatalogObject]:
    """Merge contributions into object-level groups using Gaia ID and coordinates."""
    ordered = sorted(contributions, key=_source_sort_key)
    uf = UnionFind(len(ordered))
    union_edges: list[tuple[str, int, int]] = []
    pair_warnings: list[tuple[tuple[int, ...], dict[str, Any]]] = []

    for left_index, left in enumerate(ordered):
        for right_index in range(left_index + 1, len(ordered)):
            right = ordered[right_index]
            left_gaia = left.gaia_match_key
            right_gaia = right.gaia_match_key
            sep = _separation_arcsec(left, right)

            if left_gaia and right_gaia:
                if left_gaia == right_gaia:
                    uf.union(left_index, right_index)
                    union_edges.append(("gaia_source_id", left_index, right_index))
                    if sep is not None and sep >= MATCH_RADIUS_ARCSEC:
                        pair_warnings.append(
                            (
                                (left_index, right_index),
                                _pair_warning(
                                    "same_gaia_far_coordinates",
                                    "same Gaia source id but RA/Dec separation is not < 5 arcsec",
                                    left,
                                    right,
                                    sep,
                                ),
                            )
                        )
                elif sep is not None and sep < MATCH_RADIUS_ARCSEC:
                    pair_warnings.append(
                        (
                            (left_index, right_index),
                            _pair_warning(
                                "different_gaia_near_coordinates",
                                "different Gaia source ids but RA/Dec separation is < 5 arcsec; records were not merged",
                                left,
                                right,
                                sep,
                            ),
                        )
                    )
                continue

            if sep is not None and sep < MATCH_RADIUS_ARCSEC:
                uf.union(left_index, right_index)
                union_edges.append(("coordinates", left_index, right_index))

    groups: dict[int, list[int]] = {}
    for index in range(len(ordered)):
        groups.setdefault(uf.find(index), []).append(index)

    group_warnings: dict[int, list[dict[str, Any]]] = {root: [] for root in groups}
    for indexes, warning in pair_warnings:
        target_roots = {uf.find(index) for index in indexes}
        for root in target_roots:
            group_warnings.setdefault(root, []).append(warning)

    for root, indexes in groups.items():
        for index in indexes:
            contribution = ordered[index]
            if contribution.coordinate_error:
                group_warnings[root].append(
                    {
                        "type": "coordinate_parse_failed",
                        "message": contribution.coordinate_error,
                        "records": [_candidate_ref(contribution)],
                    }
                )
        gaia_values = sorted({ordered[index].gaia_source_id for index in indexes if ordered[index].gaia_source_id})
        if len({normalize_gaia_source_id(value) for value in gaia_values}) > 1:
            group_warnings[root].append(
                {
                    "type": "multiple_gaia_source_ids_in_object",
                    "message": "merged object contains multiple non-empty Gaia source ids; review coordinate bridge matches",
                    "gaia_source_ids": gaia_values,
                    "records": [_candidate_ref(ordered[index]) for index in indexes],
                }
            )

    strategy_by_root: dict[int, str] = {}
    for root, indexes in groups.items():
        if len(indexes) == 1:
            strategy_by_root[root] = "singleton"
            continue
        edge_kinds = {kind for kind, left, right in union_edges if uf.find(left) == root and uf.find(right) == root}
        if edge_kinds == {"gaia_source_id"}:
            strategy_by_root[root] = "gaia_source_id"
        elif edge_kinds == {"coordinates"}:
            strategy_by_root[root] = "coordinates"
        elif edge_kinds:
            strategy_by_root[root] = "mixed"
        else:
            strategy_by_root[root] = "singleton"

    objects = [
        CatalogObject(
            contributions=[ordered[index] for index in indexes],
            warnings=group_warnings.get(root, []),
            match_strategy=strategy_by_root[root],
        )
        for root, indexes in sorted(groups.items(), key=lambda item: _source_sort_key(ordered[item[1][0]]))
    ]
    return objects


def _canonical_for_object(obj: CatalogObject) -> tuple[str, str, Contribution]:
    ordered = sorted(obj.contributions, key=_source_sort_key)
    gaia_contributions = [item for item in ordered if item.gaia_source_id.strip()]
    if gaia_contributions:
        contribution = gaia_contributions[0]
        return "gaia_source_id", contribution.gaia_source_id, contribution
    contribution = ordered[0]
    return "paper_candidate_id", contribution.paper_candidate_id or contribution.record_id, contribution


def _assign_object_ids(objects: list[CatalogObject]) -> list[tuple[CatalogObject, str]]:
    bases = [safe_slug(_canonical_for_object(obj)[1]) for obj in objects]
    seen: dict[str, int] = {}
    assigned: list[tuple[CatalogObject, str]] = []
    for obj, base in zip(objects, bases, strict=True):
        count = seen.get(base, 0)
        seen[base] = count + 1
        if count == 0 and bases.count(base) == 1:
            assigned.append((obj, base))
            continue
        if count == 0:
            assigned.append((obj, base))
            continue
        suffix = safe_slug(sorted(obj.contributions, key=_source_sort_key)[0].record_id)
        candidate = f"{base}__{suffix}"
        serial = 2
        used = {object_id for _, object_id in assigned}
        while candidate in used:
            candidate = f"{base}__{suffix}_{serial}"
            serial += 1
        assigned.append((obj, candidate))
    return assigned


def object_records_from_catalog_objects(
    objects: list[CatalogObject],
    *,
    generated_at: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for obj, object_id in _assign_object_ids(objects):
        ordered_contributions = sorted(obj.contributions, key=_source_sort_key)
        source_by_identity: dict[tuple[str, str], str] = {}
        sources: list[dict[str, Any]] = []
        method_chain: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []

        for index, contribution in enumerate(ordered_contributions, start=1):
            source_id = f"src-{index:03d}"
            source_by_identity[contribution.identity] = source_id
            sources.append(
                {
                    "source": source_id,
                    "paper": contribution.paper,
                    "source_json_path": contribution.source_json_path,
                    "record_id": contribution.record_id,
                    "paper_candidate_id": contribution.paper_candidate_id,
                    "gaia_source_id": contribution.gaia_source_id,
                }
            )
            method_chain.append({"source": source_id, "steps": contribution.method_steps})
            candidates.append(
                {
                    "source": source_id,
                    "identifiers": {
                        "record_id": contribution.record_id,
                        "paper_candidate_id": contribution.paper_candidate_id,
                        "gaia_source_id": contribution.gaia_source_id,
                    },
                    "core": contribution.core,
                }
            )

        canonical_kind, canonical_value, canonical_contribution = _canonical_for_object(obj)
        records.append(
            {
                "schema_version": OBJECT_SCHEMA_VERSION,
                "generated_at": generated_at,
                "object_id": object_id,
                "canonical_identifier": {
                    "kind": canonical_kind,
                    "value": canonical_value,
                    "source": source_by_identity.get(canonical_contribution.identity, "src-001"),
                },
                "sources": sources,
                "method_chain": method_chain,
                "candidates": candidates,
                "merge": {
                    "match_strategy": obj.match_strategy,
                    "warnings": obj.warnings,
                },
            }
        )
    records.sort(key=lambda item: str(item.get("object_id") or ""))
    return records


def _unique_values(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def build_catalog_index(
    object_records: list[dict[str, Any]],
    *,
    catalog_dir: Path,
    literature_dir: Path | None,
    skipped: list[dict[str, str]],
    generated_at: str,
    workspace: Path,
) -> dict[str, Any]:
    objects: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for record in object_records:
        sources = record.get("sources") if isinstance(record.get("sources"), list) else []
        source_items = [item for item in sources if isinstance(item, dict)]
        gaia_source_ids = _unique_values([str(item.get("gaia_source_id") or "") for item in source_items])
        paper_candidate_ids = _unique_values([str(item.get("paper_candidate_id") or "") for item in source_items])
        object_id = str(record.get("object_id") or "")
        object_warnings = (record.get("merge") or {}).get("warnings") if isinstance(record.get("merge"), dict) else []
        object_warning_items = [item for item in object_warnings if isinstance(item, dict)]
        for warning in object_warning_items:
            warning_with_object = {"object_id": object_id}
            warning_with_object.update(warning)
            warnings.append(warning_with_object)
        objects.append(
            {
                "object_id": object_id,
                "canonical_identifier": record.get("canonical_identifier") or {},
                "object_json_path": relative_path(catalog_dir / f"{object_id}.json", workspace=workspace),
                "source_count": len(source_items),
                "gaia_source_ids": gaia_source_ids,
                "paper_candidate_ids": paper_candidate_ids,
                "sources": [
                    {
                        "source": str(item.get("source") or ""),
                        "record_id": str(item.get("record_id") or ""),
                        "paper_candidate_id": str(item.get("paper_candidate_id") or ""),
                        "gaia_source_id": str(item.get("gaia_source_id") or ""),
                        "arxiv_id": str((item.get("paper") or {}).get("arxiv_id") or "")
                        if isinstance(item.get("paper"), dict)
                        else "",
                        "source_json_path": str(item.get("source_json_path") or ""),
                    }
                    for item in source_items
                ],
                "warning_count": len(object_warning_items),
                "match_strategy": str((record.get("merge") or {}).get("match_strategy") or "")
                if isinstance(record.get("merge"), dict)
                else "",
            }
        )

    summary = {
        "object_count": len(object_records),
        "source_count": sum(int(item.get("source_count") or 0) for item in objects),
        "candidate_count": sum(len(record.get("candidates") or []) for record in object_records),
        "objects_with_gaia_count": sum(1 for item in objects if item.get("gaia_source_ids")),
        "warning_count": len(warnings),
        "skipped_count": len(skipped),
    }

    return {
        "schema_version": INDEX_SCHEMA_VERSION,
        "generated_at": generated_at,
        "catalog_dir": str(catalog_dir),
        "literature_dir": str(literature_dir) if literature_dir is not None else "",
        "summary": summary,
        "objects": objects,
        "warnings": warnings,
        "skipped": skipped,
    }


def _markdown_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|")


def render_hvs_candidate_catalog_index(record: dict[str, Any]) -> str:
    summary = record.get("summary") or {}
    objects = record.get("objects") or []
    warnings = record.get("warnings") or []

    lines = [
        "# HVS Candidate Object Catalog",
        "",
        f"- Generated at: {record.get('generated_at')}",
        f"- Objects: {summary.get('object_count', 0)}",
        f"- Sources: {summary.get('source_count', 0)}",
        f"- Candidate records: {summary.get('candidate_count', 0)}",
        f"- Objects with Gaia source IDs: {summary.get('objects_with_gaia_count', 0)}",
        f"- Warnings: {summary.get('warning_count', 0)}",
        f"- Skipped malformed inputs: {summary.get('skipped_count', 0)}",
    ]

    if objects:
        lines.extend(["", "## Objects", ""])
        lines.append("| Object | Canonical identifier | Sources | Gaia source IDs | Paper IDs | Warnings | JSON |")
        lines.append("| --- | --- | ---: | --- | --- | ---: | --- |")
        for item in objects:
            canonical = item.get("canonical_identifier") if isinstance(item.get("canonical_identifier"), dict) else {}
            canonical_value = canonical.get("value") or item.get("object_id") or ""
            object_link = f"[JSON]({item.get('object_json_path')})" if item.get("object_json_path") else ""
            lines.append(
                f"| {_markdown_cell(item.get('object_id'))} | {_markdown_cell(canonical_value)} | "
                f"{item.get('source_count', 0)} | {_markdown_cell(', '.join(item.get('gaia_source_ids') or [])) or '-'} | "
                f"{_markdown_cell(', '.join(item.get('paper_candidate_ids') or [])) or '-'} | "
                f"{item.get('warning_count', 0)} | {object_link} |"
            )

    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.append("| Object | Type | Message |")
        lines.append("| --- | --- | --- |")
        for warning in warnings:
            lines.append(
                f"| {_markdown_cell(warning.get('object_id'))} | {_markdown_cell(warning.get('type'))} | "
                f"{_markdown_cell(warning.get('message'))} |"
            )

    lines.append("")
    return "\n".join(lines)


def _object_json_paths(catalog_dir: Path) -> list[Path]:
    if not catalog_dir.exists():
        return []
    paths: list[Path] = []
    for path in sorted(catalog_dir.glob("*.json")):
        if path.name == INDEX_JSON_FILENAME:
            continue
        try:
            payload = read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("schema_version") == OBJECT_SCHEMA_VERSION:
            paths.append(path)
    return paths


def _contributions_from_catalog_object(record: dict[str, Any]) -> list[Contribution]:
    source_records = {
        str(item.get("source") or ""): item
        for item in record.get("sources") or []
        if isinstance(item, dict) and item.get("source")
    }
    method_records = {
        str(item.get("source") or ""): item.get("steps") or []
        for item in record.get("method_chain") or []
        if isinstance(item, dict) and item.get("source")
    }

    contributions: list[Contribution] = []
    for candidate in record.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        source_id = str(candidate.get("source") or "")
        source_record = source_records.get(source_id)
        if not isinstance(source_record, dict):
            continue
        identifiers = candidate.get("identifiers") if isinstance(candidate.get("identifiers"), dict) else {}
        core = candidate.get("core") if isinstance(candidate.get("core"), dict) else {}
        coordinate, coordinate_error = parse_candidate_coordinate(core)
        paper = source_record.get("paper") if isinstance(source_record.get("paper"), dict) else {}
        contributions.append(
            Contribution(
                paper=dict(paper),
                source_json_path=str(source_record.get("source_json_path") or ""),
                record_id=str(identifiers.get("record_id") or source_record.get("record_id") or ""),
                paper_candidate_id=str(
                    identifiers.get("paper_candidate_id") or source_record.get("paper_candidate_id") or ""
                ),
                gaia_source_id=str(identifiers.get("gaia_source_id") or source_record.get("gaia_source_id") or ""),
                method_steps=_remove_source_refs(method_records.get(source_id, [])),
                core=simplify_core(core),
                coordinate=coordinate,
                coordinate_error=coordinate_error,
            )
        )
    return contributions


def load_catalog_contributions(
    catalog_dir: Path,
    *,
    workspace: Path,
) -> tuple[list[Contribution], list[dict[str, str]]]:
    contributions: list[Contribution] = []
    skipped: list[dict[str, str]] = []
    for path in _object_json_paths(catalog_dir):
        try:
            record = read_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            skipped.append({"path": relative_path(path, workspace=workspace), "error": f"{type(exc).__name__}: {exc}"})
            continue
        if record.get("schema_version") != OBJECT_SCHEMA_VERSION:
            continue
        contributions.extend(_contributions_from_catalog_object(record))
    return contributions, skipped


def _record_paths(object_records: list[dict[str, Any]], catalog_dir: Path) -> list[Path]:
    return [catalog_dir / f"{record.get('object_id')}.json" for record in object_records]


def _write_catalog_records(
    object_records: list[dict[str, Any]],
    index_record: dict[str, Any],
    *,
    catalog_dir: Path,
    dry_run: bool,
    remove_stale_objects: bool,
) -> dict[str, list[str]]:
    desired_paths = set(_record_paths(object_records, catalog_dir))
    stale_paths: list[Path] = []
    if remove_stale_objects:
        stale_paths = [path for path in _object_json_paths(catalog_dir) if path not in desired_paths]

    json_path = catalog_dir / INDEX_JSON_FILENAME
    markdown_path = catalog_dir / INDEX_MARKDOWN_FILENAME
    write_paths = [*desired_paths, json_path, markdown_path]
    if dry_run:
        return {
            "written_paths": [],
            "deleted_paths": [],
            "planned_write_paths": [str(path) for path in sorted(write_paths)],
            "planned_delete_paths": [str(path) for path in stale_paths],
        }

    catalog_dir.mkdir(parents=True, exist_ok=True)
    for path in stale_paths:
        path.unlink(missing_ok=True)
    for record in object_records:
        write_json(catalog_dir / f"{record.get('object_id')}.json", record)
    write_json(json_path, index_record)
    markdown_path.write_text(render_hvs_candidate_catalog_index(index_record), encoding="utf-8")
    return {
        "written_paths": [str(path) for path in sorted(write_paths)],
        "deleted_paths": [str(path) for path in stale_paths],
        "planned_write_paths": [],
        "planned_delete_paths": [],
    }


def _build_records_from_contributions(
    contributions: list[Contribution],
    *,
    catalog_dir: Path,
    literature_dir: Path | None,
    skipped: list[dict[str, str]],
    workspace: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    generated_at = datetime.now().isoformat(timespec="seconds")
    catalog_objects = merge_contributions(contributions)
    object_records = object_records_from_catalog_objects(catalog_objects, generated_at=generated_at)
    index_record = build_catalog_index(
        object_records,
        catalog_dir=catalog_dir,
        literature_dir=literature_dir,
        skipped=skipped,
        generated_at=generated_at,
        workspace=workspace,
    )
    return object_records, index_record


def rebuild_hvs_candidate_catalog(
    literature_dir: Path,
    catalog_dir: Path,
    *,
    workspace: Path | None = None,
) -> dict[str, Any]:
    """Build object-level catalog records from every paper-level candidate JSON."""
    workspace = workspace or literature_dir.parent
    contributions: list[Contribution] = []
    skipped: list[dict[str, str]] = []
    for path in iter_hvs_candidates_paths(literature_dir):
        path_contributions, path_skipped = contributions_from_paper_path(path, workspace=workspace)
        contributions.extend(path_contributions)
        if path_skipped is not None:
            skipped.append(path_skipped)

    object_records, index_record = _build_records_from_contributions(
        contributions,
        catalog_dir=catalog_dir,
        literature_dir=literature_dir,
        skipped=skipped,
        workspace=workspace,
    )
    return {
        "object_records": object_records,
        "index_record": index_record,
        "input_candidate_count": len(contributions),
        "skipped": skipped,
    }


def write_rebuilt_hvs_candidate_catalog(
    literature_dir: Path,
    catalog_dir: Path,
    *,
    workspace: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    workspace = workspace or literature_dir.parent
    result = rebuild_hvs_candidate_catalog(literature_dir, catalog_dir, workspace=workspace)
    write_result = _write_catalog_records(
        result["object_records"],
        result["index_record"],
        catalog_dir=catalog_dir,
        dry_run=dry_run,
        remove_stale_objects=True,
    )
    result.update(write_result)
    result["dry_run"] = dry_run
    return result


def update_hvs_candidate_catalog(
    candidate_json_path: Path,
    catalog_dir: Path,
    *,
    literature_dir: Path | None = None,
    workspace: Path | None = None,
) -> dict[str, Any]:
    """Merge one paper-level candidate JSON into the existing object catalog."""
    workspace = workspace or (literature_dir.parent if literature_dir is not None else catalog_dir.parent)
    existing_contributions, skipped = load_catalog_contributions(catalog_dir, workspace=workspace)
    new_contributions, new_skipped = contributions_from_paper_path(candidate_json_path, workspace=workspace)
    if new_skipped is not None:
        skipped.append(new_skipped)

    new_identities = {contribution.identity for contribution in new_contributions}
    retained_existing = [item for item in existing_contributions if item.identity not in new_identities]
    replaced_count = len(existing_contributions) - len(retained_existing)
    all_contributions = [*retained_existing, *new_contributions]

    object_records, index_record = _build_records_from_contributions(
        all_contributions,
        catalog_dir=catalog_dir,
        literature_dir=literature_dir,
        skipped=skipped,
        workspace=workspace,
    )
    return {
        "object_records": object_records,
        "index_record": index_record,
        "new_candidate_count": len(new_contributions),
        "replaced_existing_source_count": replaced_count,
        "skipped": skipped,
    }


def write_updated_hvs_candidate_catalog(
    candidate_json_path: Path,
    catalog_dir: Path,
    *,
    literature_dir: Path | None = None,
    workspace: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    workspace = workspace or (literature_dir.parent if literature_dir is not None else catalog_dir.parent)
    result = update_hvs_candidate_catalog(
        candidate_json_path,
        catalog_dir,
        literature_dir=literature_dir,
        workspace=workspace,
    )
    write_result = _write_catalog_records(
        result["object_records"],
        result["index_record"],
        catalog_dir=catalog_dir,
        dry_run=dry_run,
        remove_stale_objects=True,
    )
    result.update(write_result)
    result["dry_run"] = dry_run
    return result
