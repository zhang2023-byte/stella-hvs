"""Shared mechanical normalization for Method B/C extraction outputs.

This is the only deterministic post-processing applied to model-generated
candidate documents, and it is deliberately restricted to unambiguous
representation cleanup: sexagesimal coordinate punctuation under the
model-declared ``coordinate_format``. It performs no scientific inference.

Candidate membership, ordered ``record_id`` anchors, scientific values, units,
limit kinds, inclusion decisions, and citation selection (``bibkey`` /
``bibliography_refs``) are owned by the model and the independent reviewer.
The Method B scheduler separately restores the remaining exact identifier
payload from the already sealed roster after every ordered record anchor
matches; that propagation makes no scientific choice. Defects in model-owned
fields are returned through the validation/repair loop or reported as delivery
limitations; code must not decide which citation or scientific claim is
correct.

Both runners (``extraction_run`` method B and ``agentic_run`` method C) call
``normalize_mechanical_representation`` so the boundary stays identical and
idempotent across methods.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from astropy.table import Table

_COLON_HMS_RE = re.compile(
    r"^\s*(\d{1,2})\s*:\s*(\d{1,2})\s*:\s*(\d+(?:\.\d*)?)\s*$"
)
_COLON_DMS_RE = re.compile(
    r"^\s*([+-]?)\s*(\d{1,2})\s*:\s*(\d{1,2})\s*:\s*(\d+(?:\.\d*)?)\s*$"
)


def canonical_ecsv_column(path: Path, display_or_column: str) -> str | None:
    """Resolve an exact display label only when it maps to one real column."""

    try:
        table = Table.read(path, format="ascii.ecsv")
    except (OSError, ValueError):
        return None
    if display_or_column in table.colnames:
        return str(display_or_column)
    matches = [
        str(name)
        for name in table.colnames
        if str(table[name].description or "") == display_or_column
    ]
    return matches[0] if len(matches) == 1 else None


def _normalize_ecsv_source_refs(
    value: Any,
    *,
    workspace: Path,
    allowed_paths: set[str],
    path: str = "",
) -> list[str]:
    changes: list[str] = []
    if isinstance(value, dict):
        if value.get("kind") == "ecsv_cell":
            relative = str(value.get("path") or "")
            column = str(value.get("column") or "")
            if relative in allowed_paths and column:
                canonical = canonical_ecsv_column(workspace / relative, column)
                if canonical is not None and canonical != column:
                    value["column"] = canonical
                    changes.append(f"{path}.column".lstrip("."))
        for key, nested in value.items():
            changes.extend(
                _normalize_ecsv_source_refs(
                    nested,
                    workspace=workspace,
                    allowed_paths=allowed_paths,
                    path=f"{path}.{key}" if path else str(key),
                )
            )
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            changes.extend(
                _normalize_ecsv_source_refs(
                    nested,
                    workspace=workspace,
                    allowed_paths=allowed_paths,
                    path=f"{path}[{index}]",
                )
            )
    return changes


def normalize_mechanical_representation(
    document: dict[str, Any], *, workspace: Path | None = None
) -> list[str]:
    """Canonicalize representation spelling; return the changed value paths.

    Only coordinate punctuation is rewritten: a colon-separated sexagesimal
    string becomes the canonical h/m/s (or d/m/s) spelling, and only when the
    model itself declared the matching ``coordinate_format``. Everything else
    is left byte-identical.
    """

    changes: list[str] = []
    if workspace is not None:
        inputs = document.get("inputs")
        ecsv_paths = inputs.get("ecsv_paths") if isinstance(inputs, dict) else []
        allowed_paths = {
            str(item) for item in ecsv_paths or [] if isinstance(item, str)
        }
        changes.extend(
            _normalize_ecsv_source_refs(
                document,
                workspace=workspace,
                allowed_paths=allowed_paths,
            )
        )
    candidates = document.get("candidates")
    if not isinstance(candidates, list):
        return changes
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            continue
        observed = (
            ((candidate.get("core") or {}).get("observed_phase_space") or {})
            if isinstance(candidate.get("core"), dict)
            else {}
        )
        if not isinstance(observed, dict):
            continue
        for field in ("ra", "dec"):
            quantity = observed.get(field)
            if not isinstance(quantity, dict):
                continue
            value = str(quantity.get("value") or "")
            coordinate_format = str(quantity.get("coordinate_format") or "")
            normalized = ""
            if coordinate_format == "sexagesimal_hms":
                match = _COLON_HMS_RE.fullmatch(value)
                if match:
                    normalized = (
                        f"{match.group(1).zfill(2)}h{match.group(2).zfill(2)}m"
                        f"{match.group(3)}s"
                    )
            elif coordinate_format == "sexagesimal_dms":
                match = _COLON_DMS_RE.fullmatch(value)
                if match:
                    normalized = (
                        f"{match.group(1)}{match.group(2).zfill(2)}d"
                        f"{match.group(3).zfill(2)}m{match.group(4)}s"
                    )
            if normalized and normalized != value:
                quantity["value"] = normalized
                changes.append(
                    "candidates["
                    f"{index}].core.observed_phase_space.{field}.value"
                )
    return changes
