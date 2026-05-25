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
from high_velocity_lit.hvs_catalog_enrichment import (
    ENRICHMENT_MODES,
    EnrichmentClients,
    enrich_object_records,
    disabled_enrichment,
)
from high_velocity_lit.hvs_candidates_index import HVS_CANDIDATES_FILENAME, iter_hvs_candidates_paths
from high_velocity_lit.schema_models import LiteratureHvsCandidatesRecord


OBJECT_SCHEMA_VERSION = "stella.hvs_candidate_catalog.object.v4"
LEGACY_OBJECT_SCHEMA_VERSIONS = {"stella.hvs_candidate_catalog.object.v3"}
INDEX_SCHEMA_VERSION = "stella.hvs_candidate_catalog.index.v2"
READABLE_OBJECT_SCHEMA_VERSIONS = {OBJECT_SCHEMA_VERSION, *LEGACY_OBJECT_SCHEMA_VERSIONS}
INDEX_JSON_FILENAME = "03_hvs_candidates_index.json"
INDEX_MARKDOWN_FILENAME = "03_hvs_candidates_index.md"
CANDIDATES_DIRNAME = "candidates"
LEGACY_INDEX_JSON_FILENAMES = ("hvs_candidates_index.json",)
LEGACY_INDEX_MARKDOWN_FILENAMES = ("hvs_candidates_index.md",)
MATCH_RADIUS_ARCSEC = 5.0

GAIA_SOURCE_ID_RE = re.compile(r"^Gaia\s+((?:E)?DR\d+)\s+(\d+)$", re.IGNORECASE)
UNSAFE_SLUG_RE = re.compile(r"[^A-Za-z0-9+-]+")
WEAK_IDENTIFIER_VALUES = {
    "candidate",
    "cand",
    "hvs",
    "hv",
    "id",
    "object",
    "source",
    "star",
    "target",
}


@dataclass(frozen=True)
class Contribution:
    """One paper-level candidate contribution to an object-level catalog record."""

    paper: dict[str, Any]
    source_json_path: str
    record_id: str
    paper_candidate_id: str
    gaia_source_id: str
    method_steps: list[dict[str, Any]]
    candidate: dict[str, Any]
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


@dataclass(frozen=True)
class GaiaSourceId:
    release: str
    source_id: str
    raw: str

    @property
    def release_family(self) -> str:
        if self.release in {"DR3", "EDR3"}:
            return "DR3"
        return self.release

    @property
    def match_key(self) -> str:
        return f"gaia {self.release_family} {self.source_id}"

    @property
    def object_value(self) -> str:
        return f"Gaia {self.release_family} {self.source_id}"


def parse_gaia_source_id(value: Any) -> GaiaSourceId | None:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return None
    match = GAIA_SOURCE_ID_RE.match(text)
    if not match:
        return None
    return GaiaSourceId(release=match.group(1).upper(), source_id=match.group(2), raw=text)


def normalize_gaia_source_id(value: Any) -> str:
    """Return a stable Gaia source id key for matching."""
    text = " ".join(str(value or "").strip().split())
    if not text:
        return ""
    parsed = parse_gaia_source_id(text)
    if parsed is None:
        return text.casefold()
    return parsed.match_key


def safe_slug(value: Any) -> str:
    """Return a filesystem-safe slug while preserving readable ASCII tokens."""
    slug = UNSAFE_SLUG_RE.sub("_", str(value or "").strip()).strip("_")
    return slug or "candidate"


def _is_weak_identifier(value: Any) -> bool:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return True
    if text.isdigit():
        return True
    compact = re.sub(r"[^A-Za-z0-9]+", "", text).casefold()
    if len(compact) == 1 and compact.isalpha():
        return True
    return compact in WEAK_IDENTIFIER_VALUES


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


def _non_empty(value: Any) -> bool:
    return value not in (None, "", [], {})


