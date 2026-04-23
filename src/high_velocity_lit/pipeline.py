"""Monthly literature search pipeline for high-velocity star papers."""

from __future__ import annotations

import calendar
import json
import shlex
import socket
import sys
import time
import urllib.error
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, TextIO

from .arxiv_client import ArxivClient
from .config import DEFAULT_QUERIES
from .deepxiv_client import DeepXivClient
from .filters import category_matches, score_matches
from .indexing import refresh_index_outputs
from .markdown import render_month_note
from .models import MonthWindow, SearchConfig
from .note_paths import month_dir as build_month_dir
from .note_paths import month_json_path as build_month_json_path
from .note_paths import month_markdown_path as build_month_markdown_path
from .note_paths import month_title_triage_path as build_month_title_triage_path
from .records import build_month_record, build_title_triage_record
from .title_classifier import LLMTitleClassifier, TitleDecision, heuristic_title_decision, load_llm_api_key

LEGACY_GALACTIC_CATEGORY = "astro-ph"
MODERN_GALACTIC_CATEGORY = "astro-ph.GA"
LEGACY_CATEGORY_LAST_MONTH = (2008, 11)
TRANSITION_CATEGORY_MONTH = (2008, 12)
LEGACY_QUERY_LAST_MONTH = (2008, 12)
LEGACY_EXTRA_QUERIES = ["hyper-velocity star"]
ARXIV_METADATA_REPORT_SCHEMA_VERSION = "stella.arxiv.metadata.report.v1"


class PartialRunError(RuntimeError):
    """Raised when a recoverable API limit stops a run after partial output."""

    def __init__(self, summary: dict[str, Any], cause: Exception) -> None:
        super().__init__(str(cause))
        self.summary = summary
        self.__cause__ = cause


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


