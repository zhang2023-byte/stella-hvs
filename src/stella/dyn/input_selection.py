"""Explicit dynamics input selection for contribution catalogs.

A contribution catalog is an evidence timeline, not an input-selection
policy: code never chooses dynamics inputs from ``paper_preferred``, the
first or last value, the smallest uncertainty, or boundness. Dynamics for a
contribution-catalog object require a separate explicit
``hvs_dynamics.input_selection`` v1 record whose selected value snapshot and
source artifact hash are re-verified before any computation; a missing or
stale selection fails closed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from stella.lit.schema_specs import HVS_CONTRIBUTION_MEASUREMENT_FIELDS
from stella.schema_registry import schema_ref

_VALUE_COMPONENTS = (
    "value",
    "error",
    "lower_error",
    "upper_error",
    "unit",
    "limit_kind",
    "range_lower",
    "range_upper",
)


class InputSelectionError(ValueError):
    """One structured input-selection failure (fail closed)."""


def selected_value_fingerprint(value: dict[str, Any]) -> str:
    """Deterministic fingerprint over the selected value and its evidence."""

    evidence = []
    for item in value.get("direct_evidence") or []:
        source = item.get("source") or {}
        evidence.append(
            {
                "part": item.get("part"),
                "kind": source.get("kind"),
                "path": source.get("path"),
                "start_line": source.get("start_line"),
                "end_line": source.get("end_line"),
                "line": source.get("line"),
                "column": source.get("column"),
                "raw_value": source.get("raw_value"),
                "component_raw_value": source.get("component_raw_value"),
            }
        )
    payload = {
        "components": {key: value.get(key) for key in _VALUE_COMPONENTS},
        "evidence": evidence,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_input_selection(
    *,
    object_id: str,
    gaia_identity: str,
    astrometry_source: str,
    radial_velocity_snapshot: dict[str, Any],
    contribution_path: str,
    record_id: str,
    field: str,
    selector: str,
    selected_at: str,
    rationale: str,
    evidence: list[dict[str, Any]] | None = None,
    contribution_artifact: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one explicit selection record; the caller owns every choice."""

    if field not in HVS_CONTRIBUTION_MEASUREMENT_FIELDS:
        raise InputSelectionError(f"field {field!r} is not in the measurement vocabulary")
    if astrometry_source not in ("gaia_dr3", "contribution"):
        raise InputSelectionError(
            "astrometry_source must be gaia_dr3 or contribution"
        )
    artifact_hash = ""
    if contribution_artifact is not None:
        artifact_hash = hashlib.sha256(
            json.dumps(
                contribution_artifact, ensure_ascii=False, sort_keys=True
            ).encode("utf-8")
        ).hexdigest()
    return {
        "schema": schema_ref("hvs_dynamics.input_selection"),
        "object_id": object_id,
        "selected": {
            "gaia_identity": gaia_identity,
            "astrometry_source": astrometry_source,
            "radial_velocity": {
                key: radial_velocity_snapshot.get(key)
                for key in _VALUE_COMPONENTS
                if radial_velocity_snapshot.get(key) is not None
            },
            "contribution_path": contribution_path,
            "record_id": record_id,
            "field": field,
            "fingerprint": selected_value_fingerprint(radial_velocity_snapshot),
        },
        "selector": selector,
        "selected_at": selected_at,
        "rationale": rationale,
        "evidence": evidence or [],
        "source_artifact_sha256": artifact_hash,
    }


def _find_contribution_values(
    contribution_document: dict[str, Any], record_id: str, field: str
) -> list[dict[str, Any]]:
    for contribution in contribution_document.get("object_contributions") or []:
        if contribution.get("record_id") != record_id:
            continue
        for group in contribution.get("measurements") or []:
            if group.get("field") == field:
                return group.get("values") or []
    return []


def validate_input_selection(
    selection: dict[str, Any],
    *,
    workspace: Path,
    expected_object_id: str | None = None,
) -> dict[str, Any]:
    """Fail closed on a missing, mismatched, or stale selection.

    Returns the loaded contribution document when the selection verifies.
    """

    ref = selection.get("schema") or {}
    if ref.get("name") != "hvs_dynamics.input_selection" or ref.get("version") != 1:
        raise InputSelectionError("not an hvs_dynamics.input_selection v1 record")
    if expected_object_id is not None and selection.get("object_id") != expected_object_id:
        raise InputSelectionError(
            f"selection object_id {selection.get('object_id')!r} does not match {expected_object_id!r}"
        )
    selected = selection.get("selected") or {}
    contribution_path = selected.get("contribution_path") or ""
    path = Path(contribution_path)
    if not path.is_absolute():
        path = workspace / path
    if not path.is_file():
        raise InputSelectionError(f"selected contribution artifact is missing: {path}")
    artifact_sha = _file_sha256(path)
    if selection.get("source_artifact_sha256") and selection["source_artifact_sha256"] != artifact_sha:
        raise InputSelectionError(
            "stale selection: the contribution artifact changed after the selection was made"
        )
    try:
        contribution_document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputSelectionError(f"unreadable contribution artifact: {exc}") from exc
    values = _find_contribution_values(
        contribution_document, selected.get("record_id") or "", selected.get("field") or ""
    )
    if not values:
        raise InputSelectionError(
            "stale selection: the selected record/field no longer exists in the contribution artifact"
        )
    fingerprints = {selected_value_fingerprint(value) for value in values}
    if selected.get("fingerprint") not in fingerprints:
        raise InputSelectionError(
            "stale selection: the selected value fingerprint no longer matches any value of the field"
        )
    return contribution_document


def selection_for_object(selection_dir: Path, object_id: str) -> dict[str, Any]:
    path = Path(selection_dir) / f"{object_id}.json"
    if not path.is_file():
        raise InputSelectionError(
            f"missing explicit input selection for {object_id}: contribution-based "
            "dynamics never select inputs automatically"
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputSelectionError(f"unreadable selection for {object_id}: {exc}") from exc
