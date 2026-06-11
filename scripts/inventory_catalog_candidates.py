#!/usr/bin/env python3
"""Inventory local catalog-review candidates for one archived paper."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]

from stella.lit.catalog_review import build_catalog_candidate_inventory  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="List TeX table and data-resource candidates for catalog review.")
    parser.add_argument("--arxiv-id", required=True, help="arXiv ID such as 2402.10714.")
    parser.add_argument("--literature-dir", type=Path, default=WORKSPACE / "literature")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    literature_dir = args.literature_dir.expanduser()
    paper_dir = literature_dir / args.arxiv_id
    if not paper_dir.exists():
        raise SystemExit(f"paper directory does not exist: {paper_dir}")

    inventory = build_catalog_candidate_inventory(
        literature_dir=literature_dir,
        arxiv_id=args.arxiv_id,
        workspace=WORKSPACE,
    )
    print(json.dumps(inventory, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