def write_json(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def month_note_dir(config: SearchConfig, month_slug: str) -> Path:
    return build_month_dir(config.notes_dir, month_slug)


def month_json_path(config: SearchConfig, month_slug: str) -> Path:
    return build_month_json_path(config.notes_dir, month_slug)


def month_markdown_path(config: SearchConfig, month_slug: str) -> Path:
    return build_month_markdown_path(config.notes_dir, month_slug)


def month_title_triage_path(config: SearchConfig, month_slug: str) -> Path:
    return build_month_title_triage_path(config.notes_dir, month_slug)


def index_json_path(config: SearchConfig) -> Path:
    return config.notes_dir / "index.json"


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


def paper_publication_date(paper: dict[str, Any]) -> date | None:
    for key in ("publish_at", "published_at", "published"):
        value = paper.get(key)
        if not value:
            continue
        parsed = parse_datetime(value)
        if parsed != datetime.min:
            return parsed.date()
    return None


def publication_date_in_month_window(paper: dict[str, Any], month: MonthWindow) -> bool:
    published = paper_publication_date(paper)
    if published is None:
        return False
    return month.start <= published <= month.end


def fetch_arxiv_metadata(
    arxiv_client: ArxivClient,
    arxiv_id: str,
    metadata_cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    cached = metadata_cache.get(arxiv_id)
    if cached is not None:
        return cached
    metadata = arxiv_client.metadata(arxiv_id)
    metadata_cache[arxiv_id] = metadata
    return metadata


def backfill_paper_metadata(
    paper: dict[str, Any],
    *,
    arxiv_client: ArxivClient,
    metadata_cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if paper_publication_date(paper) is not None:
        return {
            "attempted": False,
            "status": "not_needed",
            "arxiv_id": paper_id(paper),
            "title": str(paper.get("title") or ""),
            "timed_out": False,
            "error": None,
            "applied_fields": [],
        }
    arxiv_id = paper_id(paper)
    if not arxiv_id:
        return {
            "attempted": False,
            "status": "missing_arxiv_id",
            "arxiv_id": "",
            "title": str(paper.get("title") or ""),
            "timed_out": False,
            "error": None,
            "applied_fields": [],
        }
    try:
        metadata = fetch_arxiv_metadata(arxiv_client, arxiv_id, metadata_cache)
    except Exception as exc:
        timed_out = is_timeout_error(exc)
        return {
            "attempted": True,
            "status": "timeout" if timed_out else "error",
            "arxiv_id": arxiv_id,
            "title": str(paper.get("title") or ""),
            "timed_out": timed_out,
            "error": f"{type(exc).__name__}: {exc}",
            "applied_fields": [],
        }
    applied_fields: list[str] = []
    for key in ("publish_at", "published_at", "published", "updated_at", "authors", "author_names", "categories"):
        if metadata.get(key) and not paper.get(key):
            paper[key] = metadata[key]
            applied_fields.append(key)
    return {
        "attempted": True,
        "status": "publication_backfilled" if paper_publication_date(paper) is not None else "no_publication_date",
        "arxiv_id": arxiv_id,
        "title": str(paper.get("title") or ""),
        "timed_out": False,
        "error": None,
        "applied_fields": applied_fields,
    }


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


def uses_default_galactic_category(config: SearchConfig) -> bool:
    return config.source == "deepxiv" and config.categories == [MODERN_GALACTIC_CATEGORY]


def uses_default_queries(config: SearchConfig) -> bool:
    return config.queries == DEFAULT_QUERIES


def resolved_categories_for_month(config: SearchConfig, month: MonthWindow) -> list[str]:
    if config.source != "deepxiv":
        return config.categories
    if not uses_default_galactic_category(config):
        return config.categories
    if (month.year, month.month) <= LEGACY_CATEGORY_LAST_MONTH:
        return [LEGACY_GALACTIC_CATEGORY]
    if (month.year, month.month) == TRANSITION_CATEGORY_MONTH:
        return [LEGACY_GALACTIC_CATEGORY, MODERN_GALACTIC_CATEGORY]
    return [MODERN_GALACTIC_CATEGORY]


def resolved_queries_for_month(config: SearchConfig, month: MonthWindow) -> list[str]:
    queries = list(config.queries)
    if not uses_default_queries(config):
        return queries
    if (month.year, month.month) > LEGACY_QUERY_LAST_MONTH:
        return queries
    for query in LEGACY_EXTRA_QUERIES:
        if query not in queries:
            queries.append(query)
    return queries


def search_call_count(config: SearchConfig, months: list[MonthWindow]) -> int:
    total = 0
    for month in months:
        month_categories = resolved_categories_for_month(config, month)
        month_queries = resolved_queries_for_month(config, month)
        category_count = len(month_categories) if config.source == "deepxiv" and month_categories else 1
        total += len(month_queries) * category_count
    return total


def bool_text(value: bool) -> str:
    return "True" if value else "False"


def list_text(values: list[str], empty: str = "disabled") -> str:
    return ", ".join(values) if values else empty


def configured_text(value: str | None) -> str:
    return "configured" if value else "not configured"


def is_rate_limit_error(exc: Exception) -> bool:
    return type(exc).__name__ == "RateLimitError" or "Daily limit reached" in str(exc)


def is_timeout_error(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return True
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        return isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in str(reason).lower()
    return "timed out" in str(exc).lower()


def empty_arxiv_metadata_summary() -> dict[str, int]:
    return {
        "requested_count": 0,
        "publication_date_backfilled_count": 0,
        "timeout_count": 0,
        "error_count": 0,
        "no_publication_date_count": 0,
        "reported_count": 0,
    }


def summarize_arxiv_metadata(month_summaries: list[dict[str, Any]]) -> dict[str, int]:
    summary = empty_arxiv_metadata_summary()
    for item in month_summaries:
        summary["requested_count"] += int(item.get("arxiv_metadata_requested_count") or 0)
        summary["publication_date_backfilled_count"] += int(item.get("arxiv_publication_date_backfilled_count") or 0)
        summary["timeout_count"] += int(item.get("arxiv_metadata_timeout_count") or 0)
        summary["error_count"] += int(item.get("arxiv_metadata_error_count") or 0)
        summary["no_publication_date_count"] += int(item.get("arxiv_metadata_no_publication_date_count") or 0)
    return summary


def relevance_sort_key(paper: dict[str, Any]) -> tuple[int, datetime, float]:
    return (
        1,
        parse_datetime(paper.get("publish_at")),
        float(paper.get("_best_score") or 0),
    )


def run_parameter_lines(config: SearchConfig, deepxiv_token: str | None) -> list[str]:
    lines = [
        f"--from: {config.start_date.isoformat()}",
        f"--to: {config.end_date.isoformat()}",
        f"--source: {config.source}",
        f"--max-results: {config.max_results}",
        f"--llm-review: {bool_text(config.llm_review)}",
        f"--categories: {list_text(config.categories)}",
        f"--min-score: {config.min_score if config.min_score is not None else 'disabled'}",
        f"--search-mode: {config.search_mode}",
        f"--progress: {bool_text(config.progress)}",
        f"--sleep: {config.search_sleep_seconds}",
        f"--llm-base-url: {config.llm_base_url}",
        f"--llm-model: {config.llm_model}",
        f"--llm-batch-size: {config.llm_batch_size}",
        f"--llm-api-key: {configured_text(config.llm_api_key)}",
        f"--notes-dir: {config.notes_dir}",
        f"--logs-dir: {config.logs_dir}",
        f"queries: {list_text(config.queries, empty='none')}",
    ]
    if config.source == "deepxiv":
        lines.append(f"--token/DEEPXIV_TOKEN: {configured_text(deepxiv_token)}")
    if uses_default_galactic_category(config):
        lines.append(
            "historical categories: <= 2008-11 -> astro-ph; "
            "2008-12 -> astro-ph + astro-ph.GA; >= 2009-01 -> astro-ph.GA"
        )
    if uses_default_queries(config):
        lines.append("historical queries: through 2008-12 also add `hyper-velocity star`")
    return lines


def resume_command(config: SearchConfig, failed_month: MonthWindow) -> str:
    command_parts = [
        "conda",
        "run",
        "-n",
        "stella-env",
        "python",
        "scripts/fetch_high_velocity_lit.py",
        "--from",
        failed_month.slug,
        "--to",
        config.end_date.isoformat(),
        "--max-results",
        str(config.max_results),
        "--source",
        config.source,
        "--llm-review",
        bool_text(config.llm_review),
        "--notes-dir",
        str(config.notes_dir),
        "--logs-dir",
        str(config.logs_dir),
    ]
    if config.categories:
        command_parts.extend(["--categories", ",".join(config.categories)])
    else:
        command_parts.extend(["--categories", ""])
    if config.min_score is not None:
        command_parts.extend(["--min-score", str(config.min_score)])
    if config.search_mode:
        command_parts.extend(["--search-mode", config.search_mode])
    return " ".join(shlex.quote(part) for part in command_parts)


def build_run_summary(
    *,
    status: str,
    run_id: str,
    started_at: datetime,
    finished_at: datetime,
    config: SearchConfig,
    month_summaries: list[dict[str, Any]],
    run_log: Path,
    requested_months: list[MonthWindow],
) -> dict[str, Any]:
    return {
        "status": status,
        "run_id": run_id,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 3),
        "notes_dir": str(config.notes_dir),
        "logs_dir": str(config.logs_dir),
        "index_json": str(index_json_path(config)),
        "run_log": str(run_log),
        "months": month_summaries,
        "completed_months": [item["month"] for item in month_summaries],
        "requested_months": [month.slug for month in requested_months],
        "total_relevant": sum(item["relevant_count"] for item in month_summaries),
        "arxiv_metadata": summarize_arxiv_metadata(month_summaries),
    }


def build_arxiv_metadata_report(
    *,
    status: str,
    run_id: str,
    started_at: datetime,
    finished_at: datetime,
    requested_months: list[MonthWindow],
    month_summaries: list[dict[str, Any]],
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    summary = summarize_arxiv_metadata(month_summaries)
    summary["reported_count"] = len(entries)
    return {
        "schema_version": ARXIV_METADATA_REPORT_SCHEMA_VERSION,
        "status": status,
        "run_id": run_id,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "requested_months": [month.slug for month in requested_months],
        "completed_months": [item["month"] for item in month_summaries],
        "summary": summary,
        "entries": entries,
    }


def write_arxiv_metadata_report(
    *,
    config: SearchConfig,
    status: str,
    run_id: str,
    started_at: datetime,
    finished_at: datetime,
    requested_months: list[MonthWindow],
    month_summaries: list[dict[str, Any]],
    entries: list[dict[str, Any]],
) -> Path:
    report_path = config.logs_dir / f"arxiv_metadata_{run_id}.json"
    report = build_arxiv_metadata_report(
        status=status,
        run_id=run_id,
        started_at=started_at,
        finished_at=finished_at,
        requested_months=requested_months,
        month_summaries=month_summaries,
        entries=entries,
    )
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report_path


def write_partial_summary(
    *,
    config: SearchConfig,
    run_id: str,
    started_at: datetime,
    month_summaries: list[dict[str, Any]],
    requested_months: list[MonthWindow],
    failed_month: MonthWindow,
    error: Exception,
    run_log: Path,
    arxiv_metadata_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    finished_at = datetime.now()
    partial_path = config.logs_dir / f"partial_{run_id}.json"
    summary = build_run_summary(
        status="partial",
        run_id=run_id,
        started_at=started_at,
        finished_at=finished_at,
        config=config,
        month_summaries=month_summaries,
        run_log=run_log,
        requested_months=requested_months,
    )
    report_path = write_arxiv_metadata_report(
        config=config,
        status="partial",
        run_id=run_id,
        started_at=started_at,
        finished_at=finished_at,
        requested_months=requested_months,
        month_summaries=month_summaries,
        entries=arxiv_metadata_entries,
    )
    summary.update(
        {
            "error": f"{type(error).__name__}: {error}",
            "failed_month": failed_month.slug,
            "resume_from": failed_month.slug,
            "resume_command": resume_command(config, failed_month),
            "partial_summary_path": str(partial_path),
            "arxiv_metadata_report_path": str(report_path),
        }
    )
    summary["arxiv_metadata"]["reported_count"] = len(arxiv_metadata_entries)
    partial_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    append_jsonl(run_log, {"event": "partial_finish", **summary})
    append_jsonl(config.logs_dir / "runs.jsonl", summary)
    return summary


def write_collection_outputs(
    *,
    config: SearchConfig,
    month_summaries: list[dict[str, Any]],
) -> None:
    del month_summaries
    refresh_index_outputs(config.notes_dir)


def classify_candidates(
    papers: list[dict[str, Any]],
    config: SearchConfig,
    *,
    run_id: str,
    month: MonthWindow,
    run_log: Path,
    progress: ProgressReporter | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    rule_related: list[dict[str, Any]] = []
    no_clear_title_evidence: list[dict[str, Any]] = []
    batches = list(classifier_batches(papers, config.llm_batch_size))
    for batch_index, batch in enumerate(batches, start=1):
        started = datetime.now()
        decisions: dict[str, TitleDecision] = {}
        error: str | None = None
        try:
            decisions = {
                paper_id(paper): heuristic_title_decision(str(paper.get("title") or ""))
                for paper in batch
            }
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            append_jsonl(
                run_log,
                {
                    "event": "classify",
                    "stage": "rules",
                    "run_id": run_id,
                    "month": month.slug,
                    "batch_size": len(batch),
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
                decision = TitleDecision(
                    False,
                    0.0,
                    "Rule triage did not return a decision for this paper.",
                    "no-clear-title-evidence",
                )
            paper["_title_triage"] = {
                "include": decision.include,
                "confidence": decision.confidence,
                "reason": decision.reason,
                "label": decision.label,
            }
            if decision.label == "rule-related":
                rule_related.append(paper)
            else:
                no_clear_title_evidence.append(paper)

    return rule_related, no_clear_title_evidence, {
        "rule_related_count": len(rule_related),
        "no_clear_title_evidence_count": len(no_clear_title_evidence),
    }


def review_title_candidates(
    papers: list[dict[str, Any]],
    config: SearchConfig,
    *,
    run_id: str,
    month: MonthWindow,
    run_log: Path,
    progress: ProgressReporter | None = None,
) -> dict[str, int]:
    if not papers:
        return {
            "llm_reviewed_count": 0,
            "llm_confirmed_count": 0,
            "llm_not_confirmed_count": 0,
            "llm_missing_count": 0,
        }

    api_key = load_llm_api_key(config.llm_api_key)
    if not api_key:
        raise RuntimeError(
            "LLM review requires LLM_API_KEY, OPENAI_API_KEY, or DEEPXIV_AGENT_API_KEY "
            "in the environment, or --llm-api-key."
        )
    llm = LLMTitleClassifier(
        api_key=api_key,
        base_url=config.llm_base_url,
        model=config.llm_model,
    )

    reviewed_count = 0
    confirmed_count = 0
    not_confirmed_count = 0
    missing_count = 0
    reviewed_at = datetime.now()
    batches = list(classifier_batches(papers, config.llm_batch_size))
    for batch_index, batch in enumerate(batches, start=1):
        started = datetime.now()
        decisions: dict[str, TitleDecision] = {}
        error: str | None = None
        try:
            decisions = llm.classify_batch(batch)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            append_jsonl(
                run_log,
                {
                    "event": "classify",
                    "stage": "llm_review",
                    "run_id": run_id,
                    "month": month.slug,
                    "batch_size": len(batch),
                    "model": config.llm_model,
                    "error": error,
                    "duration_seconds": round((datetime.now() - started).total_seconds(), 3),
                },
            )
            if progress:
                progress.update("Review", batch_index, len(batches), f"{month.slug} {len(batch)} titles")

        for paper in batch:
            reviewed_count += 1
            decision = decisions.get(paper_id(paper))
            if decision is None:
                status = "missing"
                confidence = None
                reason = "LLM did not return a review result for this title."
                missing_count += 1
            elif decision.include:
                status = "confirmed"
                confidence = decision.confidence
                reason = decision.reason
                confirmed_count += 1
            else:
                status = "not_confirmed"
                confidence = decision.confidence
                reason = decision.reason
                not_confirmed_count += 1
            paper["_review"] = {
                "status": status,
                "confidence": confidence,
                "reason": reason,
                "model": config.llm_model,
                "reviewed_at": reviewed_at.isoformat(timespec="seconds"),
            }

    return {
        "llm_reviewed_count": reviewed_count,
        "llm_confirmed_count": confirmed_count,
        "llm_not_confirmed_count": not_confirmed_count,
        "llm_missing_count": missing_count,
    }


def search_month(
    arxiv_client: ArxivClient,
    deepxiv_client: DeepXivClient | None,
    month: MonthWindow,
    config: SearchConfig,
    *,
    started_at: datetime,
    run_id: str,
    run_log: Path,
    progress: ProgressReporter | None = None,
    search_state: dict[str, int] | None = None,
    metadata_cache: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    merged: dict[str, dict[str, Any]] = {}
    query_stats: list[dict[str, Any]] = []
    metadata_report_entries: list[dict[str, Any]] = []
    metadata_cache = metadata_cache if metadata_cache is not None else {}
    title_triage_json = month_title_triage_path(config, month.slug)
    month_categories = resolved_categories_for_month(config, month)
    month_queries = resolved_queries_for_month(config, month)

    for query in month_queries:
        categories_for_query = month_categories if config.source == "deepxiv" and month_categories else [None]
        for category in categories_for_query:
            row = {"query": query, "category": category, "total": None, "returned": 0, "error": None}
            started = datetime.now()
            fatal_error: Exception | None = None
            try:
                if config.source == "deepxiv":
                    if deepxiv_client is None:
                        raise RuntimeError("DeepXiv client is required when --source deepxiv is selected.")
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
    date_window_filtered = 0
    missing_publication_date = 0
    category_filtered = 0
    score_filtered = 0
    arxiv_metadata_requested_count = 0
    arxiv_publication_date_backfilled_count = 0
    arxiv_metadata_timeout_count = 0
    arxiv_metadata_error_count = 0
    arxiv_metadata_no_publication_date_count = 0
    for paper in merged.values():
        if config.source == "deepxiv":
            metadata_result = backfill_paper_metadata(
                paper,
                arxiv_client=arxiv_client,
                metadata_cache=metadata_cache,
            )
            if metadata_result.get("attempted"):
                arxiv_metadata_requested_count += 1
                status = str(metadata_result.get("status") or "")
                if status == "publication_backfilled":
                    arxiv_publication_date_backfilled_count += 1
                elif status == "timeout":
                    arxiv_metadata_timeout_count += 1
                elif status == "error":
                    arxiv_metadata_error_count += 1
                elif status == "no_publication_date":
                    arxiv_metadata_no_publication_date_count += 1

                if status in {"timeout", "error", "no_publication_date"}:
                    entry = {
                        "month": month.slug,
                        "arxiv_id": metadata_result.get("arxiv_id"),
                        "title": metadata_result.get("title"),
                        "status": status,
                        "timed_out": metadata_result.get("timed_out") is True,
                        "error": metadata_result.get("error"),
                    }
                    metadata_report_entries.append(entry)
                    append_jsonl(
                        run_log,
                        {
                            "event": "arxiv_metadata",
                            "run_id": run_id,
                            **entry,
                        },
                    )
        published = paper_publication_date(paper)
        if published is None:
            missing_publication_date += 1
            continue
        if not publication_date_in_month_window(paper, month):
            date_window_filtered += 1
            continue
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

    rule_related, no_clear_title_evidence, classifier_stats = classify_candidates(
        candidates,
        config,
        run_id=run_id,
        month=month,
        run_log=run_log,
        progress=progress,
    )
    review_stats = {
        "llm_reviewed_count": 0,
        "llm_confirmed_count": 0,
        "llm_not_confirmed_count": 0,
        "llm_missing_count": 0,
    }
    initial_triage_stats = {
        "month": month.slug,
        "date_from": month.date_from,
        "date_to": month.date_to,
        "resolved_categories": month_categories,
        "resolved_queries": month_queries,
        "raw_unique": len(merged),
        "relevant_count": len(rule_related),
        "date_window_filtered": date_window_filtered,
        "missing_publication_date": missing_publication_date,
        "arxiv_metadata_requested_count": arxiv_metadata_requested_count,
        "arxiv_publication_date_backfilled_count": arxiv_publication_date_backfilled_count,
        "arxiv_metadata_timeout_count": arxiv_metadata_timeout_count,
        "arxiv_metadata_error_count": arxiv_metadata_error_count,
        "arxiv_metadata_no_publication_date_count": arxiv_metadata_no_publication_date_count,
        "category_filtered": category_filtered,
        "score_filtered": score_filtered,
        "classifier_candidates": len(candidates),
        **classifier_stats,
        **review_stats,
        "query_stats": query_stats,
    }
    write_json(
        title_triage_json,
        build_title_triage_record(
            month,
            rule_related_papers=rule_related,
            no_clear_title_evidence_papers=no_clear_title_evidence,
            stats=initial_triage_stats,
            config=config,
            run_id=run_id,
            started_at=started_at,
        ),
    )

    if config.llm_review:
        review_stats = review_title_candidates(
            no_clear_title_evidence,
            config,
            run_id=run_id,
            month=month,
            run_log=run_log,
            progress=progress,
        )

    llm_confirmed = [
        paper
        for paper in no_clear_title_evidence
        if ((paper.get("_review") or {}).get("status") == "confirmed")
    ]
    relevant = list(rule_related) + llm_confirmed
    relevant.sort(key=relevance_sort_key, reverse=True)

    stats = {
        "month": month.slug,
        "date_from": month.date_from,
        "date_to": month.date_to,
        "title_triage_json_path": str(title_triage_json),
        "resolved_categories": month_categories,
        "resolved_queries": month_queries,
        "raw_unique": len(merged),
        "relevant_count": len(relevant),
        "date_window_filtered": date_window_filtered,
        "missing_publication_date": missing_publication_date,
        "arxiv_metadata_requested_count": arxiv_metadata_requested_count,
        "arxiv_publication_date_backfilled_count": arxiv_publication_date_backfilled_count,
        "arxiv_metadata_timeout_count": arxiv_metadata_timeout_count,
        "arxiv_metadata_error_count": arxiv_metadata_error_count,
        "arxiv_metadata_no_publication_date_count": arxiv_metadata_no_publication_date_count,
        "category_filtered": category_filtered,
        "score_filtered": score_filtered,
        "classifier_candidates": len(candidates),
        **classifier_stats,
        **review_stats,
        "query_stats": query_stats,
    }
    write_json(
        title_triage_json,
        build_title_triage_record(
            month,
            rule_related_papers=rule_related,
            no_clear_title_evidence_papers=no_clear_title_evidence,
            stats=stats,
            config=config,
            run_id=run_id,
            started_at=started_at,
        ),
    )
    return relevant, stats, metadata_report_entries


def run_pipeline(config: SearchConfig) -> dict[str, Any]:
    config.notes_dir.mkdir(parents=True, exist_ok=True)
    config.logs_dir.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now()
    run_id = started_at.strftime("%Y%m%dT%H%M%S")
    run_log = config.logs_dir / f"run_{run_id}.log"
    arxiv_client = ArxivClient()
    deepxiv_client = DeepXivClient(token=config.token) if config.source == "deepxiv" else None
    metadata_cache: dict[str, dict[str, Any]] = {}
    arxiv_metadata_entries: list[dict[str, Any]] = []
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
            "notes_dir": str(config.notes_dir),
            "categories": config.categories,
            "category_filter_stage": "deepxiv_per_category" if config.source == "deepxiv" else "local",
            "search_mode": config.search_mode,
            "min_score": config.min_score,
            "llm_review": config.llm_review,
            "llm_base_url": config.llm_base_url if config.llm_review else None,
            "llm_model": config.llm_model if config.llm_review else None,
            "llm_batch_size": config.llm_batch_size if config.llm_review else None,
        },
    )

    try:
        progress.block("Resolved parameters:", run_parameter_lines(config, getattr(deepxiv_client, "token", None)))
        progress.message(
            f"Run {run_id}: {config.start_date.isoformat()} to {config.end_date.isoformat()} "
            f"({len(months)} month{'s' if len(months) != 1 else ''})"
        )
        for month_index, month in enumerate(months, start=1):
            progress.message(f"Month {month_index}/{len(months)} {month.slug}: {month.date_from} to {month.date_to}")
            try:
                papers, stats, month_arxiv_metadata_entries = search_month(
                    arxiv_client,
                    deepxiv_client,
                    month,
                    config,
                    started_at=started_at,
                    run_id=run_id,
                    run_log=run_log,
                    progress=progress,
                    search_state=search_state,
                    metadata_cache=metadata_cache,
                )
                arxiv_metadata_entries.extend(month_arxiv_metadata_entries)
            except Exception as exc:
                if not is_rate_limit_error(exc):
                    raise
                summary = write_partial_summary(
                    config=config,
                    run_id=run_id,
                    started_at=started_at,
                    month_summaries=month_summaries,
                    requested_months=months,
                    failed_month=month,
                    error=exc,
                    run_log=run_log,
                    arxiv_metadata_entries=arxiv_metadata_entries,
                )
                raise PartialRunError(summary, exc) from exc
            month_record = build_month_record(month, papers, stats, config, run_id=run_id, started_at=started_at)
            month_json = month_json_path(config, month.slug)
            note_path = month_markdown_path(config, month.slug)
            month_json.parent.mkdir(parents=True, exist_ok=True)
            write_json(month_json, month_record)
            persisted_month = read_json(month_json)
            note_path.write_text(render_month_note(persisted_month), encoding="utf-8")
            month_summaries.append(
                {
                    "month": month.slug,
                    "date_from": month.date_from,
                    "date_to": month.date_to,
                    "raw_unique": stats["raw_unique"],
                    "relevant_count": stats["relevant_count"],
                    "arxiv_metadata_requested_count": stats["arxiv_metadata_requested_count"],
                    "arxiv_publication_date_backfilled_count": stats["arxiv_publication_date_backfilled_count"],
                    "arxiv_metadata_timeout_count": stats["arxiv_metadata_timeout_count"],
                    "arxiv_metadata_error_count": stats["arxiv_metadata_error_count"],
                    "arxiv_metadata_no_publication_date_count": stats["arxiv_metadata_no_publication_date_count"],
                    "title_triage_json_path": stats["title_triage_json_path"],
                    "json_path": str(month_json),
                    "note_path": str(note_path),
                }
            )
            write_collection_outputs(
                config=config,
                month_summaries=month_summaries,
            )
            append_jsonl(run_log, {"event": "month_done", "run_id": run_id, **month_summaries[-1]})

        finished_at = datetime.now()
        summary = build_run_summary(
            status="complete",
            run_id=run_id,
            started_at=started_at,
            finished_at=finished_at,
            config=config,
            month_summaries=month_summaries,
            run_log=run_log,
            requested_months=months,
        )
        report_path = write_arxiv_metadata_report(
            config=config,
            status="complete",
            run_id=run_id,
            started_at=started_at,
            finished_at=finished_at,
            requested_months=months,
            month_summaries=month_summaries,
            entries=arxiv_metadata_entries,
        )
        summary["arxiv_metadata_report_path"] = str(report_path)
        summary["arxiv_metadata"]["reported_count"] = len(arxiv_metadata_entries)
        append_jsonl(run_log, {"event": "finish", **summary})
        append_jsonl(config.logs_dir / "runs.jsonl", summary)
        progress.message(f"Done: {len(month_summaries)} months, {summary['total_relevant']} relevant papers")
        return summary
    finally:
        progress.close()
