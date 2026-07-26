"""Build the immutable core-first HVS candidate artifact.

The runtime ``paper_result.json`` remains the detailed operational record.  This
module deterministically derives the maintained ``literature_hvs_candidates``
v3 document from it.  A trusted roster candidate is never removed because its
field request failed: it remains an L1 candidate with a null 19-field core and
an explicit failure record.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from stella.hvs_extraction.field_schema import CORE_GROUPS
from stella.hvs_extraction.roster_stage import _atomic_write_json
from stella.schema_registry import schema_ref

FIELDS_COMPLETE = "fields_complete"
FIELD_EXTRACTION_FAILED = "field_extraction_failed"


def empty_core() -> dict[str, dict[str, None]]:
    """Return the exact nullable 19-field core skeleton."""

    return {
        group: {field: None for field in fields}
        for group, fields in CORE_GROUPS.items()
    }


def _gaia_identifier(identifiers: list[dict[str, Any]]) -> str:
    for item in identifiers:
        recognition = item.get("recognition") or {}
        if recognition.get("kind") == "gaia":
            return (
                f"Gaia {recognition.get('release', '')} "
                f"{recognition.get('source_id', '')}"
            ).strip()
    return ""


def _candidate_identifiers(
    roster_candidate: dict[str, Any], record_id: str
) -> dict[str, Any]:
    identifiers = roster_candidate.get("identifiers") or []
    return {
        "record_id": record_id,
        "paper_candidate_id": roster_candidate.get("display_name") or record_id,
        "gaia_source_id": _gaia_identifier(identifiers),
        "all": [
            {
                "value": item["value"],
                "source_refs": item.get("source_refs") or [],
            }
            for item in identifiers
            if item.get("value")
        ],
    }


def _candidate_origin(entry: dict[str, Any]) -> dict[str, Any] | None:
    fields = entry.get("fields") or {}
    origin = fields.get("candidate_origin")
    if not origin:
        return None
    bibliography = entry.get("bibliography") or {}
    return {
        "origin_type": origin.get("origin_type"),
        "bibkey": origin.get("bibkey"),
        "paper_reassesses_unbound_status": bool(
            bibliography.get("paper_reassesses_unbound_status")
        ),
        "evidence": origin.get("evidence") or [],
        "citation": bibliography.get("resolution"),
    }


def build_core_document(
    paper_result: dict[str, Any],
    *,
    campaign_id: str,
    method_fingerprint: str = "",
    component_hashes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build one v3 core document without changing scientific content."""

    paper = paper_result.get("paper") or {}
    roster = paper_result.get("roster") or {}
    roster_candidates = {
        item["record_id"]: item for item in roster.get("candidates") or []
    }
    result_entries = {
        item["record_id"]: item for item in paper_result.get("candidates") or []
    }

    candidates: list[dict[str, Any]] = []
    for record_id, roster_candidate in roster_candidates.items():
        entry = result_entries.get(record_id) or {
            "record_id": record_id,
            "display_name": roster_candidate.get("display_name"),
            "status": FIELD_EXTRACTION_FAILED,
            "failure": {
                "code": "missing_candidate_result",
                "detail": "trusted roster candidate has no field-stage result",
            },
        }
        fields = entry.get("fields") or {}
        field_status = entry.get("status") or FIELD_EXTRACTION_FAILED
        candidates.append(
            {
                "record_id": record_id,
                "display_name": entry.get("display_name")
                or roster_candidate.get("display_name")
                or record_id,
                "identifiers": _candidate_identifiers(roster_candidate, record_id),
                "qualification": roster_candidate.get("qualification"),
                "field_status": field_status,
                "candidate_origin": _candidate_origin(entry),
                "core": (
                    fields.get("core")
                    if field_status == FIELDS_COMPLETE and fields.get("core")
                    else empty_core()
                ),
                "failure": (
                    None
                    if field_status == FIELDS_COMPLETE
                    else entry.get("failure")
                    or {
                        "code": "field_result_unavailable",
                        "detail": "no trustworthy core-field result was delivered",
                    }
                ),
            }
        )

    status = paper_result.get("status") or "failed"
    return {
        "schema": schema_ref("literature_hvs_candidates", 3),
        "generated_at": paper_result.get("generated_at"),
        "paper": {"arxiv_id": paper.get("arxiv_id")},
        "inputs": {
            "campaign_id": campaign_id,
            "source_run_id": paper_result.get("run_id"),
        },
        "production": {
            "producer": "hvs_candidate_extraction",
            "method_fingerprint": method_fingerprint,
            "component_hashes": component_hashes or {},
        },
        "extraction": {
            "status": status,
            "roster_status": paper_result.get("roster_status"),
        },
        "roster": {
            "status": (roster.get("status") if roster else None),
            "reviewed_groups": roster.get("reviewed_exclusions") or [],
        },
        "candidates": candidates,
    }


def write_core_document(
    paper_result_path: Path,
    *,
    campaign_id: str,
    method_fingerprint: str = "",
    component_hashes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Write the v3 document beside its operational paper result."""

    result = json.loads(paper_result_path.read_text(encoding="utf-8"))
    document = build_core_document(
        result,
        campaign_id=campaign_id,
        method_fingerprint=method_fingerprint,
        component_hashes=component_hashes,
    )
    _atomic_write_json(
        paper_result_path.with_name("literature_hvs_candidates.json"), document
    )
    return document
