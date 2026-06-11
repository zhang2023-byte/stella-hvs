#!/usr/bin/env python3
"""Pull local literature assets for data-related papers recorded in notes/."""

from __future__ import annotations

import argparse
import calendar
import json
import re
from datetime import date
from pathlib import Path

import requests

WORKSPACE = Path(__file__).resolve().parents[1]

from stella.lit.literature_assets import (  # noqa: E402
    DEFAULT_TIMEOUT,
    DEFAULT_USER_AGENT,
    archive_paper,
    load_data_related_papers,
)
from stella.lit.env import env_value, load_env_files  # noqa: E402
from stella.lit.note_paths import resolve_month_json_path  # noqa: E402


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
YEAR_RE = re.compile(r"^\d{4}$")
ARXIV_ID_RE = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")


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
    del from_value
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


def parse_on_value(value: str) -> list[str]:
    text = value.strip()
    if not text:
        raise ValueError("--on cannot be empty")
    if text.startswith("[") or text.endswith("]") or text.lower().startswith("list:"):
        raise ValueError("--on must be either YYYY-MM or comma-separated YYYY-MM values")
    return [validate_month_slug(item) for item in (part.strip() for part in text.split(",")) if item]


def parse_arxiv_ids(value: str) -> list[str]:
    ids: list[str] = []
    for item in (part.strip() for part in value.split(",")):
        if not item:
            continue
        if not ARXIV_ID_RE.fullmatch(item):
            raise ValueError(f"--arxiv-id values must look like 2401.10635 or 2401.10635v1; got {item!r}")
        ids.append(item)
    if not ids:
        raise ValueError("--arxiv-id cannot be empty")
    return ids


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pull local assets for data-related papers recorded in notes/.")
    parser.add_argument("--from", dest="from_value", default=None, metavar="DATE", help="Select note months from YYYY-MM-DD, YYYY-MM, or YYYY.")
    parser.add_argument("--to", dest="to_value", default=None, metavar="DATE", help="Select note months through YYYY-MM-DD, YYYY-MM, YYYY, or none.")
    parser.add_argument("--on", action="append", default=[], metavar="MONTH[,MONTH...]", help="Select note months. Use YYYY-MM or comma-separated YYYY-MM values.")
    parser.add_argument("--arxiv-id", default=None, metavar="ID[,ID...]", help="Select specific arXiv IDs instead of months.")
    parser.add_argument("--notes-dir", type=Path, default=WORKSPACE / "notes")
    parser.add_argument("--literature-dir", type=Path, default=WORKSPACE / "literature")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--ads-token", default=None, help="ADS API token. Defaults to ADS_API_TOKEN or ADS_TOKEN from env files.")
    parser.add_argument("--dry-run", type=parse_bool, default=False, metavar="True|False", help="Resolve targets without downloading files. Default: False.")
    return parser


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": DEFAULT_USER_AGENT})
    return session


def select_month_slugs(args: argparse.Namespace) -> list[str]:
    selected: list[str] = []
    if args.on:
        if len(args.on) > 1:
            raise SystemExit("Use a single --on value: YYYY-MM or comma-separated YYYY-MM values.")
        if args.from_value or args.to_value:
            raise SystemExit("--on cannot be combined with --from/--to")
        selected.extend(parse_on_value(args.on[0]))
    if args.from_value:
        start_date = parse_period(args.from_value, kind="from")
        end_date = parse_period(args.to_value, kind="to") if args.to_value else infer_period_end(args.from_value)
        if start_date > end_date:
            raise SystemExit(f"--from date {start_date.isoformat()} is after --to date {end_date.isoformat()}")
        selected.extend(month_slugs(start_date, end_date))
    elif args.to_value:
        raise SystemExit("--to requires --from")
    return sorted(dict.fromkeys(selected))


