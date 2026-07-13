#!/usr/bin/env python3
"""Analyze paired FULL versus CORE+PROV formal dev runs privately."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from stella.benchmark.paths import campaign_paths, require_external_path
from stella.benchmark.surface_ablation import (
    DEFAULT_ITERATIONS,
    DEFAULT_SEED,
    analyze_surface_ablation,
)
from stella.lit.env import load_env_files

WORKSPACE = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Private paired FULL versus CORE+PROV dev ablation."
    )
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--method", choices=("B", "C"), required=True)
    parser.add_argument("--full-run", action="append", required=True)
    parser.add_argument("--core-run", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--details-dir", type=Path)
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    return parser


def _fmt(value: object) -> str:
    return "n/a" if value is None else f"{float(value):.4f}"


def main() -> int:
    load_env_files(WORKSPACE)
    args = build_parser().parse_args()
    paths = campaign_paths(WORKSPACE, args.campaign)
    details_dir = args.details_dir
    if details_dir is None:
        private_root = os.environ.get("STELLA_GOLD_DIR", "").strip()
        if not private_root:
            raise SystemExit("set STELLA_GOLD_DIR or pass --details-dir")
        details_dir = Path(private_root).expanduser().parent / "scoring-details"
    try:
        details_dir = require_external_path(
            details_dir, workspace=WORKSPACE, label="private scoring details"
        )
        output = require_external_path(
            args.output, workspace=WORKSPACE, label="private ablation summary"
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    summary = analyze_surface_ablation(
        workspace=WORKSPACE,
        campaign_path=paths.campaign_manifest,
        method=args.method,
        full_run_ids=args.full_run,
        core_run_ids=args.core_run,
        runs_dir=paths.runs,
        scoring_dir=paths.scoring,
        details_dir=details_dir,
        iterations=args.iterations,
        seed=args.seed,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("metric                                  FULL      CORE     CORE-FULL   CI95")
    for key, row in summary["headline"].items():
        ci = row["paired_bootstrap_ci95"]
        ci_text = "n/a" if ci is None else f"[{ci[0]:.4f}, {ci[1]:.4f}]"
        print(
            f"{key:38} {_fmt(row['full']):>8} {_fmt(row['core']):>8} "
            f"{_fmt(row['delta_core_minus_full']):>11}   {ci_text}"
        )
    print(f"decision: {summary['decision']['status']}")
    print(f"Wrote {output} (private)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
