#!/usr/bin/env python3
"""Extract reviewed internal LaTeX tables into ECSV plus provenance JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]

from stella.lit.catalog_extraction import (  # noqa: E402
    extract_all_reviewed_catalog_tables,
    extract_catalog_tables,
)


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "t", "1", "yes", "y"}:
        return True
    if normalized in {"false", "f", "0", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError("expected True or False")


def parse_jobs(value: str) -> int | str:
    normalized = value.strip().lower()
    if normalized == "auto":
        return "Auto"
    try:
        jobs = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected Auto or a positive integer") from exc
    if jobs < 1:
        raise argparse.ArgumentTypeError("expected Auto or a positive integer")
    return jobs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract reviewed internal LaTeX tables into ECSV tables and provenance JSON."
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--arxiv-id", help="Extract reviewed internal tables for one arXiv ID.")
    selection.add_argument("--all-reviewed", action="store_true", help="Extract all reviewed papers with internal tables.")
    parser.add_argument("--internal-table-id", default=None, help="Extract one internal_tables[].id. Requires --arxiv-id.")
    parser.add_argument("--literature-dir", type=Path, default=WORKSPACE / "literature")
    parser.add_argument("--jobs", type=parse_jobs, default=1, metavar="Auto|N", help="Parallel paper workers for --all-reviewed. Default: 1.")
    parser.add_argument("--dry-run", type=parse_bool, default=False, metavar="True|False", help="Parse and report without writing files. Default: False.")
    parser.add_argument("--overwrite", type=parse_bool, default=False, metavar="True|False", help="Rewrite existing source excerpts and ECSV files. Default: False.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    literature_dir = args.literature_dir.expanduser()
    internal_table_id = args.internal_table_id
    if internal_table_id and args.all_reviewed:
        raise SystemExit("--internal-table-id requires --arxiv-id")
    if not literature_dir.exists():
        raise SystemExit(f"literature directory does not exist: {literature_dir}")

    try:
        if args.all_reviewed:
            payload = extract_all_reviewed_catalog_tables(
                literature_dir=literature_dir,
                workspace=WORKSPACE,
                dry_run=args.dry_run,
                overwrite=args.overwrite,
                jobs=args.jobs,
            )
        else:
            payload = extract_catalog_tables(
                literature_dir=literature_dir,
                arxiv_id=str(args.arxiv_id),
                workspace=WORKSPACE,
                internal_table_id=internal_table_id,
                dry_run=args.dry_run,
                overwrite=args.overwrite,
            )
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
