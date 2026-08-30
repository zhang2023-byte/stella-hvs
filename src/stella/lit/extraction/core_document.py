"""Build the immutable contribution-first HVS artifact.

The runtime ``paper_result.json`` remains the detailed operational record.
This module deterministically derives the maintained
``literature_hvs_contributions`` v2 document from it. A trusted roster
contribution is never removed because its quantity request failed: it
remains an L1 contribution with an empty quantities list and an explicit
failure record. Hydration detail (resolved text, source hashes, cell
headers) stays in the operational artifacts; the canonical document carries
strict locator shapes only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from stella.lit.extraction.finalize import (
    QUANTITY_EXTRACTION_COMPLETE,
    QUANTITY_EXTRACTION_FAILED,
    PAPER_COMPLETE,
    PAPER_FAILED,
    PAPER_PARTIAL,
)
from stella.lit.extraction.roster_stage import _atomic_write_json
from stella.schema_registry import schema_ref

_HYDRATION_KEYS = frozenset(
    {
        "resolved_text",
        "source_sha256",
        "quantity_raw_value",
        "column_header",
        "cell_raw_value",
    }
)


def _strip_hydration(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_hydration(item)
            for key, item in value.items()
            if key not in _HYDRATION_KEYS
        }
    if isinstance(value, list):
        return [_strip_hydration(item) for item in value]
    return value


def _object_contribution(
    roster_contribution: dict[str, Any],
    entry: dict[str, Any] | None,
) -> dict[str, Any]:
    record_id = roster_contribution["record_id"]
    identifiers = roster_contribution.get("identifiers") or []
    quantity_status = (entry or {}).get("status") or QUANTITY_EXTRACTION_FAILED
    operational_failure = (entry or {}).get("failure") or {}
    canonical_failure = (
        None
        if quantity_status == QUANTITY_EXTRACTION_COMPLETE
        else {
            "code": operational_failure.get("code") or "quantity_result_unavailable",
            "detail": operational_failure.get("detail")
            or "no trustworthy quantity result was delivered",
        }
    )
    return {
        "record_id": record_id,
        "identifiers": [
            {
                "value": item["value"],
                "evidence": _strip_hydration(item.get("source_refs") or []),
            }
            for item in identifiers
            if item.get("value")
        ],
        "contribution_type": roster_contribution["contribution_type"],
        "contribution_summary": roster_contribution["contribution_summary"],
        "contribution_evidence": _strip_hydration(
            roster_contribution.get("contribution_evidence") or []
        ),
        "paper_boundness": _strip_hydration(
            roster_contribution.get("paper_boundness") or {}
        ),
        "quantity_extraction_status": quantity_status,
        "quantities": _strip_hydration((entry or {}).get("quantities") or []),
        "failure": canonical_failure,
    }


def build_contribution_document(
    paper_result: dict[str, Any],
    *,
    method_fingerprint: str = "",
    component_hashes: dict[str, str] | None = None,
    paper_context_sha256: str = "",
) -> dict[str, Any]:
    """Build one current contribution document without changing scientific content."""

    paper = paper_result.get("paper") or {}
    roster = paper_result.get("roster") or {}
    roster_contributions = roster.get("object_contributions") or []
    result_entries = {
        item["record_id"]: item
        for item in paper_result.get("object_quantities") or []
    }

    object_contributions = [
        _object_contribution(item, result_entries.get(item["record_id"]))
        for item in roster_contributions
    ]

    status = paper_result.get("status") or PAPER_FAILED
    if status not in (PAPER_COMPLETE, PAPER_PARTIAL, PAPER_FAILED):
        status = PAPER_FAILED
    return {
        "schema": schema_ref("literature_hvs_contributions"),
        "generated_at": paper_result.get("generated_at"),
        "paper": {"arxiv_id": paper.get("arxiv_id")},
        "inputs": {
            "source_run_id": paper_result.get("run_id"),
            "paper_context_sha256": paper_context_sha256,
        },
        "production": {
            "producer": "hvs_contribution_extraction",
            "method_fingerprint": method_fingerprint,
            "component_hashes": component_hashes or {},
        },
        "extraction": {
            "status": status,
            "roster_status": paper_result.get("roster_status"),
        },
        "reviewed_exclusions": [
            {
                "reason": item.get("reason") or "",
                "evidence": _strip_hydration(item.get("source_refs") or []),
            }
            for item in roster.get("reviewed_exclusions") or []
        ],
        "object_contributions": object_contributions,
    }


def write_contribution_document(
    paper_result_path: Path,
    *,
    method_fingerprint: str = "",
    component_hashes: dict[str, str] | None = None,
    paper_context_sha256: str = "",
) -> dict[str, Any]:
    """Write the current document beside its operational paper result."""

    result = json.loads(paper_result_path.read_text(encoding="utf-8"))
    document = build_contribution_document(
        result,
        method_fingerprint=method_fingerprint,
        component_hashes=component_hashes,
        paper_context_sha256=paper_context_sha256,
    )
    _atomic_write_json(
        paper_result_path.with_name("literature_hvs_contributions.json"), document
    )
    return document
