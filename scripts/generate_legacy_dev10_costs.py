#!/usr/bin/env python3
"""Generate or verify the persisted completed legacy dev10 cost inventory."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stella.benchmark.legacy_cost import build_legacy_dev10_cost_inventory
from stella.schema_registry import ACTIVE_BENCHMARK_PRICING_SNAPSHOT


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pricing-snapshot-id",
        default=ACTIVE_BENCHMARK_PRICING_SNAPSHOT,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="default benchmark/costs/<snapshot-id>/legacy_dev10.json",
    )
    parser.add_argument("--check", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    pricing_path = (
        ROOT
        / "benchmark"
        / "pricing"
        / "tokendance"
        / f"{args.pricing_snapshot_id}.json"
    )
    output = args.output or (
        ROOT / "benchmark" / "costs" / args.pricing_snapshot_id / "legacy_dev10.json"
    )
    expected = (
        json.dumps(
            build_legacy_dev10_cost_inventory(ROOT, pricing_path),
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    if args.check:
        if not output.is_file() or output.read_text(encoding="utf-8") != expected:
            raise SystemExit(f"legacy dev10 cost inventory is stale: {output}")
        print(f"Verified {output}")
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(expected, encoding="utf-8")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
