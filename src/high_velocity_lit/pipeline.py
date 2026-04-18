"""Monthly DeepXiv search pipeline for high-velocity star literature."""

from __future__ import annotations

import calendar
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, TextIO

from .arxiv_client import ArxivClient
from .deepxiv_client import DeepXivClient
from .filters import category_matches, score_matches
from .markdown import render_index, render_month_note
from .models import MonthWindow, SearchConfig
from .title_classifier import LLMTitleClassifier, TitleDecision, heuristic_title_decision, load_llm_api_key


class ProgressReporter:
    """Small stderr progress bar for interactive terminal runs."""

    def __init__(self, enabled: bool, stream: TextIO | None = None) -> None:
        self.stream = stream or sys.stderr
        self._owns_stream = False
        self.terminal_enabled = self.stream.isatty()
        if stream is None and not self.terminal_enabled:
            try:
                self.stream = Path("/dev/tty").open("w", encoding="utf-8", buffering=1)
                self._owns_stream = True
                self.terminal_enabled = True
            except OSError:
                pass
        self.enabled = enabled and self.terminal_enabled
        self._last_width = 0
        self._line_active = False

    def block(self, title: str, lines: list[str]) -> None:
        if not self.terminal_enabled:
            return
        self.finish()
        self.stream.write(title + "\n")
        for line in lines:
            self.stream.write(f"  {line}\n")
        self.stream.flush()

    def message(self, text: str) -> None:
        if not self.enabled:
            return
        self.finish()
        self.stream.write(text + "\n")
        self.stream.flush()

    def update(self, label: str, current: int, total: int, detail: str = "") -> None:
        if not self.enabled or total <= 0:
            return

        current = min(max(current, 0), total)
        width = 24
        filled = int(width * current / total)
        bar = "#" * filled + "." * (width - filled)
        percent = int(round(100 * current / total))
        detail_text = f" {detail}" if detail else ""
        if len(detail_text) > 76:
            detail_text = detail_text[:73] + "..."
        line = f"{label:<9} [{bar}] {current}/{total} {percent:3d}%{detail_text}"
        padding = " " * max(0, self._last_width - len(line))
        self.stream.write("\r" + line + padding)
        self.stream.flush()
        self._last_width = len(line)
        self._line_active = True

        if current >= total:
            self.stream.write("\n")
            self.stream.flush()
            self._last_width = 0
            self._line_active = False

    def finish(self) -> None:
        if not self.enabled or not self._line_active:
            return
        self.stream.write("\r" + " " * self._last_width + "\r")
        self.stream.flush()
        self._last_width = 0
        self._line_active = False

    def close(self) -> None:
        self.finish()
        if self._owns_stream:
            self.stream.close()


def iter_months(config: SearchConfig) -> Iterable[MonthWindow]:
    year = config.start_date.year
    month = config.start_date.month
    while (year, month) <= (config.end_date.year, config.end_date.month):
        month_start = date(year, month, 1)
        last_day = calendar.monthrange(year, month)[1]
        month_end = date(year, month, last_day)
        start = max(month_start, config.start_date)
        end = min(month_end, config.end_date)
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


def search_call_count(config: SearchConfig, months: list[MonthWindow]) -> int:
    category_count = len(config.categories) if config.source == "deepxiv" and config.categories else 1
    return len(months) * len(config.queries) * category_count


def bool_text(value: bool) -> str:
    return "True" if value else "False"


def list_text(values: list[str], empty: str = "disabled") -> str:
    return ", ".join(values) if values else empty


def configured_text(value: str | None) -> str:
    return "configured" if value else "not configured"


