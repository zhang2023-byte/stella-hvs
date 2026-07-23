"""Deterministic projection from scratch artifacts to the scorer's input shape.

The scratch artifact is not a ``literature_hvs_candidates`` v0.2 artifact
(D034); this adapter is a representation-only translation for development
evaluation. It never changes source choice or scientific meaning (D037/D038):
null components become the current scorer's empty-string representation,
``limit_kind`` ``none`` becomes the scorer's empty spelling, and uncertainty
components are preserved as strings even though the current scorer never
compares them (the confirmed D041 gap). Failed candidates stay out of the
projection — no trustworthy field judgment exists for them (D045).
"""

from __future__ import annotations

from typing import Any

from stella.benchmark.scratch.field_schema import CORE_GROUPS

FIELDS_COMPLETE = "fields_complete"
PAPER_FAILED = "failed"
PAPER_PARTIAL = "partial"


def _quantity_raw_value(quantity: dict[str, Any]) -> str:
    for item in quantity.get("direct_evidence") or []:
        if item.get("part") == "value":
            source = item.get("source") or {}
            return str(source.get("quantity_raw_value") or "")
    return ""


def project_quantity(quantity: dict[str, Any] | None, *, coordinate: bool) -> dict[str, Any]:
    """Translate one scratch quantity to the scorer's empty-string conventions."""

    if quantity is None:
        return {}
    projected = {
        "raw_value": _quantity_raw_value(quantity),
        "value": str(quantity.get("value") or ""),
        "error": str(quantity.get("error") or ""),
        "lower_error": str(quantity.get("lower_error") or ""),
        "upper_error": str(quantity.get("upper_error") or ""),
        "unit": str(quantity.get("unit") or ""),
        "limit_kind": ""
        if quantity.get("limit_kind") in (None, "", "none")
        else str(quantity["limit_kind"]),
        "range_lower": str(quantity.get("range_lower") or ""),
        "range_upper": str(quantity.get("range_upper") or ""),
    }
    if coordinate and quantity.get("coordinate_format"):
        projected["coordinate_format"] = quantity["coordinate_format"]
    return projected


def _canonical_gaia_identifier(identifiers: list[dict[str, Any]]) -> str:
    for item in identifiers:
        recognition = item.get("recognition") or {}
        if recognition.get("kind") == "gaia":
            return f"Gaia {recognition['release']} {recognition['source_id']}"
    return ""


def project_paper_result(result: dict[str, Any]) -> dict[str, Any]:
    """Project one scratch paper_result into a scorer-consumable AI document."""

    if result["status"] == PAPER_FAILED:
        return {"extraction": {"status": PAPER_FAILED}, "candidates": []}

    roster_candidates = {
        candidate["record_id"]: candidate
        for candidate in (result.get("roster") or {}).get("candidates") or []
    }
    candidates: list[dict[str, Any]] = []
    for entry in result.get("candidates") or []:
        if entry["status"] != FIELDS_COMPLETE:
            continue
        roster_candidate = roster_candidates.get(entry["record_id"], {})
        identifiers = roster_candidate.get("identifiers") or []
        fields = entry["fields"]
        core = fields["core"]
        projected_core: dict[str, Any] = {}
        for group, field_names in CORE_GROUPS.items():
            projected_core[group] = {
                field_name: project_quantity(
                    (core.get(group) or {}).get(field_name),
                    coordinate=field_name in ("ra", "dec"),
                )
                for field_name in field_names
            }
        # The scratch contract normalizes a reported percent to a 0-1
        # fraction at extraction time and preserves the printed percent as
        # direct evidence. The scorer's R7 heuristic divides by 100 again
        # whenever raw_value carries "%", so the percent-marked raw cannot
        # be propagated for probability fields; the scorer-visible raw is
        # the already-normalized value string instead.
        for field_name in ("bound_probability", "unbound_probability"):
            quantity = projected_core["bound_assessment"].get(field_name) or {}
            if "%" in str(quantity.get("raw_value") or ""):
                quantity["raw_value"] = quantity.get("value") or ""
        bibliography = entry.get("bibliography") or {}
        candidates.append(
            {
                "identifiers": {
                    "record_id": entry["record_id"],
                    "paper_candidate_id": entry.get("display_name")
                    or roster_candidate.get("display_name")
                    or "",
                    "gaia_source_id": _canonical_gaia_identifier(identifiers),
                    "all": [
                        {"value": item["value"]}
                        for item in identifiers
                        if item.get("value")
                    ],
                },
                "candidate_origin": {
                    "origin_type": fields["candidate_origin"]["origin_type"],
                    "paper_reassesses_unbound_status": bool(
                        bibliography.get("paper_reassesses_unbound_status")
                    ),
                },
                "core": projected_core,
            }
        )

    extraction_status = (
        result.get("roster_status") or "no_candidates"
        if result["status"] != PAPER_PARTIAL
        else PAPER_PARTIAL
    )
    return {
        "extraction": {"status": extraction_status},
        "candidates": candidates,
    }
