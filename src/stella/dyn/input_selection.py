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
import re
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
DYNAMICS_RADIAL_VELOCITY_FIELD = "observed_phase_space.radial_velocity"
DYNAMICS_CONTRIBUTION_ASTROMETRY_FIELDS = (
    "observed_phase_space.parallax",
    "observed_phase_space.proper_motion_ra",
    "observed_phase_space.proper_motion_dec",
)
DYNAMICS_SELECTION_FIELDS = (
    DYNAMICS_RADIAL_VELOCITY_FIELD,
    *DYNAMICS_CONTRIBUTION_ASTROMETRY_FIELDS,
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class InputSelectionError(ValueError):
    """One structured input-selection failure (fail closed)."""


def selected_value_fingerprint(value: dict[str, Any]) -> str:
    """Fingerprint the complete canonical value, including condition/provenance."""

    canonical = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _value_snapshot(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.get(key)
        for key in _VALUE_COMPONENTS
        if value.get(key) is not None
    }


def _resolve_contribution_path(workspace: Path, contribution_path: str) -> Path:
    relative = Path(contribution_path)
    if relative.is_absolute():
        raise InputSelectionError("contribution_path must be workspace-relative")
    workspace_root = Path(workspace).resolve()
    path = (workspace_root / relative).resolve()
    literature_root = (workspace_root / "literature").resolve()
    if not path.is_relative_to(literature_root):
        raise InputSelectionError(
            "contribution_path must stay under the workspace literature directory"
        )
    return path


def build_input_selection(
    *,
    workspace: Path,
    object_id: str,
    gaia_identity: str,
    astrometry_source: str,
    selected_values: dict[str, dict[str, Any]],
    contribution_path: str,
    record_id: str,
    selector: str,
    selected_at: str,
    rationale: str,
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build and self-validate one explicit per-field dynamics selection."""

    if astrometry_source not in ("gaia_dr3", "contribution"):
        raise InputSelectionError(
            "astrometry_source must be gaia_dr3 or contribution"
        )
    expected_fields = {DYNAMICS_RADIAL_VELOCITY_FIELD}
    if astrometry_source == "contribution":
        expected_fields.update(DYNAMICS_CONTRIBUTION_ASTROMETRY_FIELDS)
    if set(selected_values) != expected_fields:
        raise InputSelectionError(
            "selected_values must contain exactly " + ", ".join(sorted(expected_fields))
        )
    path = _resolve_contribution_path(workspace, contribution_path)
    if not path.is_file():
        raise InputSelectionError(f"selected contribution artifact is missing: {path}")
    selection = {
        "schema": schema_ref("hvs_dynamics.input_selection"),
        "object_id": object_id,
        "selected": {
            "gaia_identity": gaia_identity,
            "astrometry_source": astrometry_source,
            "values": {
                field: {
                    "snapshot": _value_snapshot(value),
                    "fingerprint": selected_value_fingerprint(value),
                }
                for field, value in sorted(selected_values.items())
            },
            "contribution_path": contribution_path,
            "record_id": record_id,
        },
        "selector": selector,
        "selected_at": selected_at,
        "rationale": rationale,
        "evidence": evidence or [],
        "source_artifact_sha256": _file_sha256(path),
    }
    validate_input_selection(selection, workspace=workspace, expected_object_id=object_id)
    return selection


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
    for key in ("object_id", "selector", "selected_at", "rationale"):
        if not str(selection.get(key) or "").strip():
            raise InputSelectionError(f"{key} is required")
    selected = selection.get("selected") or {}
    for key in ("gaia_identity", "contribution_path", "record_id"):
        if not str(selected.get(key) or "").strip():
            raise InputSelectionError(f"selected.{key} is required")
    contribution_path = selected.get("contribution_path") or ""
    path = _resolve_contribution_path(workspace, contribution_path)
    if not path.is_file():
        raise InputSelectionError(f"selected contribution artifact is missing: {path}")
    artifact_sha = _file_sha256(path)
    selected_hash = str(selection.get("source_artifact_sha256") or "")
    if not _SHA256_RE.fullmatch(selected_hash):
        raise InputSelectionError("source_artifact_sha256 is required")
    if selected_hash != artifact_sha:
        raise InputSelectionError(
            "stale selection: the contribution artifact changed after the selection was made"
        )
    try:
        contribution_document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputSelectionError(f"unreadable contribution artifact: {exc}") from exc
    try:
        from stella.lit.hvs_contribution_models import (
            validate_literature_hvs_contributions_document,
        )

        validate_literature_hvs_contributions_document(contribution_document)
    except Exception as exc:
        raise InputSelectionError(
            f"selected contribution artifact is invalid: {exc}"
        ) from exc
    selected_values = selected.get("values")
    if not isinstance(selected_values, dict):
        raise InputSelectionError("selected.values is required")
    expected_fields = {DYNAMICS_RADIAL_VELOCITY_FIELD}
    if selected.get("astrometry_source") == "contribution":
        expected_fields.update(DYNAMICS_CONTRIBUTION_ASTROMETRY_FIELDS)
    elif selected.get("astrometry_source") != "gaia_dr3":
        raise InputSelectionError("invalid astrometry_source")
    if set(selected_values) != expected_fields:
        raise InputSelectionError(
            "selection does not explicitly identify every required dynamics field"
        )
    for field, chosen in selected_values.items():
        if field not in HVS_CONTRIBUTION_MEASUREMENT_FIELDS:
            raise InputSelectionError(f"unknown selected field: {field}")
        if not isinstance(chosen, dict):
            raise InputSelectionError(f"selection for {field} must be an object")
        values = _find_contribution_values(
            contribution_document, selected.get("record_id") or "", field
        )
        if not values:
            raise InputSelectionError(
                "stale selection: the selected record/field no longer exists "
                "in the contribution artifact"
            )
        matching = [
            value
            for value in values
            if selected_value_fingerprint(value) == chosen.get("fingerprint")
        ]
        if len(matching) != 1 or chosen.get("snapshot") != _value_snapshot(matching[0]):
            raise InputSelectionError(
                "stale selection: the selected value fingerprint/snapshot no "
                f"longer uniquely matches field {field}"
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
