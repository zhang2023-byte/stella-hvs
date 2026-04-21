#!/usr/bin/env python3
"""Create machine-readable catalog-ingestion scaffolds for a verified paper."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
SRC = WORKSPACE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from high_velocity_lit.catalog_ingest import bootstrap_catalog_ingestion  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bootstrap catalog_ingest JSON scaffolds from literature/<arxiv_id>/record.json."
    )
    parser.add_argument("--arxiv-id", required=True, help="Target literature/<arxiv_id>/record.json.")
    parser.add_argument("--output-dir", type=Path, default=WORKSPACE / "literature")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing catalog_ingest JSON files.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    paper_dir = args.output_dir / args.arxiv_id
    record_path = paper_dir / "record.json"
    if not record_path.exists():
        raise SystemExit(f"Missing verification record: {record_path}")
    result = bootstrap_catalog_ingestion(
        paper_dir=paper_dir,
        workspace_root=WORKSPACE,
        overwrite=args.overwrite,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
