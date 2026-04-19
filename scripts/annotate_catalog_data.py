#!/usr/bin/env python3
"""Annotate a literature note JSON with observational catalog assessments."""

from __future__ import annotations

import argparse
import calendar
import json
import os
import re
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

from high_velocity_lit.catalog_assessment import LLMCatalogAssessor, annotate_record  # noqa: E402
from high_velocity_lit.config import DEFAULT_LLM_BASE_URL, DEFAULT_LLM_BATCH_SIZE, DEFAULT_LLM_MODEL  # noqa: E402
from high_velocity_lit.markdown import render_month_note  # noqa: E402
from high_velocity_lit.title_classifier import load_llm_api_key  # noqa: E402


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


def parse_period(value: str, *, kind: str, today: date | None = None) -> date:
    today = today or date.today()
    text = value.strip()
    if kind == "to" and text.lower() in {"none", "today"}:
        return today

    try:
        if DATE_RE.fullmatch(text):
            parsed = date.fromisoformat(text)
        elif MONTH_RE.fullmatch(text):
            year, month = (int(part) for part in text.split("-"))
            day = 1 if kind == "from" else calendar.monthrange(year, month)[1]
            parsed = date(year, month, day)
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

    return min(parsed, today)


def infer_period_end(from_value: str, *, today: date | None = None) -> date:
    return today or date.today()


def validate_month_slug(value: str) -> str:
    text = value.strip()
    if not MONTH_RE.fullmatch(text):
        raise ValueError(f"--on values must be YYYY-MM; got {value!r}")
    year, month = (int(part) for part in text.split("-"))
    try:
        date(year, month, 1)
    except ValueError as exc:
        raise ValueError(f"--on values must be valid months; got {value!r}") from exc
    return text


def parse_on_values(values: list[str]) -> list[str]:
    slugs: list[str] = []
    for value in values:
        text = value.strip()
        if text.lower().startswith("list:"):
            text = text[5:].strip()
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1]
        for item in re.split(r"[,\s]+", text):
            if item.strip():
                slugs.append(validate_month_slug(item))
    return slugs


def month_slugs(start: date, end: date) -> list[str]:
    year = start.year
    month = start.month
    slugs: list[str] = []
    while (year, month) <= (end.year, end.month):
        slugs.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            month = 1
            year += 1
    return slugs


def json_paths_from_range(notes_dir: Path, start: date, end: date) -> list[Path]:
    return [notes_dir / slug / f"{slug}.json" for slug in month_slugs(start, end)]


def json_paths_from_months(notes_dir: Path, slugs: list[str]) -> list[Path]:
    return [notes_dir / slug / f"{slug}.json" for slug in slugs]


def unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        resolved = path.expanduser()
        key = resolved.resolve() if resolved.exists() else resolved.absolute()
        if key not in seen:
            seen.add(key)
            unique.append(resolved)
    return unique


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, record: dict[str, object]) -> None:
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def markdown_path_for(json_path: Path, record: dict[str, object]) -> Path:
    month = str(record.get("month") or json_path.stem)
    return json_path.with_name(f"{month}.md")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Use an LLM to annotate whether note papers contain observational high-velocity-star catalog data."
    )
    parser.add_argument(
        "--from",
        dest="from_value",
        default=None,
        metavar="DATE",
        help="Select note months from YYYY-MM-DD, YYYY-MM, or YYYY through today unless --to is set.",
    )
    parser.add_argument("--to", dest="to_value", default=None, metavar="DATE", help="Select note months through YYYY-MM-DD, YYYY-MM, YYYY, or none.")
    parser.add_argument(
        "--on",
        action="append",
        default=[],
        metavar="MONTHS",
        help="Select specific note months. Supports YYYY-MM, repeated --on, comma lists, or 'list:[YYYY-MM,YYYY-MM]'.",
    )
    parser.add_argument("--notes-dir", type=Path, default=WORKSPACE / "notes")
    parser.add_argument("--llm-api-key", default=os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("DEEPXIV_AGENT_API_KEY"))
    parser.add_argument("--llm-base-url", default=os.environ.get("LLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or os.environ.get("DEEPXIV_AGENT_BASE_URL") or DEFAULT_LLM_BASE_URL)
    parser.add_argument("--llm-model", default=os.environ.get("LLM_MODEL") or os.environ.get("OPENAI_MODEL") or os.environ.get("DEEPXIV_AGENT_MODEL") or DEFAULT_LLM_MODEL)
    parser.add_argument("--llm-batch-size", type=int, default=DEFAULT_LLM_BATCH_SIZE)
    parser.add_argument("--force", type=parse_bool, default=False, metavar="True|False", help="Recompute existing assessments. Default: False.")
    parser.add_argument("--render", type=parse_bool, default=True, metavar="True|False", help="Refresh sibling Markdown file. Default: True.")
    parser.add_argument("--dry-run", type=parse_bool, default=False, metavar="True|False", help="Run assessment without writing files. Default: False.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.llm_batch_size < 1:
        raise SystemExit("--llm-batch-size must be at least 1")
    selected_paths: list[Path] = []
    if args.on:
        try:
            selected_paths.extend(json_paths_from_months(args.notes_dir, parse_on_values(args.on)))
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    if args.from_value:
        try:
            start_date = parse_period(args.from_value, kind="from")
            end_date = parse_period(args.to_value, kind="to") if args.to_value else infer_period_end(args.from_value)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        if start_date > end_date:
            raise SystemExit(f"--from date {start_date.isoformat()} is after --to date {end_date.isoformat()}")
        selected_paths.extend(json_paths_from_range(args.notes_dir, start_date, end_date))
    elif args.to_value:
        raise SystemExit("--to requires --from")

    selected_paths = unique_paths(selected_paths)
    if not selected_paths:
        raise SystemExit("Use --on to select specific note months, or --from/--to to select a date range.")
    missing_paths = [path for path in selected_paths if not path.exists()]
    if missing_paths:
        missing = "\n".join(str(path) for path in missing_paths)
        raise SystemExit(f"JSON file(s) do not exist:\n{missing}")

    api_key = load_llm_api_key(args.llm_api_key)
    if not api_key:
        raise SystemExit("Catalog assessment requires LLM_API_KEY, OPENAI_API_KEY, DEEPXIV_AGENT_API_KEY, or --llm-api-key.")

    assessor = LLMCatalogAssessor(
        api_key=api_key,
        base_url=args.llm_base_url,
        model=args.llm_model,
    )
    results: list[dict[str, object]] = []
    totals = {"pending": 0, "assessed": 0, "missing": 0, "catalog_count": 0}
    for json_path in selected_paths:
        record = read_json(json_path)
        summary = annotate_record(
            record,
            assessor,
            batch_size=args.llm_batch_size,
            method="llm",
            model=args.llm_model,
            force=args.force,
        )
        markdown_path = markdown_path_for(json_path, record)
        if not args.dry_run:
            write_json(json_path, record)
            if args.render:
                markdown_path.write_text(render_month_note(record), encoding="utf-8")
        for key in totals:
            totals[key] += int(summary[key])
        results.append(
            {
                "json_path": str(json_path),
                "markdown_path": str(markdown_path) if args.render else None,
                **summary,
            }
        )

    output = {"dry_run": args.dry_run, "files": results, "totals": totals}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
