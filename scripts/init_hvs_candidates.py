#!/usr/bin/env python3
"""Generate a strict literature_hvs_candidates.json skeleton for one archived paper."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
SRC = WORKSPACE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from high_velocity_lit.schema_templates import build_hvs_candidates_template  # noqa: E402


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "t", "1", "yes", "y"}:
        return True
    if normalized in {"false", "f", "0", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError("expected True or False")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Initialize literature/<arxiv-id>/literature_hvs_candidates.json from code schema."
    )
    parser.add_argument("--arxiv-id", required=True)
    parser.add_argument("--literature-dir", type=Path, default=WORKSPACE / "literature")
    parser.add_argument("--overwrite", type=parse_bool, default=False, metavar="True|False")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    literature_dir = args.literature_dir.expanduser()
    paper_dir = literature_dir / args.arxiv_id
    if not paper_dir.exists():
        raise SystemExit(f"paper directory does not exist: {paper_dir}")
    review_path = paper_dir / "catalog_review.json"
    extraction_path = paper_dir / "catalog_extraction.json"
    if not review_path.exists():
        raise SystemExit(f"catalog review does not exist: {review_path}")
    if not extraction_path.exists():
        raise SystemExit(f"catalog extraction does not exist: {extraction_path}")

    output_path = paper_dir / "literature_hvs_candidates.json"
    if output_path.exists() and not args.overwrite:
        raise SystemExit(f"refusing to overwrite existing file: {output_path}")

    payload = build_hvs_candidates_template(
        literature_dir=literature_dir,
        arxiv_id=args.arxiv_id,
        workspace=WORKSPACE,
    )
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
