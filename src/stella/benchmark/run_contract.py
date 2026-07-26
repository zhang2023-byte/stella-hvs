"""Shared immutable helpers for current V5 benchmark runs."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from stella.schema_registry import require_schema


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def build_method_fingerprint(method: dict[str, Any]) -> str:
    return canonical_sha256(method)


def require_v5_run_manifest(
    manifest: dict[str, Any],
) -> tuple[dict[str, list[str]], dict[str, Any]]:
    """Validate the ordered V5 L1/L2 delivery envelope."""

    require_schema(manifest, "benchmark.run_manifest", require_current=True)
    papers = manifest.get("papers")
    if not isinstance(papers, list) or any(
        not isinstance(paper, str) or not paper for paper in papers
    ):
        raise ValueError("V5 run manifest papers must be an ordered id list")
    if len(papers) != len(set(papers)):
        raise ValueError("V5 run manifest papers must be unique")
    l1 = manifest.get("l1_roster_delivery")
    l2 = manifest.get("l2_core_field_delivery")
    if not isinstance(l1, dict) or set(l1) != {
        "complete",
        "failed",
        "missing",
    }:
        raise ValueError("V5 run manifest has invalid L1 delivery")
    if not isinstance(l2, dict) or set(l2) != {
        "complete",
        "partial",
        "failed",
        "missing",
        "candidate_counts",
    }:
        raise ValueError("V5 run manifest has invalid L2 delivery")
    for label, delivery, statuses in (
        ("L1", l1, ("complete", "failed", "missing")),
        ("L2", l2, ("complete", "partial", "failed", "missing")),
    ):
        flattened: list[str] = []
        for status in statuses:
            values = delivery.get(status)
            if not isinstance(values, list):
                raise ValueError(
                    f"V5 run manifest {label} outcomes must be lists"
                )
            if values != [paper for paper in papers if paper in set(values)]:
                raise ValueError(
                    f"V5 run manifest {label} outcomes must preserve paper order"
                )
            flattened.extend(values)
        if set(flattened) != set(papers) or len(flattened) != len(papers):
            raise ValueError(
                f"V5 run manifest {label} outcomes must exactly cover papers"
            )
    counts = l2["candidate_counts"]
    if not isinstance(counts, dict) or set(counts) != {
        "total",
        "fields_complete",
        "field_extraction_failed",
    }:
        raise ValueError("V5 run manifest has invalid candidate counts")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in counts.values()
    ):
        raise ValueError("V5 run manifest candidate counts must be non-negative")
    if (
        counts["fields_complete"] + counts["field_extraction_failed"]
        != counts["total"]
    ):
        raise ValueError("V5 run manifest candidate counts do not add up")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("V5 run manifest artifacts must be an object")
    if set(artifacts) - set(papers):
        raise ValueError("V5 run manifest artifacts contain undeclared papers")
    return l1, l2
