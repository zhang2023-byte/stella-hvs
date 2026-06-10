"""Scored-field registry shared by alignment, gold assembly, and metrics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

QUANTITY_SNAPSHOT_KEYS = ("value", "unit", "error", "lower_error", "upper_error", "raw_value")
COORDINATE_SNAPSHOT_KEYS = QUANTITY_SNAPSHOT_KEYS + ("coordinate_format",)


@dataclass(frozen=True)
class FieldSpec:
    path: str
    kind: str  # categorical | boolean | label_set | identifier | identifier_set | quantity | coordinate
    headline: bool = True


FIELD_SPECS: tuple[FieldSpec, ...] = (
    FieldSpec("identifiers.gaia_source_id", "identifier"),
    FieldSpec("identifiers.paper_candidate_id", "identifier"),
    FieldSpec("identifiers.all", "identifier_set"),
    FieldSpec("inclusion_assessment.paper_labels", "label_set"),
    FieldSpec("inclusion_assessment.galactic_bound_claim", "categorical"),
    FieldSpec("inclusion_assessment.inclusion_basis", "categorical"),
    FieldSpec("inclusion_assessment.extraction_confidence", "categorical", headline=False),
    FieldSpec("candidate_origin.origin_type", "categorical"),
    FieldSpec("candidate_origin.paper_reassesses_unbound_status", "boolean"),
    FieldSpec("candidate_origin.citation.bibkey", "identifier", headline=False),
    FieldSpec("candidate_origin.citation.arxiv_id", "identifier", headline=False),
    FieldSpec("candidate_origin.citation.bibcode", "identifier", headline=False),
    FieldSpec("core.observed_phase_space.ra", "coordinate"),
    FieldSpec("core.observed_phase_space.dec", "coordinate"),
    FieldSpec("core.observed_phase_space.distance", "quantity"),
    FieldSpec("core.observed_phase_space.parallax", "quantity"),
    FieldSpec("core.observed_phase_space.proper_motion_ra", "quantity"),
    FieldSpec("core.observed_phase_space.proper_motion_dec", "quantity"),
    FieldSpec("core.observed_phase_space.radial_velocity", "quantity"),
    FieldSpec("core.derived_kinematics.galactocentric_x", "quantity"),
    FieldSpec("core.derived_kinematics.galactocentric_y", "quantity"),
    FieldSpec("core.derived_kinematics.galactocentric_z", "quantity"),
    FieldSpec("core.derived_kinematics.galactocentric_vx", "quantity"),
    FieldSpec("core.derived_kinematics.galactocentric_vy", "quantity"),
    FieldSpec("core.derived_kinematics.galactocentric_vz", "quantity"),
    FieldSpec("core.derived_kinematics.tangential_velocity", "quantity"),
    FieldSpec("core.derived_kinematics.galactocentric_tangential_velocity", "quantity"),
    FieldSpec("core.derived_kinematics.total_velocity", "quantity"),
    FieldSpec("core.derived_kinematics.galactic_rest_frame_velocity", "quantity"),
    FieldSpec("core.bound_assessment.escape_velocity", "quantity"),
    FieldSpec("core.bound_assessment.escape_velocity_ratio", "quantity"),
    FieldSpec("core.bound_assessment.escape_margin", "quantity"),
    FieldSpec("core.bound_assessment.bound_probability", "quantity"),
    FieldSpec("core.bound_assessment.unbound_probability", "quantity"),
    FieldSpec("core.bound_assessment.bound_status_metric", "quantity"),
)


def get_by_path(candidate: dict[str, Any], path: str) -> Any:
    node: Any = candidate
    for part in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _normalize_number_text(text: str) -> str:
    """Make '499', '499.0', and '+499' compare equal without losing precision."""
    stripped = text.strip()
    if not stripped:
        return ""
    try:
        number = float(stripped)
    except ValueError:
        return stripped
    return repr(number)


def value_snapshot(spec: FieldSpec, raw: Any) -> Any:
    """A compact, comparable view of a field value; None when absent/empty."""
    if raw is None:
        return None
    if spec.kind in {"categorical", "identifier"}:
        text = str(raw).strip()
        return text or None
    if spec.kind == "boolean":
        return bool(raw)
    if spec.kind == "label_set":
        labels = sorted(str(item) for item in raw) if isinstance(raw, list) else []
        return labels or None
    if spec.kind == "identifier_set":
        values = (
            sorted(str(item.get("value") or "").strip() for item in raw if isinstance(item, dict))
            if isinstance(raw, list)
            else []
        )
        values = [value for value in values if value]
        return values or None
    if spec.kind in {"quantity", "coordinate"}:
        if not isinstance(raw, dict):
            return None
        keys = COORDINATE_SNAPSHOT_KEYS if spec.kind == "coordinate" else QUANTITY_SNAPSHOT_KEYS
        return {key: str(raw.get(key) or "") for key in keys}
    return raw


def _comparable(spec: FieldSpec, snapshot: Any) -> Any:
    if snapshot is None:
        return None
    if spec.kind in {"quantity", "coordinate"} and isinstance(snapshot, dict):
        comparable = dict(snapshot)
        comparable.pop("raw_value", None)
        for key in ("value", "error", "lower_error", "upper_error"):
            comparable[key] = _normalize_number_text(comparable.get(key, ""))
        comparable["unit"] = " ".join(comparable.get("unit", "").split())
        return tuple(sorted(comparable.items()))
    if isinstance(snapshot, list):
        return tuple(snapshot)
    return snapshot


def snapshots_agree(spec: FieldSpec, snapshots: list[Any]) -> bool:
    comparables = {repr(_comparable(spec, snapshot)) for snapshot in snapshots}
    return len(comparables) == 1


def evidence_refs(spec: FieldSpec, candidate: dict[str, Any]) -> list[dict[str, Any]]:
    """source_refs supporting a field value, for embedding into alignment."""
    raw = get_by_path(candidate, spec.path)
    if spec.kind in {"quantity", "coordinate"}:
        if isinstance(raw, dict):
            refs = raw.get("source_refs")
            return refs if isinstance(refs, list) else []
        return []
    if spec.kind == "identifier_set":
        refs: list[dict[str, Any]] = []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict) and isinstance(item.get("source_refs"), list):
                    refs.extend(item["source_refs"])
        return refs
    # Scalar fields are supported by their parent block's source_refs.
    parent_path = spec.path.rsplit(".", 1)[0]
    parent = get_by_path(candidate, parent_path)
    if isinstance(parent, dict):
        refs = parent.get("source_refs")
        if isinstance(refs, list):
            return refs
        # citation fields: fall back to bibliography refs
        refs = parent.get("bibliography_refs")
        if isinstance(refs, list):
            return refs
    return []
