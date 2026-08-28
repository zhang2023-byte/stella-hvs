"""Snapshot-bound, immutable operational cost artifacts for benchmark runs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from stella.benchmark.campaign import sha256_file
from stella.benchmark.pricing import (
    estimate_api_cost,
    estimate_api_cost_for_routes,
    load_pricing_snapshot,
)
from stella.benchmark.run_contract import canonical_sha256
from stella.schema_registry import require_schema, schema_ref

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

USAGE_COUNT_KEYS = (
    "prompt_tokens",
    "cached_input_tokens",
    "uncached_input_tokens",
    "completion_tokens",
    "reasoning_tokens",
    "total_tokens",
    "api_calls",
)


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return value


def _contribution_usage_record(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {key: 0 for key in USAGE_COUNT_KEYS}
    missing_usage = 0
    for attempt in attempts:
        totals["api_calls"] += 1
        usage = attempt.get("usage")
        if not isinstance(usage, dict):
            missing_usage += 1
            continue
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        cached = int(
            (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
            or usage.get("prompt_cache_hit_tokens")
            or 0
        )
        totals["prompt_tokens"] += prompt
        totals["cached_input_tokens"] += cached
        totals["uncached_input_tokens"] += max(0, prompt - cached)
        totals["completion_tokens"] += completion
        totals["reasoning_tokens"] += int(
            (usage.get("completion_tokens_details") or {}).get(
                "reasoning_tokens"
            )
            or usage.get("reasoning_tokens")
            or 0
        )
        totals["total_tokens"] += int(
            usage.get("total_tokens") or prompt + completion
        )
    if not attempts:
        status = "not_applicable"
    elif missing_usage == len(attempts):
        status = "unavailable"
    elif missing_usage:
        status = "partial"
    else:
        status = "complete"
    warnings = (
        [f"{missing_usage} physical request(s) omitted usage telemetry"]
        if missing_usage
        else []
    )
    return {**totals, "telemetry_status": status, "warnings": warnings}


def _contribution_pricing_request(attempt: dict[str, Any]) -> dict[str, Any]:
    usage = attempt.get("usage")
    record = {
        "started_at": attempt.get("started_at"),
        "usage_available": isinstance(usage, dict),
        "uncached_input_tokens": 0,
        "cached_input_tokens": 0,
        "completion_tokens": 0,
    }
    if not isinstance(usage, dict):
        return record
    prompt = int(usage.get("prompt_tokens") or 0)
    cached = int(
        (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
        or usage.get("prompt_cache_hit_tokens")
        or 0
    )
    record.update(
        {
            "uncached_input_tokens": max(0, prompt - cached),
            "cached_input_tokens": cached,
            "completion_tokens": int(usage.get("completion_tokens") or 0),
        }
    )
    return record


def aggregate_contribution_usage(run_dir: Path) -> dict[str, Any]:
    """Aggregate each physical contribution request exactly once by role."""

    role_patterns = {
        "roster": "contribution_roster_proposal-slot-*.json",
        "quantity": "object_quantities/*.json",
    }
    role_attempts: dict[str, list[dict[str, Any]]] = {
        role: [] for role in role_patterns
    }
    input_hashes: list[dict[str, str]] = []
    attempts_root = Path(run_dir) / "extraction_attempts"
    for role, pattern in role_patterns.items():
        for path in sorted(attempts_root.glob(f"*/papers/*/{pattern}")):
            payload = _load_object(path, f"{role} attempt artifact")
            attempts = payload.get("attempts") or []
            if not isinstance(attempts, list) or any(
                not isinstance(item, dict) for item in attempts
            ):
                raise ValueError(f"{role} attempt artifact has invalid attempts: {path}")
            role_attempts[role].extend(attempts)
            input_hashes.append(
                {
                    "path": str(path.relative_to(run_dir)),
                    "sha256": sha256_file(path),
                }
            )
    by_role = {
        role: _contribution_usage_record(attempts)
        for role, attempts in role_attempts.items()
    }
    pricing_requests_by_role = {
        role: [_contribution_pricing_request(attempt) for attempt in attempts]
        for role, attempts in role_attempts.items()
    }
    totals = {
        key: sum(record[key] for record in by_role.values())
        for key in USAGE_COUNT_KEYS
    }
    statuses = {record["telemetry_status"] for record in by_role.values()}
    if statuses <= {"complete", "not_applicable"}:
        total_status = "complete"
    elif "unavailable" in statuses and not any(
        record["total_tokens"] for record in by_role.values()
    ):
        total_status = "unavailable"
    else:
        total_status = "partial"
    total_warnings = [
        f"{role}: {warning}"
        for role, record in by_role.items()
        for warning in record["warnings"]
    ]
    return {
        "by_role": by_role,
        "total": {
            **totals,
            "telemetry_status": total_status,
            "warnings": total_warnings,
        },
        "pricing_requests_by_role": pricing_requests_by_role,
        "input_artifacts_sha256": canonical_sha256(input_hashes),
    }


def build_contribution_run_cost_artifact(
    run_dir: Path,
    pricing_snapshot_path: Path,
    *,
    final_status: str,
) -> dict[str, Any]:
    """Build a cost sidecar for the contribution-first benchmark runtime."""

    if final_status not in {"complete", "partial"}:
        raise ValueError("contribution run cost requires complete or partial status")
    run_path = Path(run_dir) / "run.json"
    campaign_path = Path(run_dir) / "campaign.json"
    method_path = Path(run_dir) / "method_config.json"
    run = _load_object(run_path, "benchmark run")
    campaign = _load_object(campaign_path, "benchmark campaign")
    frozen = _load_object(method_path, "benchmark method")
    method = frozen.get("method") or {}
    routes: dict[str, tuple[str, str]] = {}
    for role, key in (("roster", "roster_model"), ("quantity", "quantity_model")):
        route = method.get(key) or {}
        provider = str(route.get("provider") or "")
        model = str(route.get("model") or "")
        if not provider or not model:
            raise ValueError(f"contribution method is missing the {role} route")
        routes[role] = (provider, model)
    usage = aggregate_contribution_usage(Path(run_dir))
    usage_inputs_hash = usage.pop("input_artifacts_sha256")
    pricing_requests_by_role = usage.pop("pricing_requests_by_role")
    snapshot = load_pricing_snapshot(pricing_snapshot_path)
    cost = estimate_api_cost_for_routes(
        snapshot=snapshot,
        snapshot_path=pricing_snapshot_path,
        routes=routes,
        usage=usage,
        request_usage_by_role=pricing_requests_by_role,
    )
    artifact = {
        "schema": schema_ref("benchmark.run_cost"),
        "generated_at": None,
        "run_id": str(run.get("run_id") or Path(run_dir).name),
        "campaign": str(campaign.get("campaign_id") or "hvs-extraction-v6"),
        "scope": str(campaign.get("profile") or "dev10"),
        "run_state": final_status,
        "source": {
            "run_json_sha256": sha256_file(run_path),
            "campaign_sha256": sha256_file(campaign_path),
            "method_config_sha256": sha256_file(method_path),
            "usage_inputs_sha256": usage_inputs_hash,
        },
        "usage": usage,
        "estimated_api_cost": cost,
    }
    artifact["content_sha256"] = canonical_sha256(artifact)
    return validate_run_cost_artifact(artifact)


def build_run_cost_artifact(
    run_dir: Path, pricing_snapshot_path: Path
) -> dict[str, Any]:
    """Build a deterministic cost sidecar from one terminal run summary."""

    config_path = run_dir / "run_config.json"
    summary_path = run_dir / "run_summary.json"
    manifest_path = run_dir / "run_manifest.json"
    config = _load_object(config_path, "run config")
    summary = _load_object(summary_path, "run summary")
    require_schema(config, "benchmark.run_config", require_current=True)
    require_schema(summary, "benchmark.run_summary", require_current=True)
    if config.get("run_id") != summary.get("run_id"):
        raise ValueError("run config and summary identities do not match")
    if summary.get("state") not in {"completed", "interrupted"}:
        raise ValueError("run cost requires a terminal run summary")
    if summary.get("state") == "completed" and not manifest_path.is_file():
        raise ValueError("completed run cost requires run_manifest.json")
    snapshot = load_pricing_snapshot(pricing_snapshot_path)
    cost = estimate_api_cost(
        snapshot=snapshot,
        snapshot_path=pricing_snapshot_path,
        run_config=config,
        usage=summary.get("usage") or {},
    )
    source = {
        "run_config_sha256": sha256_file(config_path),
        "run_summary_sha256": sha256_file(summary_path),
        "run_manifest_sha256": (
            sha256_file(manifest_path) if manifest_path.is_file() else None
        ),
    }
    campaign = config.get("campaign")
    campaign_id = (
        campaign.get("campaign_id") if isinstance(campaign, dict) else campaign
    )
    artifact = {
        "schema": schema_ref("benchmark.run_cost"),
        "generated_at": summary.get("generated_at"),
        "run_id": config["run_id"],
        "campaign": campaign_id,
        "scope": config["scope"],
        "run_state": summary["state"],
        "source": source,
        "usage": summary["usage"],
        "estimated_api_cost": cost,
    }
    artifact["content_sha256"] = canonical_sha256(artifact)
    return validate_run_cost_artifact(artifact)


def validate_run_cost_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    """Validate the stable envelope and self-hash of a run cost artifact."""

    require_schema(artifact, "benchmark.run_cost", require_current=True)
    for key in ("run_id", "campaign", "scope", "run_state"):
        if not isinstance(artifact.get(key), str) or not artifact[key]:
            raise ValueError(f"run cost requires {key}")
    if artifact["run_state"] not in {
        "completed",
        "interrupted",
        "complete",
        "partial",
    }:
        raise ValueError("run cost has invalid run_state")
    source = artifact.get("source")
    if not isinstance(source, dict):
        raise ValueError("run cost source must be an object")
    legacy_keys = {"run_config_sha256", "run_summary_sha256"}
    contribution_keys = {
        "run_json_sha256",
        "campaign_sha256",
        "method_config_sha256",
        "usage_inputs_sha256",
    }
    if legacy_keys <= set(source):
        required_hashes = legacy_keys
        optional_hashes = {"run_manifest_sha256"}
    elif contribution_keys <= set(source):
        required_hashes = contribution_keys
        optional_hashes = set()
    else:
        raise ValueError("run cost source does not match a supported run lineage")
    for key in required_hashes:
        if SHA256_PATTERN.fullmatch(str(source.get(key) or "")) is None:
            raise ValueError(f"run cost source requires {key}")
    for key in optional_hashes:
        value = source.get(key)
        if value is not None and SHA256_PATTERN.fullmatch(str(value)) is None:
            raise ValueError(f"run cost has invalid {key}")
    if not isinstance(artifact.get("usage"), dict):
        raise ValueError("run cost usage must be an object")
    cost = artifact.get("estimated_api_cost")
    if not isinstance(cost, dict) or cost.get("currency") != "CNY":
        raise ValueError("run cost requires a CNY estimate")
    expected_hash = canonical_sha256(
        {key: value for key, value in artifact.items() if key != "content_sha256"}
    )
    if artifact.get("content_sha256") != expected_hash:
        raise ValueError("run cost content hash mismatch")
    return artifact


def write_run_cost_once(run_dir: Path, pricing_snapshot_path: Path) -> Path:
    """Write one immutable run_cost.json sidecar and refuse replacement."""

    artifact = build_run_cost_artifact(run_dir, pricing_snapshot_path)
    output = run_dir / "run_cost.json"
    try:
        with output.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n")
    except FileExistsError as exc:
        raise ValueError(f"run cost already exists: {output}") from exc
    return output


def write_contribution_run_cost_once(
    run_dir: Path,
    pricing_snapshot_path: Path,
    *,
    final_status: str,
) -> Path:
    """Write one immutable contribution benchmark cost sidecar."""

    artifact = build_contribution_run_cost_artifact(
        run_dir,
        pricing_snapshot_path,
        final_status=final_status,
    )
    output = Path(run_dir) / "run_cost.json"
    try:
        with output.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n")
    except FileExistsError as exc:
        raise ValueError(f"run cost already exists: {output}") from exc
    return output
