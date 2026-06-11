#!/usr/bin/env python3
"""Build the global HVS candidates index from per-paper literature_hvs_candidates.json files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]

from stella.lit.hvs_candidates_index import write_hvs_candidates_index_outputs  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build literature/02_literature_hvs_index.json and literature/02_literature_hvs_index.md."
    )
    parser.add_argument(
        "--literature-dir",
        type=Path,
        default=WORKSPACE / "literature",
        help="Literature root directory to scan. Default: literature/",
    )
    parser.add_argument(
        "--fail-on-skipped",
        action="store_true",
        help="Exit non-zero if any malformed literature_hvs_candidates.json file is skipped.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    literature_dir = args.literature_dir.expanduser()
    literature_dir.mkdir(parents=True, exist_ok=True)
    result = write_hvs_candidates_index_outputs(literature_dir, workspace=WORKSPACE)
    summary = result["index_record"]["summary"]
    print(
        "Built HVS candidates index: "
        f"{summary['paper_count']} papers, "
        f"{summary['candidates_found_count']} with candidates, "
        f"{summary['no_candidates_count']} with no candidates, "
        f"{summary['total_candidate_count']} total candidates."
    )
    print(result["index_json_path"])
    print(result["index_markdown_path"])
    skipped = result["index_record"]["skipped"]
    if args.fail_on_skipped and skipped:
        print("Skipped malformed HVS candidate files:", file=sys.stderr)
        for item in skipped:
            print(f"  {item['path']}: {item['error']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
