#!/usr/bin/env python3
"""Build the self-contained benchmark experiment report (dev_report.html).

Reads public scorecards from benchmark/campaigns/<id>/scoring/ plus the local
run archives for operational detail, optionally picks up the private
literature-baseline aggregate beside the gold store, and writes one offline
HTML file. The default output directory is <gold-dir>/../report/.
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path

from stella.benchmark.paths import require_external_path, validate_path_segment
from stella.benchmark.report import build_report_data, render_html, write_report
from stella.lit.env import load_env_files

WORKSPACE = Path(__file__).resolve().parents[1]
GOLD_DIR_ENV = "STELLA_GOLD_DIR"
DEFAULT_CAMPAIGNS = ["hvs-extraction-v5", "hvs-extraction-v6"]


def default_gold_dir() -> Path | None:
    value = os.environ.get(GOLD_DIR_ENV, "").strip()
    return Path(value).expanduser() if value else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the self-contained benchmark experiment HTML report."
    )
    parser.add_argument(
        "--campaign",
        action="append",
        dest="campaigns",
        default=None,
        help="Campaign id to include; repeatable. Default: V5 and V6.",
    )
    parser.add_argument("--gold-dir", type=Path, default=None)
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        default=None,
        help="Directory scanned for legacy_literature baseline scorecards. "
        "Default: <gold-dir>/../scoring-details/. Pass an empty path to skip.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Report output directory. Default: <gold-dir>/../report/.",
    )
    return parser


def main() -> int:
    load_env_files(WORKSPACE)
    args = build_parser().parse_args()
    campaigns = [
        validate_path_segment(value, "campaign id")
        for value in (args.campaigns or DEFAULT_CAMPAIGNS)
    ]
    gold_dir = args.gold_dir if args.gold_dir is not None else default_gold_dir()
    if gold_dir is None and (args.baseline_dir is None or args.output_dir is None):
        raise SystemExit(
            f"Set {GOLD_DIR_ENV} or pass --gold-dir so the baseline and output "
            "directories can be resolved (or pass both --baseline-dir and --output-dir)."
        )
    baseline_dirs: list[Path] = []
    if args.baseline_dir is not None:
        baseline_dirs = [args.baseline_dir.expanduser()]
    elif gold_dir is not None:
        baseline_dirs = [gold_dir.parent / "scoring-details"]
    output_dir = (
        args.output_dir.expanduser()
        if args.output_dir is not None
        else gold_dir.parent / "report"
    )
    try:
        output_dir = require_external_path(
            output_dir, workspace=WORKSPACE, label="report output directory"
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    data = build_report_data(WORKSPACE, campaigns, baseline_dirs)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html_text = render_html(data, generated_at)
    path = write_report(output_dir, html_text)
    n_runs = sum(exp["n_runs"] for exp in data["experiments"]) + sum(
        exp["n_runs"] for exp in data["singles"]
    )
    print(f"Wrote {path}")
    print(
        f"Experiments: {len(data['experiments'])} (n>=3) + "
        f"{len(data['singles'])} single-run configs, {n_runs} scored runs total; "
        f"baseline: {'yes' if data['baseline'] else 'no'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
