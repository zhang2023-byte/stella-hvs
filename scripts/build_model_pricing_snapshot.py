#!/usr/bin/env python3
"""Build one immutable normalized TokenDance pricing snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stella.benchmark.pricing import build_pricing_snapshot, write_pricing_snapshot_once

WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = WORKSPACE / "benchmark" / "pricing" / "tokendance"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Normalized selected TokenDance routes exported to a temporary JSON file.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    try:
        payload = json.loads(args.input.expanduser().read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("pricing input must be a JSON object")
        snapshot = build_pricing_snapshot(payload)
        path = write_pricing_snapshot_once(args.output_dir.expanduser(), snapshot)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Wrote {path} ({len(snapshot['routes'])} routes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
