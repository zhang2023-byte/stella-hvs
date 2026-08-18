#!/usr/bin/env python3
"""Formally score one sealed campaign-scoped benchmark run.

This entrypoint accepts only a sealed, clean run contract and scores
only the requested campaign split. It never accepts legacy literature or
legacy run layouts as formal inputs. A finalized clean network debug run
directory (debug_config.json present) is also accepted: it is scored as
the network-recovered view of its bound formal source run.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from stella.benchmark.scoring import score_formal_campaign_run, write_scorecard_once
from stella.benchmark.paths import (
    campaign_paths,
    require_external_path,
    validate_path_segment,
)
from stella.lit.env import load_env_files

WORKSPACE = Path(__file__).resolve().parents[1]
GOLD_DIR_ENV = "STELLA_GOLD_DIR"
DEFAULT_PATHS = campaign_paths(WORKSPACE)
DEFAULT_CAMPAIGN = DEFAULT_PATHS.campaign_manifest
DEFAULT_GOLD_MANIFEST = DEFAULT_PATHS.gold_manifest
DEFAULT_RELEASES_ROOT = DEFAULT_PATHS.releases
DEFAULT_SCORING_DIR = DEFAULT_PATHS.scoring
DEFAULT_PRICING_DIR = WORKSPACE / "benchmark" / "pricing" / "tokendance"


def default_gold_dir() -> Path | None:
    value = os.environ.get(GOLD_DIR_ENV, "").strip()
    return Path(value).expanduser() if value else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Formally score one sealed benchmark campaign run (current scorecard schema)."
    )
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--campaign", help="Campaign id; resolves all public benchmark paths.")
    parser.add_argument("--campaign-manifest", type=Path, default=DEFAULT_CAMPAIGN)
    parser.add_argument("--split", choices=("dev", "test"), required=True)
    parser.add_argument(
        "--pricing-snapshot-id",
        required=True,
        help="Immutable TokenDance pricing snapshot id under benchmark/pricing/tokendance/.",
    )
    parser.add_argument("--gold-dir", type=Path, default=None)
    parser.add_argument("--gold-manifest", type=Path, default=DEFAULT_GOLD_MANIFEST)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--gold-selection-id")
    selection.add_argument("--gold-selection-manifest", type=Path)
    parser.add_argument("--releases-root", type=Path, default=DEFAULT_RELEASES_ROOT)
    parser.add_argument(
        "--run-label",
        default=None,
        help="Public scorecard directory name. Default: sealed run id.",
    )
    parser.add_argument(
        "--supersedes",
        default=None,
        help="Optional earlier evaluation label superseded by this immutable scorecard.",
    )
    parser.add_argument("--scoring-dir", type=Path, default=DEFAULT_SCORING_DIR)
    parser.add_argument(
        "--details-dir",
        type=Path,
        default=None,
        help="Private details root. Default: <gold-dir>/../scoring-details/.",
    )
    return parser


def _value_marker(text: str) -> str:
    return text.strip() if any(ch.isalpha() for ch in text.strip()) else ""


def gold_marker_strings(private_details: dict) -> set[str]:
    """Identity and value strings that must never leak into a public scorecard."""

    markers: set[str] = set()
    for paper in private_details.get("papers", []):
        for pair in paper.get("pairs", []):
            markers.add(str(pair.get("gold_id") or ""))
            for row in pair.get("l2", []):
                markers.add(_value_marker(str(row.get("gold") or "")))
                markers.add(_value_marker(str(row.get("gold_note") or "")))
        for missed in paper.get("unmatched_gold", []):
            markers.add(str(missed.get("gold_id") or ""))
            for row in missed.get("l2", []):
                markers.add(_value_marker(str(row.get("gold") or "")))
    return {marker for marker in markers if len(marker) >= 4}


def main() -> int:
    load_env_files(WORKSPACE)
    args = build_parser().parse_args()
    if args.campaign:
        paths = campaign_paths(WORKSPACE, args.campaign)
        args.campaign_manifest = paths.campaign_manifest
        args.gold_manifest = paths.gold_manifest
        args.releases_root = paths.releases
        args.scoring_dir = paths.scoring
        if args.run_dir is None and args.run_id:
            args.run_dir = paths.runs / validate_path_segment(args.run_id, "run id")
        if args.gold_selection_id:
            selection_id = validate_path_segment(
                args.gold_selection_id, "gold selection id"
            )
            args.gold_selection_manifest = paths.gold_selections / f"{selection_id}.json"
    elif args.gold_selection_id:
        selection_id = validate_path_segment(args.gold_selection_id, "gold selection id")
        args.gold_selection_manifest = DEFAULT_PATHS.gold_selections / f"{selection_id}.json"
    if args.run_dir is None:
        raise SystemExit("pass --run-dir, or use --campaign with --run-id")
    gold_dir = args.gold_dir if args.gold_dir is not None else default_gold_dir()
    if gold_dir is None:
        raise SystemExit(f"Set {GOLD_DIR_ENV} or pass --gold-dir to the private gold store.")
    try:
        gold_dir = require_external_path(
            gold_dir, workspace=WORKSPACE, label="gold directory"
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if not gold_dir.is_dir():
        raise SystemExit(f"gold directory not found: {gold_dir}")

    scorecard, private_details = score_formal_campaign_run(
        campaign_path=args.campaign_manifest.expanduser(),
        split=args.split,
        run_dir=args.run_dir.expanduser(),
        gold_dir=gold_dir,
        gold_manifest_path=args.gold_manifest.expanduser(),
        gold_selection_path=args.gold_selection_manifest.expanduser(),
        pricing_snapshot_path=(
            DEFAULT_PRICING_DIR
            / f"{validate_path_segment(args.pricing_snapshot_id, 'pricing snapshot id')}.json"
        ),
        releases_root=args.releases_root.expanduser(),
        run_label=args.run_label,
        supersedes=args.supersedes,
    )
    run_label = scorecard["run_label"]
    scorecard_text = json.dumps(scorecard, ensure_ascii=False, indent=2) + "\n"
    leaked = [
        marker
        for marker in sorted(gold_marker_strings(private_details))
        if marker in scorecard_text
    ]
    if leaked:
        raise SystemExit("leak guard: public scorecard contains gold strings: " + ", ".join(leaked))

    scorecard_path = write_scorecard_once(args.scoring_dir.expanduser(), scorecard)
    details_root = (
        args.details_dir.expanduser()
        if args.details_dir is not None
        else gold_dir.parent / "scoring-details"
    )
    try:
        details_root = require_external_path(
            details_root, workspace=WORKSPACE, label="private scoring details"
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    details_path = details_root / run_label / "details.json"
    details_path.parent.mkdir(parents=True, exist_ok=True)
    details_path.write_text(
        json.dumps(private_details, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    roster = scorecard["l0"]["roster_delivery"]
    core = scorecard["l0"]["core_field_delivery"]
    print(f"Wrote {scorecard_path}")
    print(f"Wrote {details_path} (private)")
    print(
        "L0 delivery: "
        f"roster_complete={roster['complete']} core_complete={core['complete']} "
        f"core_partial={core['partial']} failed={core['failed']} missing={core['missing']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