def main() -> int:
    args = build_parser().parse_args()
    if args.timeout < 1:
        raise SystemExit("--timeout must be at least 1")
    load_env_files(WORKSPACE)
    if args.arxiv_id and (args.on or args.from_value or args.to_value):
        raise SystemExit("--arxiv-id cannot be combined with --on or --from/--to")

    notes_dir = args.notes_dir.expanduser()
    literature_dir = args.literature_dir.expanduser()
    all_selected = load_data_related_papers(notes_dir)
    ads_token = args.ads_token if args.ads_token is not None else env_value("ADS_API_TOKEN", "ADS_TOKEN")
    chosen_ids: list[str] = []
    skipped: list[dict[str, str]] = []

    if args.arxiv_id:
        for arxiv_id in parse_arxiv_ids(args.arxiv_id):
            selected = all_selected.get(arxiv_id)
            if selected is not None:
                chosen_ids.append(arxiv_id)
                continue
            found_any = False
            for month_path in notes_dir.glob("20[0-9][0-9]/20[0-9][0-9]-[01][0-9]/*.json"):
                if month_path.name.endswith(".title-triage.json"):
                    continue
                record = json.loads(month_path.read_text(encoding="utf-8"))
                for paper in record.get("papers") or []:
                    if isinstance(paper, dict) and str(paper.get("arxiv_id") or "").strip() == arxiv_id:
                        found_any = True
                        break
                if found_any:
                    break
            skipped.append({"arxiv_id": arxiv_id, "reason": "not-data-related" if found_any else "not-found"})
    else:
        month_slugs_selected = select_month_slugs(args)
        if not month_slugs_selected:
            raise SystemExit("Use --arxiv-id, --on, or --from/--to to select data-related papers.")
        for month_slug in month_slugs_selected:
            month_path = resolve_month_json_path(notes_dir, month_slug)
            if not month_path.exists():
                skipped.append({"month": month_slug, "reason": "month-json-missing"})
                continue
            record = json.loads(month_path.read_text(encoding="utf-8"))
            for paper in record.get("papers") or []:
                if not isinstance(paper, dict):
                    continue
                arxiv_id = str(paper.get("arxiv_id") or "").strip()
                if arxiv_id and arxiv_id in all_selected:
                    chosen_ids.append(arxiv_id)

    chosen_ids = sorted(dict.fromkeys(chosen_ids))
    selected_papers = [all_selected[arxiv_id] for arxiv_id in chosen_ids]
    results: list[dict[str, object]] = []

    if not args.dry_run:
        literature_dir.mkdir(parents=True, exist_ok=True)
        session = build_session()
        for selected in selected_papers:
            results.append(
                archive_paper(
                    selected,
                    workspace=WORKSPACE,
                    literature_dir=literature_dir,
                    session=session,
                    timeout=args.timeout,
                    ads_token=ads_token,
                )
            )
    else:
        for selected in selected_papers:
            paper = selected.paper
            results.append(
                {
                    "arxiv_id": str(paper.get("arxiv_id") or ""),
                    "month": selected.month,
                    "title": str(paper.get("title") or ""),
                    "source_note_json": str(selected.note_json_path),
                }
            )

    summary = {
        "selected_count": len(selected_papers),
        "skipped_count": len(skipped),
        "arxiv_abs_success": sum(1 for item in results if item.get("arxiv_abs") is True),
        "arxiv_pdf_success": sum(1 for item in results if item.get("arxiv_pdf") is True),
        "arxiv_source_success": sum(1 for item in results if item.get("arxiv_source") is True),
        "arxiv_source_extracted_success": sum(1 for item in results if item.get("arxiv_source_extracted") is True),
        "ads_bibcode_success": sum(1 for item in results if item.get("ads_bibcode") is True),
    }
    payload = {
        "dry_run": args.dry_run,
        "notes_dir": str(notes_dir),
        "literature_dir": str(literature_dir),
        "selected": results,
        "skipped": skipped,
        "summary": summary,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
