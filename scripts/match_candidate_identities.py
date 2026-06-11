#!/usr/bin/env python3
"""Match candidate identities between two literature_hvs_candidates.json files.

The deterministic referee for benchmark scoring: pairs candidates from two
extractions of the same paper by Gaia id, then name alias, then coordinate
proximity. Prints a JSON match report.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stella.benchmark.identity import (
    DEFAULT_FALLBACK_TOLERANCE_ARCSEC,
    DEFAULT_PROPAGATED_TOLERANCE_ARCSEC,
    match_candidate_sets,
)


def load_candidates(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    candidates = payload.get("candidates") if isinstance(payload, dict) else None
    if not isinstance(candidates, list):
        raise SystemExit(f"{path}: expected a literature_hvs_candidates.json file with a candidates list")
    return candidates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--left", type=Path, required=True, help="First literature_hvs_candidates.json (e.g. gold).")
    parser.add_argument("--right", type=Path, required=True, help="Second literature_hvs_candidates.json (e.g. AI run).")
    parser.add_argument(
        "--propagated-tolerance-arcsec",
        type=float,
        default=DEFAULT_PROPAGATED_TOLERANCE_ARCSEC,
        help="Tolerance when both sides are propagated to the common epoch (faststars Gaia radius).",
    )
    parser.add_argument(
        "--fallback-tolerance-arcsec",
        type=float,
        default=DEFAULT_FALLBACK_TOLERANCE_ARCSEC,
        help="Tolerance for unpropagated raw positions (faststars SIMBAD radius).",
    )
    args = parser.parse_args()
    report = match_candidate_sets(
        load_candidates(args.left),
        load_candidates(args.right),
        propagated_tolerance_arcsec=args.propagated_tolerance_arcsec,
        fallback_tolerance_arcsec=args.fallback_tolerance_arcsec,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
