#!/usr/bin/env python3
"""Rebuild the paper-level literature HVS contributions index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stella.lit.hvs_contributions_index import (
    write_hvs_contributions_index_outputs,
)

WORKSPACE = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rebuild literature_hvs_contributions index files.",
    )
    parser.add_argument(
        "--literature-dir",
        type=Path,
        default=WORKSPACE / "literature",
        help="Directory containing <arxiv_id>/literature_hvs_contributions.json files.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = write_hvs_contributions_index_outputs(args.literature_dir)
    print(json.dumps(result["index_record"]["summary"], ensure_ascii=False, indent=2))
    print(result["index_json_path"])
    print(result["index_markdown_path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
