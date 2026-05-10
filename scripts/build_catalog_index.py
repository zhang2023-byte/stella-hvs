#!/usr/bin/env python3
"""Build the global catalog workflow index from per-paper catalog JSON files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
SRC = WORKSPACE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from high_velocity_lit.catalog_review import write_catalog_index_outputs  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build literature/catalog_workflow_index.json and literature/catalog_workflow_index.md."
    )
    parser.add_argument("--literature-dir", type=Path, default=WORKSPACE / "literature")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    literature_dir = args.literature_dir.expanduser()
    literature_dir.mkdir(parents=True, exist_ok=True)
    result = write_catalog_index_outputs(literature_dir, workspace=WORKSPACE)
    summary = result["index_record"]["summary"]
    print(
        "Built catalog workflow index: "
        f"{summary['paper_count']} papers, "
        f"{summary['has_catalog_source_count']} with catalog sources, "
        f"{summary['extraction_manifest_count']} extraction manifests, "
        f"{summary['extraction_success_count']} successful extractions, "
        f"{summary['extraction_partial_count']} partial extractions, "
        f"{summary['extraction_failed_count']} failed extractions, "
        f"{summary['needs_review_count']} needing review."
    )
    print(result["index_json_path"])
    print(result["index_markdown_path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
