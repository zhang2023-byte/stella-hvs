#!/usr/bin/env python3
"""Create one immutable, public expert-assignment profile."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stella.benchmark.gold_assignment import (
    build_gold_assignment,
    write_gold_assignment_once,
)
from stella.benchmark.paths import campaign_paths
from stella.schema_registry import ACTIVE_BENCHMARK_CAMPAIGN


WORKSPACE = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build one immutable campaign-wide expert assignment profile."
    )
    parser.add_argument("--campaign", default=ACTIVE_BENCHMARK_CAMPAIGN)
    parser.add_argument("--assignment-id", required=True)
    parser.add_argument("--assignment-map", type=Path, required=True)
    parser.add_argument("--campaign-manifest", type=Path, default=None)
    return parser


def load_assignment_map(path: Path) -> dict[str, dict[str, object]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"assignment map is not valid JSON: {path}") from exc
    if not isinstance(payload, dict) or not all(
        isinstance(arxiv_id, str) and isinstance(assignment, dict)
        for arxiv_id, assignment in payload.items()
    ):
        raise ValueError("assignment map must be a JSON object of paper assignments")
    return payload


def main() -> int:
    args = build_parser().parse_args()
    paths = campaign_paths(WORKSPACE, args.campaign)
    campaign_manifest = (
        args.campaign_manifest.expanduser().resolve()
        if args.campaign_manifest is not None
        else paths.campaign_manifest
    )
    output = paths.gold_assignments / f"{args.assignment_id}.json"
    try:
        profile = build_gold_assignment(
            campaign_path=campaign_manifest,
            assignment_id=args.assignment_id,
            assignments=load_assignment_map(args.assignment_map.expanduser()),
        )
        written = write_gold_assignment_once(output, profile)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Wrote {written} ({len(profile['papers'])} assigned papers)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
