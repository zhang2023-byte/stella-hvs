#!/usr/bin/env python3
"""List one expert's new, resumable, or completed assigned papers."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from stella.benchmark.gold_assignment import (
    annotation_queue,
    load_gold_assignment,
    load_json_object,
)
from stella.benchmark.paths import campaign_paths, require_external_path
from stella.lit.env import load_env_files
from stella.schema_registry import ACTIVE_BENCHMARK_CAMPAIGN


WORKSPACE = Path(__file__).resolve().parents[1]
GOLD_DIR_ENV = "STELLA_GOLD_DIR"


def default_gold_dir() -> Path | None:
    value = os.environ.get(GOLD_DIR_ENV, "").strip()
    return Path(value).expanduser() if value else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", default=ACTIVE_BENCHMARK_CAMPAIGN)
    assignment = parser.add_mutually_exclusive_group(required=True)
    assignment.add_argument("--assignment-id")
    assignment.add_argument("--assignment-manifest", type=Path)
    parser.add_argument("--annotator", required=True)
    parser.add_argument(
        "--status",
        choices=("new", "resume", "completed", "all"),
        default="new",
    )
    parser.add_argument("--gold-dir", type=Path, default=None)
    parser.add_argument("--campaign-manifest", type=Path, default=None)
    parser.add_argument("--gold-manifest", type=Path, default=None)
    return parser


def main() -> int:
    load_env_files(WORKSPACE)
    args = build_parser().parse_args()
    paths = campaign_paths(WORKSPACE, args.campaign)
    campaign_manifest = args.campaign_manifest or paths.campaign_manifest
    gold_manifest_path = args.gold_manifest or paths.gold_manifest
    assignment_path = (
        args.assignment_manifest
        if args.assignment_manifest is not None
        else paths.gold_assignments / f"{args.assignment_id}.json"
    )
    gold_dir = args.gold_dir if args.gold_dir is not None else default_gold_dir()
    if gold_dir is None:
        raise SystemExit(f"Set {GOLD_DIR_ENV} or pass --gold-dir to inspect draft existence.")
    try:
        gold_dir = require_external_path(
            gold_dir, workspace=WORKSPACE, label="gold directory"
        )
        profile = load_gold_assignment(
            assignment_path.expanduser().resolve(),
            campaign_manifest.expanduser().resolve(),
        )
        manifest = load_json_object(
            gold_manifest_path.expanduser().resolve(), label="gold manifest"
        )
        rows = annotation_queue(profile, manifest, gold_dir, args.annotator)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if args.status != "all":
        rows = [row for row in rows if row["status"] == args.status]
    print(
        json.dumps(
            {
                "assignment_id": profile["assignment_id"],
                "annotator": args.annotator,
                "status": args.status,
                "papers": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
