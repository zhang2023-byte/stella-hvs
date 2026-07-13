#!/usr/bin/env python3
"""Regenerate committed HVS extraction rule views from YAML profiles."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]

from stella.lit.extraction_rules import (  # noqa: E402
    stale_generated_rule_views,
    write_generated_rule_views,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate SKILL.md and Guideline rule blocks from extraction-rule YAML."
    )
    parser.add_argument(
        "--check", action="store_true", help="Exit non-zero when committed views are stale."
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.check:
        stale = stale_generated_rule_views(WORKSPACE)
        for path in stale:
            print(f"extraction rule view is stale: {path}", file=sys.stderr)
        return 1 if stale else 0
    for path in write_generated_rule_views(WORKSPACE):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
