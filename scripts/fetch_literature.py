#!/usr/bin/env python3
"""Fetch monthly high-velocity star literature notes."""

from __future__ import annotations

import argparse
import calendar
import json
import re
import sys
from datetime import date
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]

from stella.lit.config import (  # noqa: E402
    DEFAULT_CATEGORIES,
    DEFAULT_DEEPXIV_LLM_REVIEW_MAX_CANDIDATES,
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_BATCH_SIZE,
    DEFAULT_LLM_MODEL,
    DEFAULT_MAX_RESULTS,
    DEFAULT_QUERIES,
    DEFAULT_SOURCE,
    DEFAULT_SEARCH_MODE,
    DEFAULT_SEARCH_SLEEP_SECONDS,
)
from stella.lit.env import env_value, load_env_files  # noqa: E402
from stella.lit.models import SearchConfig  # noqa: E402
from stella.lit.pipeline import PartialRunError, run_pipeline  # noqa: E402

load_env_files(WORKSPACE)


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
YEAR_RE = re.compile(r"^\d{4}$")


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "t", "1", "yes", "y"}:
        return True
    if normalized in {"false", "f", "0", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError("expected True or False")


def parse_period(value: str | None, *, kind: str, today: date | None = None) -> date:
    today = today or date.today()
    if value is None:
        if kind == "to":
            return today
        raise ValueError("--from is required")

    text = value.strip()
    if kind == "to" and text.lower() in {"none", "today"}:
        return today

    try:
        if DATE_RE.fullmatch(text):
            parsed = date.fromisoformat(text)
        elif MONTH_RE.fullmatch(text):
            year, month = (int(part) for part in text.split("-"))
            if kind == "from":
                parsed = date(year, month, 1)
            else:
                parsed = date(year, month, calendar.monthrange(year, month)[1])
        elif YEAR_RE.fullmatch(text):
            year = int(text)
            parsed = date(year, 1, 1) if kind == "from" else date(year, 12, 31)
        else:
            raise ValueError
    except ValueError as exc:
        expected = "YYYY-MM-DD, YYYY-MM, or YYYY"
        if kind == "to":
            expected += ", or none"
        raise ValueError(f"--{kind} must be {expected}; got {value!r}") from exc

    if parsed > today:
        return today
    return parsed


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


def print_partial_notice(summary: dict[str, object]) -> None:
    completed = summary.get("completed_months") or []
    if isinstance(completed, list) and completed:
        completed_text = f"{completed[0]} to {completed[-1]}" if len(completed) > 1 else str(completed[0])
    else:
        completed_text = "none"

    sys.stderr.write("\nAPI rate limit reached. Partial results were saved.\n")
    sys.stderr.write(f"Completed months: {completed_text}\n")
    sys.stderr.write(f"Partial summary: {summary.get('partial_summary_path')}\n")
    sys.stderr.write(f"Run log: {summary.get('run_log')}\n")
    sys.stderr.write(f"Resume from: {summary.get('resume_from')}\n")
    sys.stderr.write("Resume command:\n")
    sys.stderr.write(str(summary.get("resume_command")) + "\n")
    sys.stderr.flush()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect monthly arXiv/DeepXiv notes for high-velocity star literature."
    )
    parser.add_argument(
        "--from",
        dest="from_value",
        required=True,
        metavar="DATE",
        help="Start date as YYYY-MM-DD, YYYY-MM, or YYYY.",
    )
    parser.add_argument(
        "--to",
        dest="to_value",
        default=None,
        metavar="DATE",
        help="End date as YYYY-MM-DD, YYYY-MM, YYYY, or none. Default: today.",
    )
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
    parser.add_argument("--llm-api-key", default=env_value("LLM_API_KEY", "OPENAI_API_KEY", "DEEPXIV_AGENT_API_KEY"))
    parser.add_argument("--llm-base-url", default=env_value("LLM_BASE_URL", "OPENAI_BASE_URL", "DEEPXIV_AGENT_BASE_URL", default=DEFAULT_LLM_BASE_URL))
    parser.add_argument("--llm-model", default=env_value("LLM_MODEL", "OPENAI_MODEL", "DEEPXIV_AGENT_MODEL", default=DEFAULT_LLM_MODEL))
    parser.add_argument("--llm-batch-size", type=int, default=DEFAULT_LLM_BATCH_SIZE)
    parser.add_argument(
        "--deepxiv-llm-review-max-candidates",
        type=int,
        default=DEFAULT_DEEPXIV_LLM_REVIEW_MAX_CANDIDATES,
        help=(
            "For --source deepxiv, review at most this many no-clear-title-evidence "
            "candidates with the LLM after dedupe/filtering, sorted by DeepXiv score. Default: 20."
        ),
    )
    parser.add_argument(
        "--llm-review",
        type=parse_bool,
        default=False,
        metavar="True|False",
        help="Review titles without clear evidence using the LLM. Default: False.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=DEFAULT_SEARCH_SLEEP_SECONDS,
        help="Seconds to sleep between candidate search calls.",
    )
    parser.add_argument("--query-file", type=Path, default=None, help="One query per line. Replaces defaults.")
    parser.add_argument("--extra-query", action="append", default=[], help="Add an extra query. Can be repeated.")
    parser.add_argument("--progress", type=parse_bool, default=True, metavar="True|False", help="Show terminal progress bars. Default: True.")
    parser.add_argument("--token", default=None, help="Optional DeepXiv token for --source deepxiv.")
    parser.add_argument("--notes-dir", type=Path, default=WORKSPACE / "notes")
    parser.add_argument("--logs-dir", type=Path, default=WORKSPACE / "logs")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        start_date = parse_period(args.from_value, kind="from")
        end_date = parse_period(args.to_value, kind="to")
    except ValueError as exc:
        parser.error(str(exc))
    if start_date > end_date:
        parser.error(f"--from date {start_date.isoformat()} is after --to date {end_date.isoformat()}")
    if args.max_results < 1:
        parser.error("--max-results must be at least 1")
    if args.deepxiv_llm_review_max_candidates < 1:
        parser.error("--deepxiv-llm-review-max-candidates must be at least 1")
    if args.llm_review:
        if not args.llm_api_key:
            parser.error("--llm-review True requires LLM_API_KEY or --llm-api-key")

    queries = load_queries(args.query_file, args.extra_query)
    config = SearchConfig(
        workspace=WORKSPACE,
        notes_dir=args.notes_dir,
        logs_dir=args.logs_dir,
        start_date=start_date,
        end_date=end_date,
        source=args.source,
        queries=queries,
        categories=split_csv(args.categories),
        max_results=args.max_results,
        search_mode=args.search_mode,
        min_score=args.min_score,
        llm_api_key=args.llm_api_key,
        llm_base_url=args.llm_base_url,
        llm_model=args.llm_model,
        llm_batch_size=args.llm_batch_size,
        llm_review=args.llm_review,
        search_sleep_seconds=args.sleep,
        progress=args.progress,
        deepxiv_llm_review_max_candidates=args.deepxiv_llm_review_max_candidates,
        token=args.token,
    )
    try:
        summary = run_pipeline(config)
    except PartialRunError as exc:
        print_partial_notice(exc.summary)
        print(json.dumps(exc.summary, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
