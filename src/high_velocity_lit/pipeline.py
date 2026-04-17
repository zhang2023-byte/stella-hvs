"""Monthly DeepXiv search pipeline for high-velocity star literature."""

from __future__ import annotations

import calendar
import json
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from .arxiv_client import ArxivClient
from .deepxiv_client import DeepXivClient
from .filters import category_matches, score_matches
from .markdown import render_index, render_month_note
from .models import MonthWindow, SearchConfig
from .title_classifier import LLMTitleClassifier, TitleDecision, heuristic_title_decision, load_llm_api_key


def iter_months(config: SearchConfig) -> Iterable[MonthWindow]:
    year = config.start_year
    month = config.start_month
    while (year, month) <= (config.end_year, config.end_month):
        start = date(year, month, 1)
        last_day = calendar.monthrange(year, month)[1]
        end = date(year, month, last_day)
        if config.end_date and end > config.end_date:
            end = config.end_date
        if end >= start:
            yield MonthWindow(year=year, month=month, start=start, end=end)

        month += 1
        if month > 12:
            month = 1
            year += 1


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def parse_datetime(value: Any) -> datetime:
    if not value:
        return datetime.min
    text = str(value).replace("Z", "+00:00")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19 if " " in fmt or "T" in fmt else 10], fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime.min


def paper_id(paper: dict[str, Any]) -> str:
    return str(paper.get("arxiv_id") or paper.get("id") or "").strip()


def merge_paper(existing: dict[str, Any], incoming: dict[str, Any], query: str) -> None:
    existing["_matched_queries"].append(query)
    existing["_best_score"] = max(float(existing.get("_best_score") or 0), float(incoming.get("score") or 0))
    for key, value in incoming.items():
        if value and not existing.get(key):
            existing[key] = value


def add_matched_category(paper: dict[str, Any], category: str | None) -> None:
    if not category:
        return
    categories = paper.setdefault("_matched_categories", [])
    if category not in categories:
        categories.append(category)


def classifier_batches(papers: list[dict[str, Any]], batch_size: int) -> Iterable[list[dict[str, Any]]]:
    size = max(1, batch_size)
    for index in range(0, len(papers), size):
        yield papers[index : index + size]


