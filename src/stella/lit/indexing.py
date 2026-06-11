"""Collection-level yearly index rebuilt from canonical monthly JSON records."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .note_paths import iter_month_json_paths
from .records import (
    INDEX_SCHEMA_VERSION,
    MONTH_SCHEMA_VERSION,
    has_observational_catalog,
    month_json_navigation_path,
    note_navigation_path,
)
from .markdown import render_index

NOTES_INDEX_JSON_FILENAME = "00_literature_notes_index.json"
NOTES_INDEX_MARKDOWN_FILENAME = "00_literature_notes_index.md"
LEGACY_NOTES_INDEX_JSON_FILENAMES = ("literature_notes_index.json", "index.json")
LEGACY_NOTES_INDEX_MARKDOWN_FILENAMES = ("literature_notes_index.md",)
LEGACY_NOTES_INDEX_JSON_FILENAME = "index.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _paper_sort_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("published_at") or ""),
        str(item.get("month") or ""),
        str(item.get("title") or ""),
    )


def _index_paper_item(paper: dict[str, Any], *, month: str) -> dict[str, Any]:
    assessment = paper.get("catalog_assessment") or {}
    item = {
        "title": str(paper.get("title") or "Untitled"),
        "arxiv_id": str(paper.get("arxiv_id") or ""),
        "month": month,
        "published_at": str(paper.get("published_at") or ""),
        "navigation_path": note_navigation_path(month),
        "json_path": month_json_navigation_path(month),
        "links": paper.get("links") or {},
        "has_observational_catalog": assessment.get("has_observational_catalog") is True,
    }
    return item


def rebuild_index(notes_dir: Path) -> dict[str, Any]:
    years: dict[str, dict[str, Any]] = {}
    flat_papers: list[dict[str, Any]] = []
    total_literature_count = 0
    total_data_related_count = 0

    for json_path in iter_month_json_paths(notes_dir):
        record = read_json(json_path)
        month = str(record.get("month") or json_path.stem)
        year = month[:4] or str(record.get("date_from") or "")[:4]
        year_bucket = years.setdefault(
            year,
            {
                "year": year,
                "literature_count": 0,
                "data_related_count": 0,
                "data_related_papers": [],
            },
        )

        papers = record.get("papers") or []
        literature_count = len(papers)
        year_bucket["literature_count"] += literature_count
        total_literature_count += literature_count

        for paper in papers:
            if not isinstance(paper, dict):
                continue
            item = _index_paper_item(paper, month=month)
            flat_papers.append(item)
            if not has_observational_catalog(paper):
                continue
            year_bucket["data_related_papers"].append(item)
            year_bucket["data_related_count"] += 1
            total_data_related_count += 1

    year_records = []
    for year in sorted(years.keys(), reverse=True):
        bucket = years[year]
        bucket["data_related_papers"].sort(key=_paper_sort_key, reverse=True)
        year_records.append(bucket)
    flat_papers.sort(key=_paper_sort_key, reverse=True)

    return {
        "schema_version": INDEX_SCHEMA_VERSION,
        "month_schema_version": MONTH_SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "notes_dir": str(notes_dir),
        "summary": {
            "year_count": len(year_records),
            "literature_count": total_literature_count,
            "data_related_count": total_data_related_count,
        },
        "years": year_records,
        "papers": flat_papers,
    }


def write_index_outputs(notes_dir: Path) -> dict[str, Any]:
    index_record = rebuild_index(notes_dir)
    write_json(notes_dir / NOTES_INDEX_JSON_FILENAME, index_record)
    for filename in LEGACY_NOTES_INDEX_JSON_FILENAMES:
        (notes_dir / filename).unlink(missing_ok=True)
    return index_record


def refresh_index_outputs(notes_dir: Path) -> dict[str, Any]:
    index_record = write_index_outputs(notes_dir)
    index_json_path = notes_dir / NOTES_INDEX_JSON_FILENAME
    index_markdown_path = notes_dir / NOTES_INDEX_MARKDOWN_FILENAME
    index_markdown_path.write_text(render_index(index_record), encoding="utf-8")
    for filename in LEGACY_NOTES_INDEX_MARKDOWN_FILENAMES:
        (notes_dir / filename).unlink(missing_ok=True)
    return {
        "index_record": index_record,
        "index_json_path": str(index_json_path),
        "index_markdown_path": str(index_markdown_path),
    }
