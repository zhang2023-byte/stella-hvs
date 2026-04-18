#!/usr/bin/env python3
"""Fetch monthly high-velocity star literature notes from DeepXiv."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
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

from high_velocity_lit.config import (  # noqa: E402
    DEFAULT_CATEGORIES,
    DEFAULT_CLASSIFIER,
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_BATCH_SIZE,
    DEFAULT_LLM_MODEL,
    DEFAULT_MAX_RESULTS,
    DEFAULT_QUERIES,
    DEFAULT_BRIEF_SLEEP_SECONDS,
    DEFAULT_SOURCE,
    DEFAULT_SEARCH_MODE,
    DEFAULT_SEARCH_SLEEP_SECONDS,
)
from high_velocity_lit.models import SearchConfig  # noqa: E402
from high_velocity_lit.pipeline import run_pipeline  # noqa: E402


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def load_queries(query_file: Path | None, extra_queries: list[str]) -> list[str]:
    queries = list(DEFAULT_QUERIES)
    if query_file:
        queries = [
            line.strip()
            for line in query_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    queries.extend(query.strip() for query in extra_queries if query.strip())

    seen: set[str] = set()
    unique: list[str] = []
    for query in queries:
        key = query.lower()
        if key not in seen:
            seen.add(key)
            unique.append(query)
    return unique


def split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect monthly DeepXiv/arXiv notes for high-velocity star literature."
    )
    parser.add_argument("--start-year", type=int, default=2025)
    parser.add_argument("--start-month", type=int, default=1)
    parser.add_argument("--end-year", type=int, default=2026)
    parser.add_argument("--end-month", type=int, default=4)
    parser.add_argument("--end-date", default=None, help="Optional cap for the final month, YYYY-MM-DD.")
    parser.add_argument("--source", default=DEFAULT_SOURCE, choices=["deepxiv", "arxiv"], help="Candidate search backend.")
    parser.add_argument("--max-results", type=int, default=DEFAULT_MAX_RESULTS)
    parser.add_argument("--search-mode", default=DEFAULT_SEARCH_MODE, choices=["bm25", "vector", "hybrid"])
    parser.add_argument(
        "--categories",
        default=",".join(DEFAULT_CATEGORIES),
        help="Comma-separated arXiv categories. Empty string disables category filtering.",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=None,
        help="Optional DeepXiv score floor. Default is no score floor to avoid missing papers.",
    )
    parser.add_argument(
        "--classifier",
        default=DEFAULT_CLASSIFIER,
        choices=["llm", "rules", "none"],
        help="How to confirm candidate relevance before brief. Default: rules.",
    )
    parser.add_argument("--llm-api-key", default=os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("DEEPXIV_AGENT_API_KEY"))
    parser.add_argument("--llm-base-url", default=os.environ.get("LLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or os.environ.get("DEEPXIV_AGENT_BASE_URL") or DEFAULT_LLM_BASE_URL)
    parser.add_argument("--llm-model", default=os.environ.get("LLM_MODEL") or os.environ.get("OPENAI_MODEL") or os.environ.get("DEEPXIV_AGENT_MODEL") or DEFAULT_LLM_MODEL)
    parser.add_argument("--llm-batch-size", type=int, default=DEFAULT_LLM_BATCH_SIZE)
    parser.add_argument(
        "--llm-review-weak",
        action="store_true",
        help="With --classifier rules, send weak rule matches to the LLM for confirmation.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=DEFAULT_SEARCH_SLEEP_SECONDS,
        help="Seconds to sleep between candidate search calls.",
    )
    parser.add_argument(
        "--brief-sleep",
        type=float,
        default=DEFAULT_BRIEF_SLEEP_SECONDS,
        help="Seconds to sleep between DeepXiv brief calls.",
    )
    parser.add_argument("--query-file", type=Path, default=None, help="One query per line. Replaces defaults.")
    parser.add_argument("--extra-query", action="append", default=[], help="Add an extra query. Can be repeated.")
    parser.add_argument("--no-brief", action="store_true", help="Skip DeepXiv brief calls and use search metadata only.")
    parser.add_argument("--token", default=None, help="Optional DeepXiv token. Defaults to DEEPXIV_TOKEN from loaded .env files.")
    parser.add_argument("--notes-dir", type=Path, default=WORKSPACE / "notes")
    parser.add_argument("--logs-dir", type=Path, default=WORKSPACE / "logs")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    queries = load_queries(args.query_file, args.extra_query)
    config = SearchConfig(
        workspace=WORKSPACE,
        notes_dir=args.notes_dir,
        logs_dir=args.logs_dir,
        start_year=args.start_year,
        start_month=args.start_month,
        end_year=args.end_year,
        end_month=args.end_month,
        end_date=parse_date(args.end_date),
        source=args.source,
        queries=queries,
        categories=split_csv(args.categories),
        max_results=args.max_results,
        search_mode=args.search_mode,
        min_score=args.min_score,
        classifier=args.classifier,
        llm_api_key=args.llm_api_key,
        llm_base_url=args.llm_base_url,
        llm_model=args.llm_model,
        llm_batch_size=args.llm_batch_size,
        llm_review_weak=args.llm_review_weak,
        search_sleep_seconds=args.sleep,
        brief_sleep_seconds=args.brief_sleep,
        use_brief=not args.no_brief,
        token=args.token,
    )
    summary = run_pipeline(config)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
