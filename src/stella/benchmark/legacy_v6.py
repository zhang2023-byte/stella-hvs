"""Read-only support for historical V6 artifacts and scorecards.

The V6 production writer, network-debug paths, supplements, and release
gates are retired. What remains is the demonstrable historical read surface:
loading and validating already-persisted ``literature_hvs_candidates`` (v3)
documents and benchmark scorecards for display. Nothing in this module
writes or executes V6 extraction.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from stella.schema_registry import model_for, require_schema


def read_v6_candidates_document(path: Path) -> dict[str, Any]:
    """Load and validate a persisted V6 candidates document (read-only)."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    name, version = require_schema(payload, "literature_hvs_candidates")
    model = model_for(name, version)
    model.model_validate(payload)
    return payload


def read_v6_scorecard(path: Path) -> dict[str, Any]:
    """Load a persisted benchmark scorecard without any reseal or rescore."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    require_schema(payload, "benchmark.scorecard")
    return payload


def v6_paper_summary(document: dict[str, Any]) -> dict[str, Any]:
    """Display summary of one historical V6 paper result."""

    return {
        "schema": document.get("schema"),
        "paper": (document.get("paper") or {}).get("arxiv_id"),
        "status": (document.get("extraction") or {}).get("status"),
    }
