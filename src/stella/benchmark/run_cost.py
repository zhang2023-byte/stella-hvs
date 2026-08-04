"""Snapshot-bound, immutable operational cost artifacts for benchmark runs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from stella.benchmark.campaign import sha256_file
from stella.benchmark.pricing import estimate_api_cost, load_pricing_snapshot
from stella.benchmark.run_contract import canonical_sha256
from stella.schema_registry import require_schema, schema_ref

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return value


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
    if artifact["run_state"] not in {"completed", "interrupted"}:
        raise ValueError("run cost has invalid run_state")
    source = artifact.get("source")
    if not isinstance(source, dict):
        raise ValueError("run cost source must be an object")
    for key in ("run_config_sha256", "run_summary_sha256"):
        if SHA256_PATTERN.fullmatch(str(source.get(key) or "")) is None:
            raise ValueError(f"run cost source requires {key}")
    manifest_hash = source.get("run_manifest_sha256")
    if manifest_hash is not None and SHA256_PATTERN.fullmatch(str(manifest_hash)) is None:
        raise ValueError("run cost has invalid run_manifest_sha256")
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