def classify_candidates(
    papers: list[dict[str, Any]],
    config: SearchConfig,
    *,
    run_id: str,
    month: MonthWindow,
    run_log: Path,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if config.classifier == "none":
        for paper in papers:
            paper["_classifier"] = {
                "include": True,
                "confidence": 1.0,
                "reason": "Classifier disabled.",
                "label": "none",
            }
        return papers, {"classifier_included": len(papers), "classifier_filtered": 0, "classifier_errors": 0}

    included: list[dict[str, Any]] = []
    filtered = 0
    errors = 0

    llm: LLMTitleClassifier | None = None
    if config.classifier == "llm":
        api_key = load_llm_api_key(config.llm_api_key)
        if not api_key:
            raise RuntimeError(
                "LLM classifier requires LLM_API_KEY, OPENAI_API_KEY, or DEEPXIV_AGENT_API_KEY "
                "in the environment, or --llm-api-key."
            )
        llm = LLMTitleClassifier(
            api_key=api_key,
            base_url=config.llm_base_url,
            model=config.llm_model,
        )

    for batch in classifier_batches(papers, config.llm_batch_size):
        started = datetime.now()
        decisions: dict[str, TitleDecision] = {}
        error: str | None = None
        try:
            if config.classifier == "llm":
                assert llm is not None
                decisions = llm.classify_batch(batch)
            else:
                decisions = {
                    paper_id(paper): heuristic_title_decision(str(paper.get("title") or ""))
                    for paper in batch
                }
        except Exception as exc:
            errors += len(batch)
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            append_jsonl(
                run_log,
                {
                    "event": "classify",
                    "run_id": run_id,
                    "month": month.slug,
                    "classifier": config.classifier,
                    "model": config.llm_model if config.classifier == "llm" else None,
                    "batch_size": len(batch),
                    "error": error,
                    "duration_seconds": round((datetime.now() - started).total_seconds(), 3),
                },
            )

        for paper in batch:
            arxiv_id = paper_id(paper)
            decision = decisions.get(arxiv_id)
            if decision is None:
                decision = TitleDecision(False, 0.0, "Classifier did not return a decision for this paper.", "missing")
            paper["_classifier"] = {
                "include": decision.include,
                "confidence": decision.confidence,
                "reason": decision.reason,
                "label": decision.label,
            }
            if decision.include:
                included.append(paper)
            else:
                filtered += 1

    return included, {
        "classifier_included": len(included),
        "classifier_filtered": filtered,
        "classifier_errors": errors,
    }


def search_month(
    arxiv_client: ArxivClient,
    deepxiv_client: DeepXivClient,
    month: MonthWindow,
    config: SearchConfig,
    *,
    run_id: str,
    run_log: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    query_stats: list[dict[str, Any]] = []

    for query in config.queries:
        categories_for_query = config.categories if config.source == "deepxiv" and config.categories else [None]
        for category in categories_for_query:
            row = {"query": query, "category": category, "total": None, "returned": 0, "error": None}
            started = datetime.now()
            fatal_error: Exception | None = None
            try:
                if config.source == "deepxiv":
                    result = deepxiv_client.search(
                        query,
                        size=config.max_results,
                        search_mode=config.search_mode,
                        date_from=month.date_from,
                        date_to=month.date_to,
                        categories=[category] if category else None,
                    )
                else:
                    result = arxiv_client.search(
                        query,
                        size=config.max_results,
                        date_from=month.date_from,
                        date_to=month.date_to,
                    )
                papers = result.get("results") or []
                row["total"] = result.get("total")
                row["returned"] = len(papers)
                for paper in papers:
                    arxiv_id = paper_id(paper)
                    if not arxiv_id:
                        continue
                    if arxiv_id in merged:
                        merge_paper(merged[arxiv_id], paper, query)
                        add_matched_category(merged[arxiv_id], category)
                    else:
                        item = dict(paper)
                        item["_matched_queries"] = [query]
                        item["_best_score"] = float(item.get("score") or 0)
                        item["_matched_categories"] = []
                        add_matched_category(item, category)
                        merged[arxiv_id] = item
            except Exception as exc:
                row["error"] = f"{type(exc).__name__}: {exc}"
                fatal_error = exc

            query_stats.append(row)
            append_jsonl(
                run_log,
                {
                    "event": "query",
                    "source": config.source,
                    "run_id": run_id,
                    "month": month.slug,
                    "query": query,
                    "category": category,
                    "date_from": month.date_from,
                    "date_to": month.date_to,
                    "total": row["total"],
                    "returned": row["returned"],
                    "error": row["error"],
                    "duration_seconds": round((datetime.now() - started).total_seconds(), 3),
                },
            )
            if fatal_error:
                raise fatal_error
            if config.search_sleep_seconds > 0:
                time.sleep(config.search_sleep_seconds)

        if config.source != "deepxiv":
            # arXiv search does not currently fan out over categories in this script.
            # Avoid repeating the same query for each configured category.
            continue

    if config.source != "deepxiv":
        # The loop above already ran once per query with category=None.
        pass

    candidates: list[dict[str, Any]] = []
    category_filtered = 0
    score_filtered = 0
    for paper in merged.values():
        if config.source != "deepxiv" and not category_matches(paper, config.categories):
            category_filtered += 1
            continue
        if not score_matches(paper, config.min_score):
            score_filtered += 1
            continue
        candidates.append(paper)

    candidates.sort(
        key=lambda paper: (
            parse_datetime(paper.get("publish_at")),
            float(paper.get("_best_score") or 0),
        ),
        reverse=True,
    )

    relevant, classifier_stats = classify_candidates(candidates, config, run_id=run_id, month=month, run_log=run_log)

    relevant.sort(
        key=lambda paper: (
            parse_datetime(paper.get("publish_at")),
            float(paper.get("_best_score") or 0),
        ),
        reverse=True,
    )

    if config.use_brief:
        for paper in relevant:
            arxiv_id = paper_id(paper)
            if not arxiv_id:
                continue
            started = datetime.now()
            fatal_error: Exception | None = None
            try:
                paper["_brief"] = deepxiv_client.brief(arxiv_id)
                error = None
            except Exception as exc:
                paper["_brief_error"] = f"{type(exc).__name__}: {exc}"
                error = paper["_brief_error"]
                if type(exc).__name__ in {"AuthenticationError", "RateLimitError"}:
                    fatal_error = exc
            append_jsonl(
                run_log,
                {
                    "event": "brief",
                    "run_id": run_id,
                    "month": month.slug,
                    "arxiv_id": arxiv_id,
                    "error": error,
                    "duration_seconds": round((datetime.now() - started).total_seconds(), 3),
                },
            )
            if fatal_error:
                raise fatal_error
            if config.brief_sleep_seconds > 0:
                time.sleep(config.brief_sleep_seconds)

    stats = {
        "month": month.slug,
        "date_from": month.date_from,
        "date_to": month.date_to,
        "raw_unique": len(merged),
        "relevant_count": len(relevant),
        "category_filtered": category_filtered,
        "score_filtered": score_filtered,
        "classifier_candidates": len(candidates),
        **classifier_stats,
        "query_stats": query_stats,
    }
    return relevant, stats


def run_pipeline(config: SearchConfig) -> dict[str, Any]:
    config.notes_dir.mkdir(parents=True, exist_ok=True)
    config.logs_dir.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now()
    run_id = started_at.strftime("%Y%m%dT%H%M%S")
    run_log = config.logs_dir / f"run_{run_id}.log"
    arxiv_client = ArxivClient()
    deepxiv_client = DeepXivClient(token=config.token)
    month_summaries: list[dict[str, Any]] = []

    append_jsonl(
        run_log,
        {
            "event": "start",
            "run_id": run_id,
            "started_at": started_at.isoformat(timespec="seconds"),
            "start_year": config.start_year,
            "start_month": config.start_month,
            "end_year": config.end_year,
            "end_month": config.end_month,
            "end_date": config.end_date.isoformat() if config.end_date else None,
            "query_count": len(config.queries),
            "max_results": config.max_results,
            "candidate_source": config.source,
            "categories": config.categories,
            "category_filter_stage": "deepxiv_per_category" if config.source == "deepxiv" else "local",
            "search_mode": config.search_mode,
            "min_score": config.min_score,
            "classifier": config.classifier,
            "llm_base_url": config.llm_base_url if config.classifier == "llm" else None,
            "llm_model": config.llm_model if config.classifier == "llm" else None,
            "llm_batch_size": config.llm_batch_size if config.classifier == "llm" else None,
            "use_brief": config.use_brief,
        },
    )

    for month in iter_months(config):
        papers, stats = search_month(
            arxiv_client,
            deepxiv_client,
            month,
            config,
            run_id=run_id,
            run_log=run_log,
        )
        note = render_month_note(month, papers, stats, config, run_id=run_id, started_at=started_at)
        (config.notes_dir / f"{month.slug}.md").write_text(note, encoding="utf-8")
        month_summaries.append(
            {
                "month": month.slug,
                "date_from": month.date_from,
                "date_to": month.date_to,
                "raw_unique": stats["raw_unique"],
                "relevant_count": stats["relevant_count"],
            }
        )
        append_jsonl(run_log, {"event": "month_done", "run_id": run_id, **month_summaries[-1]})

    index = render_index(month_summaries, run_id=run_id, started_at=started_at)
    (config.notes_dir / "index.md").write_text(index, encoding="utf-8")

    finished_at = datetime.now()
    summary = {
        "run_id": run_id,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 3),
        "notes_dir": str(config.notes_dir),
        "logs_dir": str(config.logs_dir),
        "months": month_summaries,
        "total_relevant": sum(item["relevant_count"] for item in month_summaries),
    }
    append_jsonl(run_log, {"event": "finish", **summary})
    append_jsonl(config.logs_dir / "runs.jsonl", summary)
    return summary
