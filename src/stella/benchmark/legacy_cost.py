"""Deterministic cost backfill for completed end-to-end legacy dev10 runs."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from stella.benchmark.campaign import sha256_file
from stella.benchmark.pricing import (
    COST_FORMULA_VERSION,
    estimate_api_cost_for_routes,
    load_pricing_snapshot,
)
from stella.benchmark.run_contract import canonical_sha256
from stella.hvs_extraction.run import USAGE_NUMERIC_FIELDS, _aggregate_usage
from stella.schema_registry import schema_ref

STAGES = ("roster", "roster_review", "core_fields", "final_review")
LEGACY_DEV10_RUNS: dict[str, tuple[str, ...]] = {
    "hvs-extraction-scratch-legacy": (
        "scratch-dev-single",
        "scratch-dev-ensemble",
        "scratch-dev2-single",
        "scratch-dev2-ensemble",
        "scratch-dev3-ensemble",
        "scratch-final-full-dev10",
        "scratch-dev10-20260726T034159Z",
    ),
    "hvs-extraction-v2": (
        "dev-b-202607140950-1",
        "dev-b-202607140952-3",
        "dev-c-202607140951-2",
        "dev-c-202607140952-4",
    ),
    "hvs-extraction-v3": (
        "v3-dev-baseline-b-core-r1",
        "v3-dev-baseline-c-core-r1",
        "v3-dev-hardened-b-core-r1",
    ),
    "hvs-extraction-v4": (
        "v4-dev-pre-engineering-b-core-r1",
        "v4-dev-post-engineering-b-core-r1",
    ),
    "hvs-extraction-v5": (
        "v5-dev10-glm52-thinking-high-repeat1-20260730",
        "v5-dev10-glm52-thinking-high-repeat2-20260730",
        "v5-dev10-glm52-thinking-high-repeat3-20260730",
        "v5-dev10-dsv4flash0731-roster-high-field-low-r1-20260731",
        "v5-dev10-dsv4flash0731-roster-max-field-low-r1-20260731",
    ),
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _empty_units() -> dict[str, list[dict[str, Any]]]:
    return {stage: [] for stage in STAGES}


def _source_hashes(run_dir: Path) -> dict[str, str | None]:
    values: dict[str, str | None] = {}
    for name in ("run_config.json", "run_summary.json", "run_manifest.json"):
        path = run_dir / name
        values[name.removesuffix(".json") + "_sha256"] = (
            sha256_file(path) if path.is_file() else None
        )
    return values


def _route(value: Any, label: str) -> tuple[str, str]:
    if not isinstance(value, dict):
        raise ValueError(f"legacy run is missing {label} route")
    provider = str(value.get("provider") or "")
    model = str(value.get("model") or "")
    if not provider or not model:
        raise ValueError(f"legacy run is missing {label} provider/model")
    return provider, model


def _scratch_or_v5_units(
    run_dir: Path, config: dict[str, Any], *, scratch: bool
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, tuple[str, str]]]:
    method = config.get("method") or {}
    roster_route = _route(
        method.get("roster_extractor") if scratch else method.get("roster_model"),
        "roster",
    )
    core_route = _route(
        method.get("field_extractor") if scratch else method.get("core_field_model"),
        "core fields",
    )
    adjudicator = method.get("roster_adjudicator") if scratch else None
    review_route = _route(adjudicator, "roster review") if adjudicator else roster_route
    units = _empty_units()
    paper_root = run_dir / "papers"
    for path in sorted(paper_root.glob("*/roster_proposal-slot-*.json")):
        artifact = _load(path)
        units["roster"].append(
            {
                "attempts": artifact.get("attempts") or [],
                "usages": artifact.get("usages") or [],
            }
        )
    if scratch:
        for path in sorted(paper_root.glob("*/roster_final.json")):
            provenance = _load(path).get("provenance") or {}
            attempts = provenance.get("adjudicator_attempts") or []
            usages = provenance.get("adjudicator_usages") or []
            if attempts or usages:
                units["roster_review"].append(
                    {"attempts": attempts, "usages": usages}
                )
    for path in sorted(paper_root.glob("*/candidates/*.json")):
        artifact = _load(path)
        units["core_fields"].append(
            {
                "attempts": artifact.get("attempts") or [],
                "usages": artifact.get("usages") or [],
            }
        )
    return units, {
        "roster": roster_route,
        "roster_review": review_route,
        "core_fields": core_route,
        "final_review": review_route,
    }


def _attempt_stage(name: str) -> str:
    if name.startswith(("roster-review-", "roster-reconciliation-")):
        return "roster_review"
    if name.startswith("roster-"):
        return "roster"
    if name.startswith(("review-", "review-revision-")):
        return "final_review"
    return "core_fields"


def _v2_v4_units(
    run_dir: Path, config: dict[str, Any]
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, tuple[str, str]]]:
    method = config.get("method") or {}
    models = method.get("models") or {}
    providers = method.get("providers") or {}
    extractor_provider = (providers.get("extractor") or [None])[0]
    reviewer_provider = (providers.get("reviewer") or [None])[0]
    extractor = (str(extractor_provider or ""), str(models.get("extractor") or ""))
    reviewer = (str(reviewer_provider or ""), str(models.get("reviewer") or ""))
    if not all(extractor) or not all(reviewer):
        raise ValueError(f"legacy run routes are incomplete: {run_dir}")
    units = _empty_units()
    requests = {
        str(path)[: -len(".request.json")]: path
        for path in run_dir.glob("**/attempts/*.request.json")
    }
    responses = {
        str(path)[: -len(".response.json")]: path
        for path in run_dir.glob("**/attempts/*.response.json")
    }
    for stem in sorted(set(requests) | set(responses)):
        response_path = responses.get(stem)
        usage = None
        if response_path is not None:
            usage = _load(response_path).get("usage")
        name = Path(stem).name
        units[_attempt_stage(name)].append(
            {
                "attempts": [
                    {
                        "outcome": (
                            "response_received" if response_path is not None else "missing"
                        )
                    }
                ],
                "usages": [usage] if isinstance(usage, dict) else [],
            }
        )
    return units, {
        "roster": extractor,
        "roster_review": reviewer,
        "core_fields": extractor,
        "final_review": reviewer,
    }


def _aggregate_total(by_stage: dict[str, dict[str, Any]]) -> dict[str, Any]:
    total = {key: 0 for key in USAGE_NUMERIC_FIELDS}
    total["api_calls"] = 0
    warnings: set[str] = set()
    statuses: set[str] = set()
    for usage in by_stage.values():
        for key in (*USAGE_NUMERIC_FIELDS, "api_calls"):
            total[key] += int(usage.get(key) or 0)
        statuses.add(str(usage.get("telemetry_status") or "unavailable"))
        warnings.update(usage.get("warnings") or [])
    if statuses <= {"not_applicable"}:
        status = "not_applicable"
    elif statuses <= {"complete", "not_applicable"}:
        status = "complete"
    elif "unavailable" in statuses and total["total_tokens"] == 0:
        status = "unavailable"
    else:
        status = "partial"
    total["telemetry_status"] = status
    total["warnings"] = sorted(warnings)
    return total


def _run_record(
    campaign: str,
    run_id: str,
    run_dir: Path,
    snapshot: dict[str, Any],
    snapshot_path: Path,
) -> dict[str, Any]:
    config = _load(run_dir / "run_config.json")
    if campaign in {"hvs-extraction-v2", "hvs-extraction-v3", "hvs-extraction-v4"}:
        units, routes = _v2_v4_units(run_dir, config)
    else:
        units, routes = _scratch_or_v5_units(
            run_dir, config, scratch=campaign == "hvs-extraction-scratch-legacy"
        )
    by_stage = {stage: _aggregate_usage(units[stage]) for stage in STAGES}
    usage = {"by_role": by_stage, "total": _aggregate_total(by_stage)}
    cost = estimate_api_cost_for_routes(
        snapshot=snapshot,
        snapshot_path=snapshot_path,
        routes=routes,
        usage=usage,
    )
    by_stage_cost = cost.pop("by_role")
    provenance_status = (
        "reconstructed_from_paper_artifacts"
        if run_id == "scratch-final-full-dev10"
        else "strict_terminal_run"
    )
    return {
        "run_id": run_id,
        "campaign": campaign,
        "scope": "full_dev",
        "paper_count": 10,
        "provenance_status": provenance_status,
        "source": _source_hashes(run_dir),
        "routes": {
            stage: {"provider": route[0], "model": route[1]}
            for stage, route in routes.items()
        },
        "usage": {"by_stage": by_stage, "total": usage["total"]},
        "estimated_api_cost": {
            **cost,
            "by_stage": by_stage_cost,
        },
    }


def _combine_usage(values: list[dict[str, Any]]) -> dict[str, Any]:
    combined = {key: 0 for key in USAGE_NUMERIC_FIELDS}
    combined["api_calls"] = 0
    statuses: set[str] = set()
    warnings: set[str] = set()
    for value in values:
        for key in (*USAGE_NUMERIC_FIELDS, "api_calls"):
            combined[key] += int(value.get(key) or 0)
        statuses.add(str(value.get("telemetry_status") or "unavailable"))
        warnings.update(value.get("warnings") or [])
    if statuses <= {"not_applicable"}:
        status = "not_applicable"
    elif statuses <= {"complete", "not_applicable"}:
        status = "complete"
    elif "unavailable" in statuses and combined["total_tokens"] == 0:
        status = "unavailable"
    else:
        status = "partial"
    combined["telemetry_status"] = status
    combined["warnings"] = sorted(warnings)
    return combined


def _summary_cost(
    records: list[dict[str, Any]],
    snapshot: dict[str, Any],
    snapshot_path: Path,
) -> dict[str, Any]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        for stage in STAGES:
            route = record["routes"][stage]
            grouped[(stage, route["provider"], route["model"])].append(
                record["usage"]["by_stage"][stage]
            )
    routes: dict[str, tuple[str, str]] = {}
    by_role: dict[str, dict[str, Any]] = {}
    for index, ((stage, provider, model), values) in enumerate(sorted(grouped.items())):
        role = f"stage_{index}_{stage}"
        routes[role] = (provider, model)
        by_role[role] = _combine_usage(values)
    overall = estimate_api_cost_for_routes(
        snapshot=snapshot,
        snapshot_path=snapshot_path,
        routes=routes,
        usage={"by_role": by_role},
    )
    by_stage_cny: dict[str, str] = {}
    for stage in STAGES:
        stage_routes = {
            role: route
            for role, route in routes.items()
            if role.endswith("_" + stage)
        }
        stage_usage = {
            role: by_role[role]
            for role in stage_routes
        }
        estimate = estimate_api_cost_for_routes(
            snapshot=snapshot,
            snapshot_path=snapshot_path,
            routes=stage_routes,
            usage={"by_role": stage_usage},
        )
        by_stage_cny[stage] = estimate["known_subtotal_cny"]
    return {
        "status": overall["status"],
        "currency": "CNY",
        "total_cny": overall["total_cny"],
        "known_subtotal_cny": overall["known_subtotal_cny"],
        "by_stage_cny": by_stage_cny,
        "formula_version": COST_FORMULA_VERSION,
    }


def _summarize(
    records: list[dict[str, Any]],
    snapshot: dict[str, Any],
    snapshot_path: Path,
) -> dict[str, Any]:
    usage_by_stage: dict[str, dict[str, int]] = {
        stage: {key: 0 for key in (*USAGE_NUMERIC_FIELDS, "api_calls")}
        for stage in STAGES
    }
    for record in records:
        for stage, usage in record["usage"]["by_stage"].items():
            for key in usage_by_stage[stage]:
                usage_by_stage[stage][key] += int(usage.get(key) or 0)
    total_tokens = sum(
        stage["total_tokens"] for stage in usage_by_stage.values()
    )
    api_calls = sum(stage["api_calls"] for stage in usage_by_stage.values())
    return {
        "run_count": len(records),
        "usage": {
            "total_tokens": total_tokens,
            "api_calls": api_calls,
            "by_stage": usage_by_stage,
        },
        "estimated_api_cost": _summary_cost(records, snapshot, snapshot_path),
    }


def build_legacy_dev10_cost_inventory(
    workspace: Path, pricing_snapshot_path: Path
) -> dict[str, Any]:
    """Recalculate the frozen completed-dev10 scope without editing legacy runs."""

    snapshot = load_pricing_snapshot(pricing_snapshot_path)
    campaigns: list[dict[str, Any]] = []
    all_records: list[dict[str, Any]] = []
    for campaign, run_ids in LEGACY_DEV10_RUNS.items():
        records = [
            _run_record(
                campaign,
                run_id,
                workspace / "benchmark" / "campaigns" / campaign / "runs" / run_id,
                snapshot,
                pricing_snapshot_path,
            )
            for run_id in run_ids
        ]
        campaigns.append(
            {
                "campaign": campaign,
                "summary": _summarize(records, snapshot, pricing_snapshot_path),
                "runs": records,
            }
        )
        all_records.extend(records)
    artifact = {
        "schema": schema_ref("benchmark.legacy_dev10_cost_inventory"),
        "scope": {
            "name": "completed_end_to_end_dev10",
            "paper_count_per_run": 10,
            "legacy_runs_are_read_only": True,
            "selection": "explicit frozen run identities audited on 2026-08-04",
        },
        "pricing_snapshot": {
            "snapshot_id": snapshot["snapshot_id"],
            "sha256": sha256_file(pricing_snapshot_path),
            "captured_at": snapshot["source"]["captured_at"],
        },
        "cost_formula_version": COST_FORMULA_VERSION,
        "summary": _summarize(all_records, snapshot, pricing_snapshot_path),
        "campaigns": campaigns,
    }
    artifact["content_sha256"] = canonical_sha256(artifact)
    return artifact
