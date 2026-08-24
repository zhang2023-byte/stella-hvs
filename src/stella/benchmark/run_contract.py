"""Shared immutable helpers for current V6 benchmark runs."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from stella.lit.extraction.hashing import (  # noqa: F401
    canonical_json_bytes,
    canonical_sha256,
)
from stella.schema_registry import require_schema


def build_method_fingerprint(method: dict[str, Any]) -> str:
    return canonical_sha256(method)


def require_v6_run_manifest(
    manifest: dict[str, Any],
) -> tuple[dict[str, list[str]], dict[str, Any]]:
    """Validate the ordered V6 L0/L1/L2 delivery envelope."""

    require_schema(manifest, "benchmark.run_manifest", require_current=True)
    papers = manifest.get("papers")
    if not isinstance(papers, list) or any(
        not isinstance(paper, str) or not paper for paper in papers
    ):
        raise ValueError("V6 run manifest papers must be an ordered id list")
    if len(papers) != len(set(papers)):
        raise ValueError("V6 run manifest papers must be unique")
    l1 = manifest.get("l1_roster_delivery")
    l2 = manifest.get("l2_core_field_delivery")
    if not isinstance(l1, dict) or set(l1) != {
        "complete",
        "failed",
        "missing",
    }:
        raise ValueError("V6 run manifest has invalid L1 delivery")
    if not isinstance(l2, dict) or set(l2) != {
        "complete",
        "partial",
        "failed",
        "missing",
        "candidate_counts",
    }:
        raise ValueError("V6 run manifest has invalid L2 delivery")
    for label, delivery, statuses in (
        ("L1", l1, ("complete", "failed", "missing")),
        ("L2", l2, ("complete", "partial", "failed", "missing")),
    ):
        flattened: list[str] = []
        for status in statuses:
            values = delivery.get(status)
            if not isinstance(values, list):
                raise ValueError(
                    f"V6 run manifest {label} outcomes must be lists"
                )
            if values != [paper for paper in papers if paper in set(values)]:
                raise ValueError(
                    f"V6 run manifest {label} outcomes must preserve paper order"
                )
            flattened.extend(values)
        if set(flattened) != set(papers) or len(flattened) != len(papers):
            raise ValueError(
                f"V6 run manifest {label} outcomes must exactly cover papers"
            )
    counts = l2["candidate_counts"]
    if not isinstance(counts, dict) or set(counts) != {
        "total",
        "fields_complete",
        "field_extraction_failed",
    }:
        raise ValueError("V6 run manifest has invalid candidate counts")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in counts.values()
    ):
        raise ValueError("V6 run manifest candidate counts must be non-negative")
    if (
        counts["fields_complete"] + counts["field_extraction_failed"]
        != counts["total"]
    ):
        raise ValueError("V6 run manifest candidate counts do not add up")
    l0 = manifest.get("l0")
    if not isinstance(l0, dict) or set(l0) != {"format_validation"}:
        raise ValueError("V6 run manifest has invalid L0 envelope")
    formatting = l0["format_validation"]
    expected_format_keys = {
        "observed_units",
        "valid_first_pass",
        "valid_after_correction",
        "invalid",
        "not_observed",
        "first_pass_rate",
        "final_valid_rate",
    }
    if not isinstance(formatting, dict) or set(formatting) != expected_format_keys:
        raise ValueError("V6 run manifest has invalid format-validation counts")
    count_keys = expected_format_keys - {"first_pass_rate", "final_valid_rate"}
    if any(
        isinstance(formatting[key], bool)
        or not isinstance(formatting[key], int)
        or formatting[key] < 0
        for key in count_keys
    ):
        raise ValueError("V6 format-validation counts must be non-negative integers")
    observed = (
        formatting["valid_first_pass"]
        + formatting["valid_after_correction"]
        + formatting["invalid"]
    )
    if formatting["observed_units"] != observed:
        raise ValueError("V6 format-validation observed count does not add up")
    for key in ("first_pass_rate", "final_valid_rate"):
        value = formatting[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
            raise ValueError("V6 format-validation rates must be between zero and one")
    usage = manifest.get("usage")
    if not isinstance(usage, dict) or set(usage) != {"by_role", "total"}:
        raise ValueError("V6 run manifest has invalid usage envelope")
    by_role = usage["by_role"]
    if not isinstance(by_role, dict) or set(by_role) != {"roster", "core_fields"}:
        raise ValueError("V6 run manifest usage must cover roster and core_fields")
    usage_keys = {
        "prompt_tokens",
        "cached_input_tokens",
        "uncached_input_tokens",
        "completion_tokens",
        "reasoning_tokens",
        "total_tokens",
        "api_calls",
        "telemetry_status",
        "warnings",
    }
    for label, record in [*by_role.items(), ("total", usage["total"])]:
        if not isinstance(record, dict) or set(record) != usage_keys:
            raise ValueError(f"V6 run manifest has invalid {label} usage")
        for key in usage_keys - {"telemetry_status", "warnings"}:
            value = record[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"V6 run manifest {label} usage must be non-negative")
        if record["cached_input_tokens"] + record["uncached_input_tokens"] != record["prompt_tokens"]:
            raise ValueError(f"V6 run manifest {label} input token counts do not add up")
        if record["reasoning_tokens"] > record["completion_tokens"]:
            raise ValueError(f"V6 run manifest {label} reasoning tokens exceed completion")
        if record["telemetry_status"] not in {
            "complete",
            "partial",
            "unavailable",
            "not_applicable",
        }:
            raise ValueError(f"V6 run manifest {label} telemetry status is invalid")
        if not isinstance(record["warnings"], list) or any(
            not isinstance(item, str) for item in record["warnings"]
        ):
            raise ValueError(f"V6 run manifest {label} warnings must be strings")
    for key in usage_keys - {"telemetry_status", "warnings"}:
        if usage["total"][key] != sum(record[key] for record in by_role.values()):
            raise ValueError(f"V6 run manifest total {key} does not match role usage")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("V6 run manifest artifacts must be an object")
    if set(artifacts) - set(papers):
        raise ValueError("V6 run manifest artifacts contain undeclared papers")
    return l1, l2
