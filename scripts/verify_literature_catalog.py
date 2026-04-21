#!/usr/bin/env python3
"""Verify whether a paper contains a catalog via DeepXiv, PDF, and source."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
SRC = WORKSPACE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

try:
    from dotenv import load_dotenv

    for env_path in (Path.home() / ".env", WORKSPACE / ".env", Path.cwd() / ".env"):
        if env_path.exists():
            load_dotenv(env_path, override=True)
except ImportError:
    pass

from high_velocity_lit.arxiv_client import ArxivClient  # noqa: E402
from high_velocity_lit.deepxiv_client import DeepXivClient  # noqa: E402
from high_velocity_lit.literature_catalog import sample_index_md_candidates, verify_paper_catalog  # noqa: E402


def parse_ids(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ids: list[str] = []
    for value in values:
        for part in value.split(","):
            item = part.strip()
            if not item or item in seen:
                continue
            seen.add(item)
            ids.append(item)
    return ids


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Use DeepXiv, PDF, and arXiv source to verify paper-level catalog availability."
    )
    parser.add_argument("--arxiv-id", action="append", default=[], help="One arXiv ID or a comma-separated list.")
    parser.add_argument(
        "--sample-index-md",
        type=int,
        default=0,
        metavar="N",
        help="Randomly sample N entries from notes/index.md and verify them.",
    )
    parser.add_argument("--seed", type=int, default=None, help="Seed for --sample-index-md.")
    parser.add_argument("--index-md", type=Path, default=WORKSPACE / "notes" / "index.md")
    parser.add_argument("--output-dir", type=Path, default=WORKSPACE / "literature")
    parser.add_argument("--force", action="store_true", help="Recompute papers even if literature/<id>/record.json exists.")
    parser.add_argument("--token", default=None, help="Override DEEPXIV_TOKEN.")
    parser.add_argument("--max-sections", type=int, default=4, help="Max DeepXiv sections to read before raw fallback.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    explicit_ids = parse_ids(args.arxiv_id)
    sampled = sample_index_md_candidates(args.index_md, count=args.sample_index_md, seed=args.seed) if args.sample_index_md else []
    ids = explicit_ids + [item["arxiv_id"] for item in sampled if item["arxiv_id"] not in explicit_ids]
    if not ids:
        raise SystemExit("Use --arxiv-id or --sample-index-md to select at least one paper.")
    if args.max_sections < 1:
        raise SystemExit("--max-sections must be at least 1")

    deepxiv_client = DeepXivClient(token=args.token)
    arxiv_client = ArxivClient()
    records = []
    for arxiv_id in ids:
        record = verify_paper_catalog(
            arxiv_id=arxiv_id,
            output_root=args.output_dir,
            deepxiv_client=deepxiv_client,
            arxiv_client=arxiv_client,
            force=args.force,
            max_sections=args.max_sections,
        )
        records.append(
            {
                "arxiv_id": arxiv_id,
                "title": record.get("title"),
                "record_path": str(args.output_dir / arxiv_id / "record.json"),
                "summary_path": str(args.output_dir / arxiv_id / "summary.md"),
                "location": (record.get("catalog") or {}).get("location"),
                "overall_verdict": (record.get("verification") or {}).get("overall_verdict"),
            }
        )

    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "papers": records,
                "sampled_from_index_md": sampled,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
