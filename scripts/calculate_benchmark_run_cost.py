#!/usr/bin/env python3
"""Calculate or verify one terminal V6 benchmark run cost sidecar."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stella.benchmark.run_cost import (
    build_run_cost_artifact,
    write_run_cost_once,
)
from stella.benchmark.paths import validate_path_segment
from stella.schema_registry import ACTIVE_BENCHMARK_PRICING_SNAPSHOT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--pricing-snapshot-id",
        default=ACTIVE_BENCHMARK_PRICING_SNAPSHOT,
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    run_id = validate_path_segment(args.run_id, "run id")
    run_dir = (
        ROOT
        / "benchmark"
        / "campaigns"
        / "hvs-extraction-v6"
        / "runs"
        / run_id
    )
    pricing_path = (
        ROOT
        / "benchmark"
        / "pricing"
        / "tokendance"
        / f"{args.pricing_snapshot_id}.json"
    )
    if args.check:
        output = run_dir / "run_cost.json"
        expected = json.dumps(
            build_run_cost_artifact(run_dir, pricing_path),
            ensure_ascii=False,
            indent=2,
        ) + "\n"
        if not output.is_file() or output.read_text(encoding="utf-8") != expected:
            raise SystemExit(f"run cost is missing or stale: {output}")
        print(f"Verified {output}")
        return 0
    print(write_run_cost_once(run_dir, pricing_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
