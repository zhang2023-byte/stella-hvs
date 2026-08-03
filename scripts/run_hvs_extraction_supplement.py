#!/usr/bin/env python3
"""Preflight a V6 full-fields or method-chain supplement experiment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stella.hvs_extraction.supplements import run_supplement


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument(
        "--type", required=True, choices=("full_fields", "method_chain")
    )
    parser.add_argument("--arxiv-id", action="append", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_supplement(
        ROOT,
        run_id=args.run_id,
        source_run_id=args.source_run_id,
        arxiv_ids=args.arxiv_id,
        supplement_type=args.type,
        adapter=None,
        preflight_only=args.preflight_only,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileExistsError, ValueError) as exc:
        print(f"supplement run refused: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(2)
