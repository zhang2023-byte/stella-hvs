#!/usr/bin/env python3
"""Score literature/<arxiv_id>/ candidates as a diagnostic baseline.

Reads the external private gold store under an explicit gold selection
profile and writes both the aggregate scorecard and the item-level details
beside that store (default: <gold-dir>/../scoring-details/<run_label>/).
Nothing is written into any campaign's public scoring directory. This is a
diagnostic baseline, not a formal campaign score.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from stella.benchmark.baseline import score_literature_baseline, write_baseline_outputs
from stella.benchmark.paths import campaign_paths, require_external_path, validate_path_segment
from stella.lit.env import load_env_files

WORKSPACE = Path(__file__).resolve().parents[1]
GOLD_DIR_ENV = "STELLA_GOLD_DIR"


def default_gold_dir() -> Path | None:
    value = os.environ.get(GOLD_DIR_ENV, "").strip()
    return Path(value).expanduser() if value else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Score literature/<arxiv_id>/literature_hvs_candidates.json against the "
            "selected expert gold as a diagnostic baseline (private output only)."
        )
    )
    parser.add_argument("--campaign", default=None, help="Campaign id; default: active campaign.")
    parser.add_argument("--split", choices=("dev",), required=True)
    parser.add_argument("--gold-selection-id", required=True)
    parser.add_argument("--gold-dir", type=Path, default=None)
    parser.add_argument(
        "--literature-dir",
        type=Path,
        default=WORKSPACE / "literature",
        help="Literature root containing per-paper candidates. Default: literature/",
    )
    parser.add_argument(
        "--run-label",
        default=None,
        help="Output directory name. Default: literature-baseline-<split>--gold-<selection id>.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory. Default: <gold-dir>/../scoring-details/<run_label>/.",
    )
    return parser


def main() -> int:
    load_env_files(WORKSPACE)
    args = build_parser().parse_args()
    paths = campaign_paths(WORKSPACE, args.campaign) if args.campaign else campaign_paths(WORKSPACE)
    selection_id = validate_path_segment(args.gold_selection_id, "gold selection id")
    gold_dir = args.gold_dir if args.gold_dir is not None else default_gold_dir()
    if gold_dir is None:
        raise SystemExit(f"Set {GOLD_DIR_ENV} or pass --gold-dir to the private gold store.")
    try:
        gold_dir = require_external_path(gold_dir, workspace=WORKSPACE, label="gold directory")
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if not gold_dir.is_dir():
        raise SystemExit(f"gold directory not found: {gold_dir}")

    run_label = args.run_label or f"literature-baseline-{args.split}--gold-{selection_id}"
    output_dir = (
        args.output_dir.expanduser()
        if args.output_dir is not None
        else gold_dir.parent / "scoring-details" / run_label
    )
    try:
        output_dir = require_external_path(
            output_dir, workspace=WORKSPACE, label="baseline output directory"
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    try:
        scorecard, private_details = score_literature_baseline(
            campaign_path=paths.campaign_manifest,
            split=args.split,
            literature_dir=args.literature_dir.expanduser(),
            gold_dir=gold_dir,
            gold_manifest_path=paths.gold_manifest,
            gold_selection_path=paths.gold_selections / f"{selection_id}.json",
            run_label=run_label,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    try:
        scorecard_path, details_path = write_baseline_outputs(
            output_dir, scorecard, private_details
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    l1 = scorecard["l1"]["micro"]
    l2 = scorecard["l2"]["micro"]
    print(f"Wrote {scorecard_path}")
    print(f"Wrote {details_path} (private)")
    print(
        "Baseline: "
        f"L1 P/R/F1={l1['precision']:.3f}/{l1['recall']:.3f}/{l1['f1']:.3f} "
        f"L2 coverage={l2['coverage']:.3f} "
        f"strict_e2e={l2['delivery_end_to_end_strict']:.3f}"
    )
    missing = [p["arxiv_id"] for p in scorecard["l1"]["per_paper"] if p["ai_status"] == "missing"]
    if missing:
        print(f"Papers without literature candidates: {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
