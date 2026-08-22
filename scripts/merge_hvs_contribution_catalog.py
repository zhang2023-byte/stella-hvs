#!/usr/bin/env python3
"""Merge the object-level HVS contribution timeline catalog."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stella.lit.hvs_contribution_catalog import write_contribution_catalog

WORKSPACE = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rebuild per-object HVS contribution timelines.",
    )
    parser.add_argument(
        "--literature-dir",
        type=Path,
        default=WORKSPACE / "literature",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=WORKSPACE / "catalog" / "contributions",
        help="Output directory for per-object records and the catalog index.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = write_contribution_catalog(
        args.literature_dir, output_dir=args.output_dir
    )
    print(
        json.dumps(
            {
                "object_count": result["object_count"],
                "index_path": result["index_path"],
                "output_dir": result["output_dir"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
