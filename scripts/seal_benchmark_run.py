#!/usr/bin/env python3
"""Verify the immutable manifest of a completed current benchmark run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stella.benchmark.campaign import sha256_file
from stella.benchmark.run_contract import require_v5_run_manifest
from stella.schema_registry import require_schema

WORKSPACE = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify a completed current benchmark run"
    )
    parser.add_argument("run_dir", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    run_dir = args.run_dir.expanduser().resolve()
    config_path = run_dir / "run_config.json"
    summary_path = run_dir / "run_summary.json"
    manifest_path = run_dir / "run_manifest.json"
    if not all(path.is_file() for path in (config_path, summary_path, manifest_path)):
        raise SystemExit(
            "current runs are sealed by their runner; config, summary, and "
            "manifest must already exist"
        )
    config = json.loads(config_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require_schema(config, "benchmark.run_config", require_current=True)
    require_schema(summary, "benchmark.run_summary", require_current=True)
    require_v5_run_manifest(manifest)
    if manifest["run_config_sha256"] != sha256_file(config_path):
        raise SystemExit("run config hash does not match the sealed manifest")
    if manifest["run_summary_sha256"] != sha256_file(summary_path):
        raise SystemExit("run summary hash does not match the sealed manifest")
    print(
        f"Verified {manifest['run_id']}: "
        f"L1 complete={len(manifest['l1_roster_delivery']['complete'])}, "
        f"L2 complete={len(manifest['l2_core_field_delivery']['complete'])}, "
        f"partial={len(manifest['l2_core_field_delivery']['partial'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
