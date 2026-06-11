#!/usr/bin/env python3
"""Remove old catalog workflow outputs while preserving archived paper assets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]

from stella.lit.catalog_review import cleanup_catalog_workflow_outputs  # noqa: E402


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "t", "1", "yes", "y"}:
        return True
    if normalized in {"false", "f", "0", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError("expected True or False")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Remove catalog_review.json, catalog_extraction.json, catalog_sources/, catalog_tables/, and catalog workflow indexes."
    )
    parser.add_argument("--literature-dir", type=Path, default=WORKSPACE / "literature")
    parser.add_argument("--dry-run", type=parse_bool, default=False, metavar="True|False", help="Report changes without removing files. Default: False.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    payload = cleanup_catalog_workflow_outputs(args.literature_dir.expanduser(), dry_run=args.dry_run)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