def run_parameter_lines(config: SearchConfig, deepxiv_token: str | None) -> list[str]:
    return [
        f"--from: {config.start_date.isoformat()}",
        f"--to: {config.end_date.isoformat()}",
        f"--source: {config.source}",
        f"--max-results: {config.max_results}",
        f"--brief: {bool_text(config.use_brief)}",
        f"--classifier: {config.classifier}",
        f"--llm-review: {bool_text(config.llm_review)}",
        f"--categories: {list_text(config.categories)}",
        f"--min-score: {config.min_score if config.min_score is not None else 'disabled'}",
        f"--search-mode: {config.search_mode}",
        f"--progress: {bool_text(config.progress)}",
        f"--sleep: {config.search_sleep_seconds}",
        f"--brief-sleep: {config.brief_sleep_seconds}",
        f"--llm-base-url: {config.llm_base_url}",
        f"--llm-model: {config.llm_model}",
        f"--llm-batch-size: {config.llm_batch_size}",
        f"--llm-api-key: {configured_text(config.llm_api_key)}",
        f"--token/DEEPXIV_TOKEN: {configured_text(deepxiv_token)}",
        f"--notes-dir: {config.notes_dir}",
        f"--logs-dir: {config.logs_dir}",
        f"queries: {list_text(config.queries, empty='none')}",
    ]


def classify_candidates(
    papers: list[dict[str, Any]],
    config: SearchConfig,
    *,
    run_id: str,
    month: MonthWindow,
    run_log: Path,
    progress: ProgressReporter | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    included: list[dict[str, Any]] = []
    filtered = 0
    errors = 0
    direct_rule_included = 0
    weak_rule_candidates = 0
    weak_llm_reviewed = 0
    weak_llm_included = 0

    llm: LLMTitleClassifier | None = None
    use_llm = config.classifier == "llm" or (config.classifier == "rules" and config.llm_review)
    if use_llm:
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

    batches = list(classifier_batches(papers, config.llm_batch_size))
    for batch_index, batch in enumerate(batches, start=1):
        started = datetime.now()
        decisions: dict[str, TitleDecision] = {}
        error: str | None = None
        batch_weak_llm_reviewed = 0
        try:
            if config.classifier == "llm":
                assert llm is not None
                decisions = llm.classify_batch(batch)
            else:
                decisions = {
                    paper_id(paper): heuristic_title_decision(str(paper.get("title") or ""))
                    for paper in batch
                }
                if config.llm_review:
                    weak_batch = [
                        paper
                        for paper in batch
                        if decisions.get(paper_id(paper), TitleDecision(False, 0, "", "")).label == "rule-weak"
                    ]
                    if weak_batch:
                        assert llm is not None
                        batch_weak_llm_reviewed = len(weak_batch)
                        weak_llm_reviewed += len(weak_batch)
                        llm_decisions = llm.classify_batch(weak_batch)
                        for paper in weak_batch:
                            arxiv_id = paper_id(paper)
                            rule_decision = decisions[arxiv_id]
                            llm_decision = llm_decisions.get(arxiv_id)
                            if llm_decision is None:
                                decisions[arxiv_id] = TitleDecision(
                                    False,
                                    0.0,
                                    rule_decision.reason + " LLM did not return a decision for this weak match.",
                                    "rule-weak-llm-missing",
                                )
                            elif llm_decision.include:
                                weak_llm_included += 1
                                decisions[arxiv_id] = TitleDecision(
                                    True,
                                    llm_decision.confidence,
                                    rule_decision.reason + " LLM confirmed: " + llm_decision.reason,
                                    "rule-weak-llm-confirmed",
                                )
                            else:
                                decisions[arxiv_id] = TitleDecision(
                                    False,
                                    llm_decision.confidence,
                                    rule_decision.reason + " LLM rejected: " + llm_decision.reason,
                                    "rule-weak-llm-rejected",
                                )
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
                    "llm_review": config.llm_review,
                    "model": config.llm_model if use_llm else None,
                    "batch_size": len(batch),
                    "weak_llm_reviewed": batch_weak_llm_reviewed,
                    "error": error,
                    "duration_seconds": round((datetime.now() - started).total_seconds(), 3),
                },
            )
            if progress:
                progress.update("Classify", batch_index, len(batches), f"{month.slug} {len(batch)} titles")

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
                if decision.label == "rule-direct":
                    direct_rule_included += 1
                elif decision.label.startswith("rule-weak"):
                    weak_rule_candidates += 1
                included.append(paper)
            else:
                if decision.label.startswith("rule-weak"):
                    weak_rule_candidates += 1
                filtered += 1

    return included, {
        "classifier_included": len(included),
        "classifier_filtered": filtered,
        "classifier_errors": errors,
        "direct_rule_included": direct_rule_included,
        "weak_rule_candidates": weak_rule_candidates,
        "weak_llm_reviewed": weak_llm_reviewed,
        "weak_llm_included": weak_llm_included,
    }


