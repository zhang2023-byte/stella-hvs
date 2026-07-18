"""Shared mechanical normalization for Method B/C extraction outputs.

This is the only deterministic post-processing applied to model-generated
candidate documents, and it is deliberately restricted to unambiguous
representation cleanup: sexagesimal coordinate punctuation under the
model-declared ``coordinate_format``. It performs no scientific inference.

Candidate membership, record identifiers, scientific values, units, limit
kinds, inclusion decisions, and citation selection (``bibkey`` /
``bibliography_refs``) are owned by the model and the independent reviewer.
Defects in them are returned to the model/reviewer through the
validation/repair loop or reported as delivery limitations; code must not
decide which citation or scientific claim is correct.

Both runners (``extraction_run`` method B and ``agentic_run`` method C) call
``normalize_mechanical_representation`` so the boundary stays identical and
idempotent across methods.
"""

from __future__ import annotations

import re
from typing import Any

_COLON_HMS_RE = re.compile(
    r"^\s*(\d{1,2})\s*:\s*(\d{1,2})\s*:\s*(\d+(?:\.\d*)?)\s*$"
)
_COLON_DMS_RE = re.compile(
    r"^\s*([+-]?)\s*(\d{1,2})\s*:\s*(\d{1,2})\s*:\s*(\d+(?:\.\d*)?)\s*$"
)


def normalize_mechanical_representation(document: dict[str, Any]) -> list[str]:
    """Canonicalize representation spelling; return the changed value paths.

    Only coordinate punctuation is rewritten: a colon-separated sexagesimal
    string becomes the canonical h/m/s (or d/m/s) spelling, and only when the
    model itself declared the matching ``coordinate_format``. Everything else
    is left byte-identical.
    """

    changes: list[str] = []
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
