#!/usr/bin/env python3
"""Migrate catalog source field names and TeX evidence source_refs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
SRC = WORKSPACE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from high_velocity_lit.catalog_review import (  # noqa: E402
    migrate_external_resource_source_refs,
    write_catalog_index_outputs,
)


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "t", "1", "yes", "y"}:
        return True
    if normalized in {"false", "f", "0", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError("expected True or False")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Migrate catalog source field names and external_catalog_sources[].local_path TeX evidence into source_refs."
    )
    parser.add_argument("--literature-dir", type=Path, default=WORKSPACE / "literature")
    parser.add_argument("--dry-run", type=parse_bool, default=False, metavar="True|False", help="Report changes without writing JSON. Default: False.")
    parser.add_argument(
        "--rebuild-index",
        type=parse_bool,
        default=True,
        metavar="True|False",
        help="Rebuild literature/catalog_workflow_index.json and .md after writing. Default: True.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    literature_dir = args.literature_dir.expanduser()
    if not literature_dir.exists():
        raise SystemExit(f"literature directory does not exist: {literature_dir}")
    payload = migrate_external_resource_source_refs(literature_dir, dry_run=args.dry_run)
    if args.rebuild_index and not args.dry_run and payload["migrated_count"]:
        index = write_catalog_index_outputs(literature_dir, workspace=WORKSPACE)
        payload["catalog_index_path"] = index["index_json_path"]
        payload["catalog_index_markdown_path"] = index["index_markdown_path"]
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