def search_month(
    arxiv_client: ArxivClient,
    deepxiv_client: DeepXivClient,
    month: MonthWindow,
    config: SearchConfig,
    *,
    run_id: str,
    run_log: Path,
    progress: ProgressReporter | None = None,
    search_state: dict[str, int] | None = None,
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
            if progress and search_state is not None:
                search_state["done"] += 1
                detail = f"{month.slug} {query}"
                if category:
                    detail += f" {category}"
                progress.update("Search", search_state["done"], search_state["total"], detail)
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

    relevant, classifier_stats = classify_candidates(
        candidates,
        config,
        run_id=run_id,
        month=month,
        run_log=run_log,
        progress=progress,
    )

    relevant.sort(
        key=lambda paper: (
            parse_datetime(paper.get("publish_at")),
            float(paper.get("_best_score") or 0),
        ),
        reverse=True,
    )

    if config.use_brief:
        for index, paper in enumerate(relevant, start=1):
            arxiv_id = paper_id(paper)
            if not arxiv_id:
                if progress:
                    progress.update("Brief", index, len(relevant), f"{month.slug} missing arXiv ID")
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
            if progress:
                progress.update("Brief", index, len(relevant), f"{month.slug} {arxiv_id}")
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
    months = list(iter_months(config))
    progress = ProgressReporter(config.progress)
    search_state = {"done": 0, "total": search_call_count(config, months)}

    append_jsonl(
        run_log,
        {
            "event": "start",
            "run_id": run_id,
            "started_at": started_at.isoformat(timespec="seconds"),
            "from_date": config.start_date.isoformat(),
            "to_date": config.end_date.isoformat(),
            "query_count": len(config.queries),
            "max_results": config.max_results,
            "candidate_source": config.source,
            "categories": config.categories,
            "category_filter_stage": "deepxiv_per_category" if config.source == "deepxiv" else "local",
            "search_mode": config.search_mode,
            "min_score": config.min_score,
            "classifier": config.classifier,
            "llm_review": config.llm_review,
            "llm_base_url": config.llm_base_url if config.classifier == "llm" or config.llm_review else None,
            "llm_model": config.llm_model if config.classifier == "llm" or config.llm_review else None,
            "llm_batch_size": config.llm_batch_size if config.classifier == "llm" or config.llm_review else None,
            "use_brief": config.use_brief,
        },
    )

    try:
        progress.block("Resolved parameters:", run_parameter_lines(config, deepxiv_client.token))
        progress.message(
            f"Run {run_id}: {config.start_date.isoformat()} to {config.end_date.isoformat()} "
            f"({len(months)} month{'s' if len(months) != 1 else ''})"
        )
        for month_index, month in enumerate(months, start=1):
            progress.message(f"Month {month_index}/{len(months)} {month.slug}: {month.date_from} to {month.date_to}")
            papers, stats = search_month(
                arxiv_client,
                deepxiv_client,
                month,
                config,
                run_id=run_id,
                run_log=run_log,
                progress=progress,
                search_state=search_state,
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
        progress.message(f"Done: {len(month_summaries)} months, {summary['total_relevant']} relevant papers")
        return summary
    finally:
        progress.close()
