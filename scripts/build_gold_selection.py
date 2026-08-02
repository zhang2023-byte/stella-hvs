#!/usr/bin/env python3
"""Create one immutable, value-free expert-gold selection profile."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from stella.benchmark.gold_selection import (
    build_gold_selection,
    write_gold_selection_once,
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
    parser = argparse.ArgumentParser(
        description="Build one immutable per-paper expert-gold selection profile."
    )
    parser.add_argument("--campaign", default=ACTIVE_BENCHMARK_CAMPAIGN)
    parser.add_argument("--split", choices=("dev", "test"), required=True)
    parser.add_argument("--selection-id", required=True)
    parser.add_argument("--annotator-map", type=Path, required=True)
    parser.add_argument("--gold-dir", type=Path, default=None)
    parser.add_argument("--campaign-manifest", type=Path, default=None)
    parser.add_argument("--gold-manifest", type=Path, default=None)
    return parser


def load_annotator_map(path: Path) -> dict[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"annotator map is not valid JSON: {path}") from exc
    if not isinstance(payload, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in payload.items()
    ):
        raise ValueError("annotator map must be a JSON object of arxiv_id to annotator")
    return payload


def main() -> int:
    load_env_files(WORKSPACE)
    args = build_parser().parse_args()
    paths = campaign_paths(WORKSPACE, args.campaign)
    campaign_manifest = args.campaign_manifest or paths.campaign_manifest
    gold_manifest = args.gold_manifest or paths.gold_manifest
    output = paths.gold_selections / f"{args.selection_id}.json"
    gold_dir = args.gold_dir if args.gold_dir is not None else default_gold_dir()
    if gold_dir is None:
        raise SystemExit(f"Set {GOLD_DIR_ENV} or pass --gold-dir to the private gold store.")
    try:
        gold_dir = require_external_path(
            gold_dir, workspace=WORKSPACE, label="gold directory"
        )
        annotator_map = load_annotator_map(args.annotator_map.expanduser())
        profile = build_gold_selection(
            campaign_path=campaign_manifest.expanduser().resolve(),
            gold_manifest_path=gold_manifest.expanduser().resolve(),
            gold_dir=gold_dir,
            split=args.split,
            selection_id=args.selection_id,
            annotator_map=annotator_map,
        )
        written = write_gold_selection_once(output.expanduser(), profile)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Wrote {written} ({len(profile['papers'])} selected papers)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
