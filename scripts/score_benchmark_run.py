#!/usr/bin/env python3
"""Formally score one sealed ``hvs-extraction-v1`` campaign run.

This v0.3 entrypoint accepts only a sealed, clean run contract and scores
only the requested campaign split. It never accepts legacy literature or
v0.2 run layouts as formal inputs.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from stella.benchmark.scoring import score_formal_campaign_run
from stella.lit.env import load_env_files

WORKSPACE = Path(__file__).resolve().parents[1]
GOLD_DIR_ENV = "STELLA_GOLD_DIR"
DEFAULT_CAMPAIGN = WORKSPACE / "benchmark" / "manifest" / "campaign_manifest.json"
DEFAULT_GOLD_MANIFEST = WORKSPACE / "benchmark" / "manifest" / "gold_manifest.json"
DEFAULT_RELEASES_ROOT = WORKSPACE / "benchmark" / "releases"
DEFAULT_SCORING_DIR = WORKSPACE / "benchmark" / "scoring"


def default_gold_dir() -> Path | None:
    value = os.environ.get(GOLD_DIR_ENV, "").strip()
    return Path(value).expanduser() if value else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Formally score one sealed benchmark campaign run (scorecard v0.3)."
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--campaign-manifest", type=Path, default=DEFAULT_CAMPAIGN)
    parser.add_argument("--split", choices=("dev", "test"), required=True)
    parser.add_argument("--gold-dir", type=Path, default=None)
    parser.add_argument("--gold-manifest", type=Path, default=DEFAULT_GOLD_MANIFEST)
    parser.add_argument("--releases-root", type=Path, default=DEFAULT_RELEASES_ROOT)
    parser.add_argument(
        "--run-label",
        default=None,
        help="Public scorecard directory name. Default: sealed run id.",
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
    gold_dir = args.gold_dir if args.gold_dir is not None else default_gold_dir()
    if gold_dir is None:
        raise SystemExit(f"Set {GOLD_DIR_ENV} or pass --gold-dir to the private gold store.")
    gold_dir = gold_dir.expanduser().resolve()
    if not gold_dir.is_dir():
        raise SystemExit(f"gold directory not found: {gold_dir}")

    scorecard, private_details = score_formal_campaign_run(
        campaign_path=args.campaign_manifest.expanduser(),
        split=args.split,
        run_dir=args.run_dir.expanduser(),
        gold_dir=gold_dir,
        gold_manifest_path=args.gold_manifest.expanduser(),
        releases_root=args.releases_root.expanduser(),
        run_label=args.run_label,
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

    scoring_dir = args.scoring_dir.expanduser() / run_label
    scoring_dir.mkdir(parents=True, exist_ok=True)
    scorecard_path = scoring_dir / "scorecard.json"
    scorecard_path.write_text(scorecard_text, encoding="utf-8")
    details_root = (
        args.details_dir.expanduser()
        if args.details_dir is not None
        else gold_dir.parent / "scoring-details"
    )
    details_path = details_root / run_label / "details.json"
    details_path.parent.mkdir(parents=True, exist_ok=True)
    details_path.write_text(
        json.dumps(private_details, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    delivery = scorecard["delivery_counts"]
    print(f"Wrote {scorecard_path}")
    print(f"Wrote {details_path} (private)")
    print(
        "delivery: "
        f"valid={delivery['valid']} invalid={delivery['invalid']} missing={delivery['missing']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
