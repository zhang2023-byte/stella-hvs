#!/usr/bin/env python3
"""Build the contribution-aware HVS web catalog (pre-gold view)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stella.web.contribution_catalog_site import build_contribution_catalog_site

WORKSPACE = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render the HVS contribution timeline web catalog.",
    )
    parser.add_argument(
        "--catalog-dir",
        type=Path,
        default=WORKSPACE / "catalog" / "contributions",
        help="Directory of hvs_contribution_catalog.object JSON records.",
    )
    parser.add_argument(
        "--web-dir",
        type=Path,
        default=WORKSPACE / "catalog" / "web-contributions",
        help="Output directory for the generated site.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = build_contribution_catalog_site(args.catalog_dir, web_dir=args.web_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
