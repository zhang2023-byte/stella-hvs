#!/usr/bin/env python3
"""Build the static benchmark review site under benchmark/review/."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
SRC = WORKSPACE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stella_benchmark.paths import alignment_index_path, benchmark_root  # noqa: E402
from stella_benchmark.review_site import build_review_site  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build benchmark/review/index.html.")
    parser.add_argument("--benchmark-root", type=Path, default=benchmark_root(WORKSPACE))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.benchmark_root.expanduser()
    index_html = build_review_site(root)
    print(f"review site: {index_html}")
    if not alignment_index_path(root).exists():
        print(
            "warning: no alignment index found; run scripts/benchmark_align_candidates.py first",
            file=sys.stderr,
        )
    print("serve with: conda run -n stella-env python scripts/serve_benchmark_review.py --expert-id <id>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
