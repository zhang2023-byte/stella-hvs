"""Canonical JSON records for Stella literature outputs."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .models import MonthWindow, SearchConfig
from .note_paths import month_json_path, month_markdown_path


MONTH_SCHEMA_VERSION = "stella.literature.month.v3"
INDEX_SCHEMA_VERSION = "stella.literature.index.v4"
TITLE_TRIAGE_SCHEMA_VERSION = "stella.literature.title_triage.v1"


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(as_text(item) for item in value if item)
    return str(value)


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return sorted(value)
    text = str(value).strip()
    return [text] if text else []


def first_present(*values: Any) -> str:
    for value in values:
        text = as_text(value).strip()
        if text:
            return text
    return ""


def as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def paper_url(arxiv_id: str) -> str:
    return f"https://arxiv.org/abs/{arxiv_id}"


def pdf_url(arxiv_id: str) -> str:
    return f"https://arxiv.org/pdf/{arxiv_id}"


def note_navigation_path(month: str) -> str:
    return str(month_markdown_path(Path("."), month))


def month_json_navigation_path(month: str) -> str:
    return str(month_json_path(Path("."), month))


def has_observational_catalog(paper: dict[str, Any]) -> bool:
    assessment = paper.get("catalog_assessment") or {}
    return assessment.get("has_observational_catalog") is True


def source_field_record(paper: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "id",
        "arxiv_id",
        "title",
        "abstract",
        "summary",
        "author_names",
        "authors",
        "categories",
        "publish_at",
        "published_at",
        "published",
        "updated_at",
        "updated",
        "score",
        "citation",
        "citations",
        "keywords",
        "source",
        "tldr",
    }
    return {key: value for key, value in paper.items() if not key.startswith("_") and key not in normalized}


def base_paper_record(paper: dict[str, Any], *, config: SearchConfig, run_id: str) -> dict[str, Any]:
    arxiv_id = first_present(paper.get("arxiv_id"), paper.get("id"))
    abstract = first_present(paper.get("abstract"), paper.get("summary"))
    best_score = as_float(first_present(paper.get("_best_score"), paper.get("score")))
    source_score = as_float(paper.get("score"))
    citations = first_present(paper.get("citations"), paper.get("citation"))
    search_source = first_present(paper.get("_search_source"), config.source)
    published_at = first_present(
        paper.get("publish_at"),
        paper.get("published_at"),
        paper.get("published"),
    )

    record = {
        "arxiv_id": arxiv_id,
        "title": first_present(paper.get("title"), "Untitled"),
        "authors": as_list(paper.get("authors")),
        "author_names": first_present(paper.get("author_names"), paper.get("authors")),
        "categories": as_list(paper.get("categories")),
        "published_at": published_at,
        "updated_at": first_present(paper.get("updated_at"), paper.get("updated")),
        "links": {
            "abs": paper_url(arxiv_id) if arxiv_id else "",
            "pdf": pdf_url(arxiv_id) if arxiv_id else "",
        },
        "abstract": {
            "source": search_source if abstract else None,
            "text": abstract,
        },
        "match": {
            "queries": as_list(paper.get("_matched_queries")),
            "categories": as_list(paper.get("_matched_categories")),
            "best_score": best_score,
        },
        "deepxiv": {
            "score": source_score,
            "best_score": best_score,
            "search_keywords": paper.get("keywords"),
            "citations": citations,
        },
        "provenance": {
            "search_source": search_source,
            "run_id": run_id,
        },
    }
    if search_source != config.source:
        record["provenance"]["configured_search_source"] = config.source
    if first_present(paper.get("_fallback_from")):
        record["provenance"]["fallback_from"] = first_present(paper.get("_fallback_from"))
    raw_fields = source_field_record(paper)
    if raw_fields:
        record["source_fields"] = raw_fields
    return record


def paper_record(paper: dict[str, Any], *, config: SearchConfig, run_id: str) -> dict[str, Any]:
    return base_paper_record(paper, config=config, run_id=run_id)


def title_triage_record(paper: dict[str, Any], *, config: SearchConfig, run_id: str) -> dict[str, Any]:
    record = base_paper_record(paper, config=config, run_id=run_id)
    triage = paper.get("_title_triage") or {}
    review = paper.get("_review") or {}
    record["title_triage"] = {
        "label": first_present(triage.get("label")),
        "confidence": as_float(triage.get("confidence")),
        "reason": first_present(triage.get("reason")),
    }
    if review:
        record["review"] = {
            "status": first_present(review.get("status")),
            "confidence": as_float(review.get("confidence")),
            "reason": first_present(review.get("reason")),
            "model": first_present(review.get("model")),
            "reviewed_at": first_present(review.get("reviewed_at")),
        }
    return record


def config_record(
    config: SearchConfig,
    *,
    categories: list[str] | None = None,
    queries: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "source": config.source,
        "queries": config.queries if queries is None else queries,
        "categories": config.categories if categories is None else categories,
        "max_results": config.max_results,
        "search_mode": config.search_mode,
        "min_score": config.min_score,
        "llm_review": config.llm_review,
        "llm_base_url": config.llm_base_url,
        "llm_model": config.llm_model,
        "llm_batch_size": config.llm_batch_size,
        "deepxiv_llm_review_max_candidates": config.deepxiv_llm_review_max_candidates,
    }


def build_month_record(
    month: MonthWindow,
    papers: list[dict[str, Any]],
    stats: dict[str, Any],
    config: SearchConfig,
    *,
    run_id: str,
    started_at: datetime,
) -> dict[str, Any]:
    stats_record = {key: value for key, value in stats.items() if key != "query_stats"}
    return {
        "schema_version": MONTH_SCHEMA_VERSION,
        "month": month.slug,
        "date_from": month.date_from,
        "date_to": month.date_to,
        "run": {
            "run_id": run_id,
            "started_at": started_at.isoformat(timespec="seconds"),
        },
        "config": config_record(
            config,
            categories=stats.get("resolved_categories"),
            queries=stats.get("resolved_queries"),
        ),
        "stats": stats_record,
        "search_log": stats.get("query_stats", []),
        "papers": [paper_record(paper, config=config, run_id=run_id) for paper in papers],
    }


def build_title_triage_record(
    month: MonthWindow,
    *,
    rule_related_papers: list[dict[str, Any]],
    no_clear_title_evidence_papers: list[dict[str, Any]],
    stats: dict[str, Any],
    config: SearchConfig,
    run_id: str,
    started_at: datetime,
) -> dict[str, Any]:
    stats_record = {key: value for key, value in stats.items() if key != "query_stats"}
    return {
        "schema_version": TITLE_TRIAGE_SCHEMA_VERSION,
        "month": month.slug,
        "date_from": month.date_from,
        "date_to": month.date_to,
        "run": {
            "run_id": run_id,
            "started_at": started_at.isoformat(timespec="seconds"),
        },
        "config": config_record(
            config,
            categories=stats.get("resolved_categories"),
            queries=stats.get("resolved_queries"),
        ),
        "stats": stats_record,
        "search_log": stats.get("query_stats", []),
        "rule_related_papers": [
            title_triage_record(paper, config=config, run_id=run_id) for paper in rule_related_papers
        ],
        "no_clear_title_evidence_papers": [
            title_triage_record(paper, config=config, run_id=run_id)
            for paper in no_clear_title_evidence_papers
        ],
    }
