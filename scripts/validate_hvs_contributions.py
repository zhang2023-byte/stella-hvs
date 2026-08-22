#!/usr/bin/env python3
"""Validate a literature_hvs_contributions v1 document (or a run's paper copy)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Strictly validate one literature_hvs_contributions document.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", help="Path to a literature_hvs_contributions.json.")
    source.add_argument(
        "--run-paper-dir",
        help="A contribution run's papers/<arxiv_id> directory holding the canonical document.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from stella.hvs_contribution_extraction.schema_check import (
        validate_contribution_document_file,
    )

    path = Path(args.input) if args.input else Path(args.run_paper_dir) / "literature_hvs_contributions.json"
    try:
        record = validate_contribution_document_file(path)
    except FileNotFoundError:
        print(f"missing document: {path}", file=sys.stderr)
        return 2
    except Exception as exc:  # surface any validation failure verbatim
        print(f"invalid document: {exc}", file=sys.stderr)
        return 1
    print(
        f"valid: {record.schema_.name} v{record.schema_.version} "
        f"status={record.extraction.status} "
        f"roster={record.extraction.roster_status} "
        f"contributions={len(record.object_contributions)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
