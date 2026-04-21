"""Canonical JSON records for Stella literature outputs."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .models import MonthWindow, SearchConfig
from .note_paths import month_json_path, month_markdown_path


MONTH_SCHEMA_VERSION = "stella.literature.month.v2"
INDEX_SCHEMA_VERSION = "stella.literature.index.v4"


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


def classifier_label(paper: dict[str, Any]) -> str:
    classifier = paper.get("_classifier") or {}
    return str(classifier.get("label") or "")


def triage_level(label: str) -> str:
    return "weak" if label.startswith("rule-weak") or "weak" in label.lower() else "direct"


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


def catalog_verification_record(paper: dict[str, Any]) -> dict[str, Any]:
    verification = paper.get("catalog_verification")
    if not isinstance(verification, dict) or not verification:
        return {}
    normalized = {
        "verified": verification.get("verified") is True,
        "verified_at": first_present(verification.get("verified_at")),
        "overall_verdict": first_present(verification.get("overall_verdict")),
        "catalog_location": first_present(verification.get("catalog_location")),
        "record_path": first_present(verification.get("record_path")),
        "summary_path": first_present(verification.get("summary_path")),
    }
    if "has_catalog" in verification:
        normalized["has_catalog"] = verification.get("has_catalog") is True
    return normalized


def is_catalog_verified(paper: dict[str, Any]) -> bool:
    verification = catalog_verification_record(paper)
    return verification.get("verified") is True


def has_verified_catalog(paper: dict[str, Any]) -> bool:
    verification = catalog_verification_record(paper)
    return verification.get("has_catalog") is True


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


def brief_field_record(brief: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "tldr",
        "keywords",
        "citations",
        "publish_at",
        "published_at",
    }
    return {key: value for key, value in brief.items() if key not in normalized}


def paper_record(paper: dict[str, Any], *, config: SearchConfig, run_id: str) -> dict[str, Any]:
    arxiv_id = first_present(paper.get("arxiv_id"), paper.get("id"))
    classifier = paper.get("_classifier") or {}
    label = str(classifier.get("label") or "")
    brief = paper.get("_brief") or {}
    brief_skipped = first_present(paper.get("_brief_skipped"))
    brief_error = first_present(paper.get("_brief_error"))
    abstract = first_present(paper.get("abstract"), paper.get("summary"))
    best_score = as_float(first_present(paper.get("_best_score"), paper.get("score")))
    source_score = as_float(paper.get("score"))
    citations = first_present(brief.get("citations"), paper.get("citations"), paper.get("citation"))
    published_at = first_present(
        paper.get("publish_at"),
        paper.get("published_at"),
        paper.get("published"),
        brief.get("publish_at"),
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
            "source": config.source if abstract else None,
            "text": abstract,
        },
        "match": {
            "queries": as_list(paper.get("_matched_queries")),
            "categories": as_list(paper.get("_matched_categories")),
            "best_score": best_score,
        },
        "triage": {
            "level": triage_level(label),
            "label": label or config.classifier,
            "include": bool(classifier.get("include", True)),
            "confidence": as_float(classifier.get("confidence")),
            "reason": first_present(classifier.get("reason")),
        },
        "deepxiv": {
            "score": source_score,
            "best_score": best_score,
            "search_keywords": paper.get("keywords"),
            "citations": citations,
        },
        "brief": {
            "fetched": bool(brief),
            "source": "deepxiv" if brief else None,
            "skipped_reason": brief_skipped or None,
            "error": brief_error or None,
            "tldr": first_present(brief.get("tldr"), paper.get("tldr")),
            "keywords": brief.get("keywords"),
            "citations": first_present(brief.get("citations")),
            "published_at": first_present(brief.get("publish_at")),
            "source_fields": brief_field_record(brief),
        },
        "provenance": {
            "search_source": config.source,
            "brief_source": "deepxiv" if brief else None,
            "run_id": run_id,
        },
    }
    raw_fields = source_field_record(paper)
    if raw_fields:
        record["source_fields"] = raw_fields
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
        "classifier": config.classifier,
        "llm_review": config.llm_review,
        "llm_base_url": config.llm_base_url,
        "llm_model": config.llm_model,
        "llm_batch_size": config.llm_batch_size,
        "use_brief": config.use_brief,
        "brief_policy": "direct_only" if config.use_brief else "disabled",
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