def _copy_semantic_fields(record: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for field_name in fields:
        value = record.get(field_name)
        if isinstance(value, list):
            items = [str(item) for item in value if str(item).strip()]
            if items:
                output[field_name] = items
            continue
        if _non_empty(value):
            output[field_name] = str(value)
    return output


def _simplify_quantity(record: Any, *, semantic_fields: tuple[str, ...] = ()) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        return None
    simplified: dict[str, Any] = _copy_semantic_fields(record, semantic_fields)
    simplified.update(
        {
            "value": str(record.get("value") or ""),
            "unit": str(record.get("unit") or ""),
            "method_refs": [str(item) for item in record.get("method_refs") or []],
        }
    )
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


def _simplify_quantity_list(records: Any, *, semantic_fields: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    if not isinstance(records, list):
        return []
    simplified: list[dict[str, Any]] = []
    for record in records:
        quantity = _simplify_quantity(record, semantic_fields=semantic_fields)
        if quantity is not None:
            simplified.append(quantity)
    return simplified


def _simplify_quantity_object(
    group: Any,
    *,
    quantity_fields: tuple[str, ...],
    list_fields: dict[str, tuple[str, ...]],
) -> dict[str, Any]:
    source_group = group if isinstance(group, dict) else {}
    simplified: dict[str, Any] = {}
    for field_name in quantity_fields:
        quantity = _simplify_quantity(source_group.get(field_name))
        if quantity is not None:
            simplified[field_name] = quantity
    for field_name, semantic_fields in list_fields.items():
        simplified[field_name] = _simplify_quantity_list(
            source_group.get(field_name),
            semantic_fields=semantic_fields,
        )
    return simplified


def _simplify_candidate_context(candidate: dict[str, Any]) -> dict[str, Any]:
    assessment = candidate.get("inclusion_assessment") if isinstance(candidate.get("inclusion_assessment"), dict) else {}
    origin = candidate.get("candidate_origin") if isinstance(candidate.get("candidate_origin"), dict) else {}
    context: dict[str, Any] = {
        "paper_labels": [str(item) for item in assessment.get("paper_labels") or []],
        "galactic_bound_claim": str(assessment.get("galactic_bound_claim") or ""),
        "inclusion_basis": str(assessment.get("inclusion_basis") or ""),
        "extraction_confidence": str(assessment.get("extraction_confidence") or ""),
        "origin_type": str(origin.get("origin_type") or ""),
        "paper_reassesses_unbound_status": bool(origin.get("paper_reassesses_unbound_status")),
    }
    citation = origin.get("citation")
    if isinstance(citation, dict):
        citation_payload = _copy_semantic_fields(
            citation,
            ("bibkey", "authors", "year", "title", "doi", "bibcode", "arxiv_id"),
        )
        if citation_payload:
            context["citation"] = citation_payload
    return context


def _candidate_identifiers(candidate: dict[str, Any]) -> dict[str, Any]:
    identifiers = candidate.get("identifiers") if isinstance(candidate.get("identifiers"), dict) else {}
    payload: dict[str, Any] = {
        "record_id": str(identifiers.get("record_id") or ""),
        "paper_candidate_id": str(identifiers.get("paper_candidate_id") or ""),
        "gaia_source_id": str(identifiers.get("gaia_source_id") or ""),
    }
    all_values: list[str] = []
    seen: set[str] = set()
    for item in identifiers.get("all") or []:
        value = item.get("value") if isinstance(item, dict) else item
        text = " ".join(str(value or "").strip().split())
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            all_values.append(text)
    if all_values:
        payload["all"] = all_values
    return payload


def simplify_candidate(candidate: Any) -> dict[str, Any]:
    """Return the object-catalog compact candidate payload for a paper-level candidate."""
    source_candidate = candidate if isinstance(candidate, dict) else {}
    return {
        "identifiers": _candidate_identifiers(source_candidate),
        "candidate_context": _simplify_candidate_context(source_candidate),
        "core": simplify_core(source_candidate.get("core") or {}),
        "photometry": _simplify_quantity_list(
            source_candidate.get("photometry"),
            semantic_fields=("measurement_type", "band", "system", "survey"),
        ),
        "spectroscopy": _simplify_quantity_list(
            source_candidate.get("spectroscopy"),
            semantic_fields=("measurement_type", "spectral_type", "line", "instrument", "survey"),
        ),
        "stellar_parameters": _simplify_quantity_object(
            source_candidate.get("stellar_parameters"),
            quantity_fields=("teff", "log_g", "metallicity", "mass", "radius", "age", "luminosity", "spectral_type"),
            list_fields={"other": ("name",)},
        ),
        "abundances": _simplify_quantity_list(
            source_candidate.get("abundances"),
            semantic_fields=("element", "abundance_scale", "reference_element"),
        ),
        "quality_flags": _simplify_quantity_list(source_candidate.get("quality_flags"), semantic_fields=("name",)),
        "orbit": _simplify_quantity_object(
            source_candidate.get("orbit"),
            quantity_fields=(
                "eccentricity",
                "pericenter",
                "apocenter",
                "zmax",
                "flight_time",
                "disk_crossing_radius",
                "angular_momentum",
            ),
            list_fields={"other": ("name",)},
        ),
        "astrophysical_origin": _simplify_quantity_object(
            source_candidate.get("astrophysical_origin"),
            quantity_fields=("origin_site", "origin_classification", "ejection_velocity", "travel_time"),
            list_fields={"hypothesis_metrics": ("hypothesis", "metric_type"), "other": ("name",)},
        ),
        "extra": _simplify_quantity_list(source_candidate.get("extra"), semantic_fields=("name",)),
    }


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


def _coordinate_identifier(coordinate: SkyCoord | None) -> str:
    if coordinate is None:
        return ""
    ra = coordinate.ra.to_string(unit=u.hourangle, sep="", precision=2, pad=True)
    dec = coordinate.dec.to_string(unit=u.deg, sep="", precision=1, alwayssign=True, pad=True)
    return f"J{ra.replace('.', '')}{dec.replace('.', '')}"


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
        coordinate, coordinate_error = parse_candidate_coordinate(candidate.get("core") or {})
        compact_candidate = simplify_candidate(candidate)
        contributions.append(
            Contribution(
                paper=dict(paper),
                source_json_path=source_json_path,
                record_id=str(identifiers.get("record_id") or ""),
                paper_candidate_id=str(identifiers.get("paper_candidate_id") or ""),
                gaia_source_id=str(identifiers.get("gaia_source_id") or ""),
                method_steps=list(method_steps),
                candidate=compact_candidate,
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


def _gaia_canonical_sort_key(contribution: Contribution) -> tuple[int, tuple[str, str, str, str]]:
    parsed = parse_gaia_source_id(contribution.gaia_source_id)
    if parsed is None:
        release_priority = 3
    elif parsed.release == "DR3":
        release_priority = 0
    elif parsed.release == "EDR3":
        release_priority = 1
    else:
        release_priority = 2
    return (release_priority, _source_sort_key(contribution))


def _canonical_gaia_contribution(obj: CatalogObject) -> Contribution | None:
    ordered = sorted(obj.contributions, key=_source_sort_key)
    gaia_contributions = [item for item in ordered if item.gaia_source_id.strip()]
    if gaia_contributions:
        return sorted(gaia_contributions, key=_gaia_canonical_sort_key)[0]
    return None


def _canonical_for_object(obj: CatalogObject) -> tuple[str, str, Contribution]:
    ordered = sorted(obj.contributions, key=_source_sort_key)
    gaia_contribution = _canonical_gaia_contribution(obj)
    if gaia_contribution is not None:
        return "gaia_source_id", gaia_contribution.gaia_source_id, gaia_contribution
    for contribution in ordered:
        if not _is_weak_identifier(contribution.paper_candidate_id):
            return "paper_candidate_id", contribution.paper_candidate_id, contribution
    for contribution in ordered:
        coordinate_id = _coordinate_identifier(contribution.coordinate)
        if coordinate_id:
            return "coordinate", coordinate_id, contribution
    contribution = ordered[0]
    return "record_id", contribution.record_id, contribution


def _object_id_base_for_object(obj: CatalogObject) -> str:
    gaia_contribution = _canonical_gaia_contribution(obj)
    if gaia_contribution is not None:
        parsed = parse_gaia_source_id(gaia_contribution.gaia_source_id)
        gaia_value = parsed.object_value if parsed is not None else gaia_contribution.gaia_source_id
        return safe_slug(gaia_value)

    canonical_kind, canonical_value, _ = _canonical_for_object(obj)
    if canonical_kind == "coordinate":
        return canonical_value
    if canonical_kind == "record_id":
        return f"src_{safe_slug(canonical_value)}"
    return safe_slug(canonical_value)


def _assign_object_ids(objects: list[CatalogObject]) -> list[tuple[CatalogObject, str]]:
    bases = [_object_id_base_for_object(obj) for obj in objects]
    base_counts: dict[str, int] = {}
    for base in bases:
        base_counts[base] = base_counts.get(base, 0) + 1
    assigned: list[tuple[CatalogObject, str]] = []
    for obj, base in zip(objects, bases, strict=True):
        if base_counts[base] == 1:
            candidate = base
        else:
            suffix = safe_slug(sorted(obj.contributions, key=_source_sort_key)[0].record_id)
            candidate = f"{base}__{suffix}"
        serial = 2
        used = {object_id for _, object_id in assigned}
        while candidate in used:
            suffix = safe_slug(sorted(obj.contributions, key=_source_sort_key)[0].record_id)
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
            candidates.append({"source": source_id, **contribution.candidate})

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
                "external_enrichment": disabled_enrichment(),
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
    enrichment_warnings: list[dict[str, Any]] = []
    enrichment_status_counts: dict[str, int] = {}
    candidates_dir = catalog_dir / CANDIDATES_DIRNAME
    for record in object_records:
        sources = record.get("sources") if isinstance(record.get("sources"), list) else []
        source_items = [item for item in sources if isinstance(item, dict)]
        gaia_source_ids = _unique_values([str(item.get("gaia_source_id") or "") for item in source_items])
        paper_candidate_ids = _unique_values([str(item.get("paper_candidate_id") or "") for item in source_items])
        object_id = str(record.get("object_id") or "")
        object_warnings = (record.get("merge") or {}).get("warnings") if isinstance(record.get("merge"), dict) else []
        object_warning_items = [item for item in object_warnings if isinstance(item, dict)]
        enrichment = record.get("external_enrichment") if isinstance(record.get("external_enrichment"), dict) else {}
        enrichment_status = str(enrichment.get("status") or "missing")
        enrichment_status_counts[enrichment_status] = enrichment_status_counts.get(enrichment_status, 0) + 1
        enrichment_warning_items = [
            item for item in enrichment.get("warnings") or [] if isinstance(item, dict)
        ]
        for warning in object_warning_items:
            warning_with_object = {"object_id": object_id}
            warning_with_object.update(warning)
            warnings.append(warning_with_object)
        for warning in enrichment_warning_items:
            warning_with_object = {"object_id": object_id}
            warning_with_object.update(warning)
            enrichment_warnings.append(warning_with_object)
        objects.append(
            {
                "object_id": object_id,
                "canonical_identifier": record.get("canonical_identifier") or {},
                "object_json_path": relative_path(candidates_dir / f"{object_id}.json", workspace=workspace),
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
                "enrichment_status": enrichment_status,
                "enrichment_warning_count": len(enrichment_warning_items),
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
        "enrichment_status_counts": enrichment_status_counts,
        "objects_enriched_count": enrichment_status_counts.get("success", 0) + enrichment_status_counts.get("partial", 0),
        "enrichment_warning_count": len(enrichment_warnings),
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
        "enrichment_warnings": enrichment_warnings,
        "skipped": skipped,
    }


def _markdown_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|")


def render_hvs_candidate_catalog_index(record: dict[str, Any]) -> str:
    summary = record.get("summary") or {}
    objects = record.get("objects") or []
    warnings = record.get("warnings") or []
    enrichment_warnings = record.get("enrichment_warnings") or []

    lines = [
        "# HVS Candidate Object Catalog",
        "",
        f"- Generated at: {record.get('generated_at')}",
        f"- Objects: {summary.get('object_count', 0)}",
        f"- Sources: {summary.get('source_count', 0)}",
        f"- Candidate records: {summary.get('candidate_count', 0)}",
        f"- Objects with Gaia source IDs: {summary.get('objects_with_gaia_count', 0)}",
        f"- Warnings: {summary.get('warning_count', 0)}",
        f"- Objects enriched: {summary.get('objects_enriched_count', 0)}",
        f"- Enrichment warnings: {summary.get('enrichment_warning_count', 0)}",
        f"- Skipped malformed inputs: {summary.get('skipped_count', 0)}",
    ]

    enrichment_status_counts = summary.get("enrichment_status_counts") if isinstance(summary.get("enrichment_status_counts"), dict) else {}
    if enrichment_status_counts:
        lines.append(
            "- Enrichment statuses: "
            + ", ".join(f"{key}={value}" for key, value in sorted(enrichment_status_counts.items()))
        )

    if objects:
        lines.extend(["", "## Objects", ""])
        lines.append("| Object | Canonical identifier | Sources | Gaia source IDs | Paper IDs | Warnings | Enrichment | JSON |")
        lines.append("| --- | --- | ---: | --- | --- | ---: | --- | --- |")
        for item in objects:
            canonical = item.get("canonical_identifier") if isinstance(item.get("canonical_identifier"), dict) else {}
            canonical_value = canonical.get("value") or item.get("object_id") or ""
            object_link = f"[JSON]({item.get('object_json_path')})" if item.get("object_json_path") else ""
            lines.append(
                f"| {_markdown_cell(item.get('object_id'))} | {_markdown_cell(canonical_value)} | "
                f"{item.get('source_count', 0)} | {_markdown_cell(', '.join(item.get('gaia_source_ids') or [])) or '-'} | "
                f"{_markdown_cell(', '.join(item.get('paper_candidate_ids') or [])) or '-'} | "
                f"{item.get('warning_count', 0)} | {_markdown_cell(item.get('enrichment_status')) or '-'} "
                f"({item.get('enrichment_warning_count', 0)}) | {object_link} |"
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

    if enrichment_warnings:
        lines.extend(["", "## Enrichment Warnings", ""])
        lines.append("| Object | Type | Message |")
        lines.append("| --- | --- | --- |")
        for warning in enrichment_warnings:
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
    candidate_paths = list((catalog_dir / CANDIDATES_DIRNAME).glob("*.json"))
    legacy_paths = list(catalog_dir.glob("*.json"))
    for path in sorted([*candidate_paths, *legacy_paths]):
        if path.name == INDEX_JSON_FILENAME or path.name in LEGACY_INDEX_JSON_FILENAMES:
            continue
        try:
            payload = read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("schema_version") in READABLE_OBJECT_SCHEMA_VERSIONS:
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
        compact_candidate = simplify_candidate(candidate)
        compact_candidate["identifiers"] = {
            "record_id": str(identifiers.get("record_id") or source_record.get("record_id") or ""),
            "paper_candidate_id": str(
                identifiers.get("paper_candidate_id") or source_record.get("paper_candidate_id") or ""
            ),
            "gaia_source_id": str(identifiers.get("gaia_source_id") or source_record.get("gaia_source_id") or ""),
        }
        if isinstance(candidate.get("candidate_context"), dict):
            compact_candidate["candidate_context"] = dict(candidate["candidate_context"])
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
                candidate=compact_candidate,
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
        if record.get("schema_version") not in READABLE_OBJECT_SCHEMA_VERSIONS:
            continue
        contributions.extend(_contributions_from_catalog_object(record))
    return contributions, skipped


def _record_paths(object_records: list[dict[str, Any]], catalog_dir: Path) -> list[Path]:
    candidates_dir = catalog_dir / CANDIDATES_DIRNAME
    return [candidates_dir / f"{record.get('object_id')}.json" for record in object_records]


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
    (catalog_dir / CANDIDATES_DIRNAME).mkdir(parents=True, exist_ok=True)
    for path in stale_paths:
        path.unlink(missing_ok=True)
    for record in object_records:
        write_json(catalog_dir / CANDIDATES_DIRNAME / f"{record.get('object_id')}.json", record)
    write_json(json_path, index_record)
    markdown_path.write_text(render_hvs_candidate_catalog_index(index_record), encoding="utf-8")
    for filename in LEGACY_INDEX_JSON_FILENAMES + LEGACY_INDEX_MARKDOWN_FILENAMES:
        (catalog_dir / filename).unlink(missing_ok=True)
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
    enrichment_mode: str,
    enrichment_clients: EnrichmentClients | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    generated_at = datetime.now().isoformat(timespec="seconds")
    catalog_objects = merge_contributions(contributions)
    object_records = object_records_from_catalog_objects(catalog_objects, generated_at=generated_at)
    object_records = enrich_object_records(
        object_records,
        mode=enrichment_mode,
        clients=enrichment_clients,
        queried_at=generated_at,
    )
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
    enrichment_mode: str = "off",
    enrichment_clients: EnrichmentClients | None = None,
) -> dict[str, Any]:
    """Build object-level catalog records from every paper-level candidate JSON."""
    if enrichment_mode not in ENRICHMENT_MODES:
        raise ValueError(f"unknown enrichment mode: {enrichment_mode}")
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
        enrichment_mode=enrichment_mode,
        enrichment_clients=enrichment_clients,
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
    enrichment_mode: str = "off",
    enrichment_clients: EnrichmentClients | None = None,
) -> dict[str, Any]:
    workspace = workspace or literature_dir.parent
    result = rebuild_hvs_candidate_catalog(
        literature_dir,
        catalog_dir,
        workspace=workspace,
        enrichment_mode=enrichment_mode,
        enrichment_clients=enrichment_clients,
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


def update_hvs_candidate_catalog(
    candidate_json_path: Path,
    catalog_dir: Path,
    *,
    literature_dir: Path | None = None,
    workspace: Path | None = None,
    enrichment_mode: str = "off",
    enrichment_clients: EnrichmentClients | None = None,
) -> dict[str, Any]:
    """Merge one paper-level candidate JSON into the existing object catalog."""
    if enrichment_mode not in ENRICHMENT_MODES:
        raise ValueError(f"unknown enrichment mode: {enrichment_mode}")
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
        enrichment_mode=enrichment_mode,
        enrichment_clients=enrichment_clients,
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
    enrichment_mode: str = "off",
    enrichment_clients: EnrichmentClients | None = None,
) -> dict[str, Any]:
    workspace = workspace or (literature_dir.parent if literature_dir is not None else catalog_dir.parent)
    result = update_hvs_candidate_catalog(
        candidate_json_path,
        catalog_dir,
        literature_dir=literature_dir,
        workspace=workspace,
        enrichment_mode=enrichment_mode,
        enrichment_clients=enrichment_clients,
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
