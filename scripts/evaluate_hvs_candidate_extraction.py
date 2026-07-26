#!/usr/bin/env python3
"""Evaluate one immutable extraction dev run against the external private gold."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stella.hvs_extraction.evaluate import (
    evaluate_hvs_extraction_run,
    render_terminal_report,
)
from stella.benchmark.paths import require_external_path
from stella.lit.env import env_value, load_env_files


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--gold-dir",
        default=None,
        help="external private gold directory; default STELLA_GOLD_DIR",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_env_files(ROOT)
    raw_gold_dir = args.gold_dir or env_value("STELLA_GOLD_DIR")
    if not raw_gold_dir:
        raise ValueError(
            "STELLA_GOLD_DIR or an explicit --gold-dir is required for evaluation"
        )
    gold_dir = require_external_path(
        Path(raw_gold_dir), workspace=ROOT, label="gold directory"
    )
    report = evaluate_hvs_extraction_run(
        ROOT,
        args.run_id,
        gold_dir=gold_dir,
    )
    print(render_terminal_report(report), flush=True)
    print(f"aggregate scorecard: {report['scorecard_path']}", flush=True)
    print(
        f"private details: {report['private_details_path']}",
        flush=True,
    )
    return 0


def cli() -> int:
    try:
        return main()
    except (FileNotFoundError, ValueError) as exc:
        print(f"extraction evaluation refused: {exc}", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(cli())
