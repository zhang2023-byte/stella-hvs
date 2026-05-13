"""Catalog review inventory and index helpers."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from .schema_specs import (
    CATALOG_EXTRACTION_SCHEMA_VERSION,
    CATALOG_INDEX_SCHEMA_VERSION,
    CATALOG_INVENTORY_SCHEMA_VERSION,
    CATALOG_REVIEW_SCHEMA_VERSION,
)

REVIEW_FILENAME = "catalog_review.json"
EXTRACTION_FILENAME = "catalog_extraction.json"
INDEX_JSON_FILENAME = "literature_catalog_index.json"
INDEX_MARKDOWN_FILENAME = "literature_catalog_index.md"
INTERNAL_TABLES_FIELD = "internal_tables"
EXTERNAL_RESOURCES_FIELD = "external_resources"

TABLE_ENVIRONMENTS = {
    "deluxetable",
    "deluxetable*",
    "longtable",
    "sidewaystable",
    "sidewaystable*",
    "table",
    "table*",
}
MACHINE_READABLE_SUFFIXES = {
    ".csv",
    ".dat",
    ".ecsv",
    ".fit",
    ".fits",
    ".fits.gz",
    ".mrt",
    ".tbl",
    ".tsv",
    ".txt",
    ".vot",
    ".votable",
    ".xml",
}
URL_RE = re.compile(r"https?://[^\s{}\\)>,]+")
BEGIN_ENV_RE = re.compile(r"\\begin\{([^}]+)\}")
END_ENV_TEMPLATE = r"\\end\{%s\}"
REVIEW_STATUS_MEANINGS = {
    "reviewed": "Data asset review is complete for the available paper/source context.",
    "partial": "Data asset review is incomplete or has unresolved coverage questions.",
    "needs_review": "Data asset review has not been completed yet.",
    "source_missing": "Data asset review could not be completed from source files.",
    "unknown": "Data asset review status is missing or unknown.",
}
EXTRACTION_SUCCESS_STATUSES = {"success", "would_write", "skipped_existing"}
EXTRACTION_STATUS_VALUES = {"success", "partial", "failed", "not_started", "not_applicable"}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def preferred_list(record: dict[str, Any], field: str) -> list[dict[str, Any]]:
    if isinstance(record.get(field), list):
        return _dict_items(record.get(field))
    return []


def internal_tables_from_review(review: dict[str, Any]) -> list[dict[str, Any]]:
    return preferred_list(review, INTERNAL_TABLES_FIELD)


def external_resources_from_record(record: dict[str, Any]) -> list[dict[str, Any]]:
    return preferred_list(record, EXTERNAL_RESOURCES_FIELD)


def relative_path(path: Path, *, workspace: Path) -> str:
    try:
        return str(path.relative_to(workspace))
    except ValueError:
        return str(path)


def compact_date(text: Any) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    return value.split("T", 1)[0].split(" ", 1)[0]


def paper_dir(literature_dir: Path, arxiv_id: str) -> Path:
    return literature_dir / arxiv_id


def catalog_review_path(paper_directory: Path) -> Path:
    return paper_directory / REVIEW_FILENAME


def iter_catalog_review_paths(literature_dir: Path) -> list[Path]:
    if not literature_dir.exists():
        return []
    return sorted(
        path
        for path in literature_dir.glob(f"*/{REVIEW_FILENAME}")
        if path.is_file() and path.parent.name not in {"catalog_sources", "catalog_tables"}
    )


def _source_dir_from_audit(paper_directory: Path, audit: dict[str, Any]) -> Path | None:
    source = audit.get("arxiv_source") or {}
    extract_dir = str(source.get("extract_dir") or "arxiv_source")
    candidate = paper_directory / extract_dir
    if candidate.exists() and candidate.is_dir():
        return candidate
    fallback = paper_directory / "arxiv_source"
    if fallback.exists() and fallback.is_dir():
        return fallback
    return None


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def _find_matching_brace(text: str, open_index: int) -> int:
    depth = 0
    escaped = False
    for index in range(open_index, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def latex_command_argument(text: str, command: str) -> str:
    match = re.search(rf"\\{re.escape(command)}\s*(?:\[[^\]]*\])?\s*\{{", text, flags=re.DOTALL)
    if match is None:
        return ""
    open_index = match.end() - 1
    close_index = _find_matching_brace(text, open_index)
    if close_index == -1:
        return ""
    return " ".join(text[open_index + 1 : close_index].split())


def _line_number_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def extract_table_candidates(tex_path: Path, *, source_dir: Path, workspace: Path) -> list[dict[str, Any]]:
    text = _read_text(tex_path)
    candidates: list[dict[str, Any]] = []
    search_from = 0
    while True:
        match = BEGIN_ENV_RE.search(text, search_from)
        if match is None:
            break
        env = match.group(1)
        search_from = match.end()
        if env not in TABLE_ENVIRONMENTS:
            continue
        end_match = re.search(END_ENV_TEMPLATE % re.escape(env), text[match.end() :])
        if end_match is None:
            continue
        end_offset = match.end() + end_match.end()
        excerpt = text[match.start() : end_offset]
        start_line = _line_number_for_offset(text, match.start())
        end_line = _line_number_for_offset(text, end_offset)
        caption = latex_command_argument(excerpt, "caption") or latex_command_argument(excerpt, "tablecaption")
        label = latex_command_argument(excerpt, "label")
        candidates.append(
            {
                "kind": "latex_table",
                "environment": env,
                "path": relative_path(tex_path, workspace=workspace),
                "source_relative_path": str(tex_path.relative_to(source_dir)),
                "start_line": start_line,
                "end_line": end_line,
                "caption": caption,
                "label": label,
                "latex_excerpt": excerpt,
            }
        )
        search_from = end_offset
    return candidates


def _machine_readable_suffix(path: Path) -> str:
    name = path.name.lower()
    if name.endswith(".fits.gz"):
        return ".fits.gz"
    return path.suffix.lower()


def find_machine_readable_files(source_dir: Path, *, workspace: Path) -> list[dict[str, Any]]:
    resources: list[dict[str, Any]] = []
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        suffix = _machine_readable_suffix(path)
        if suffix not in MACHINE_READABLE_SUFFIXES:
            continue
        resources.append(
            {
                "kind": "local_machine_readable_file",
                "path": relative_path(path, workspace=workspace),
                "source_relative_path": str(path.relative_to(source_dir)),
                "suffix": suffix,
                "size_bytes": path.stat().st_size,
            }
        )
    return resources


def _extract_urls_from_text(text: str) -> list[str]:
    urls = set(URL_RE.findall(text))
    for command in ("url", "href"):
        pattern = re.compile(rf"\\{command}\s*\{{([^}}]+)\}}")
        for match in pattern.finditer(text):
            value = match.group(1).strip()
            if value.startswith("http://") or value.startswith("https://"):
                urls.add(value)
    return sorted(urls)


def find_external_resource_mentions(tex_paths: list[Path], *, source_dir: Path, workspace: Path) -> list[dict[str, Any]]:
    mentions: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for tex_path in tex_paths:
        text = _read_text(tex_path)
        lines = text.splitlines()
        for index, line in enumerate(lines, start=1):
            urls = _extract_urls_from_text(line)
            lowered = line.lower()
            tokens = (
                "cds",
                "vizier",
                "votable",
                "machine-readable",
                "machine readable",
                "data are available",
                "data is available",
                "zenodo",
                "github",
            )
            looks_data_related = any(
                token in lowered
                for token in tokens
            )
            if not urls and not looks_data_related:
                continue
            context_start = max(0, index - 3)
            context_end = min(len(lines), index + 2)
            context = "\n".join(lines[context_start:context_end]).strip()
            for url in urls or [""]:
                key = (str(tex_path), url or context)
                if key in seen:
                    continue
                seen.add(key)
                mentions.append(
                    {
                        "kind": "external_resource_mention",
                        "path": relative_path(tex_path, workspace=workspace),
                        "source_relative_path": str(tex_path.relative_to(source_dir)),
                        "line": index,
                        "url": url,
                        "context": context,
                    }
                )
    return mentions


def find_tex_root(tex_paths: list[Path]) -> str:
    scored: list[tuple[int, str]] = []
    for path in tex_paths:
        text = _read_text(path)
        score = 0
        if "\\documentclass" in text:
            score += 10
        if "\\begin{document}" in text:
            score += 5
        if "\\title" in text:
            score += 2
        scored.append((-score, str(path)))
    if not scored:
        return ""
    return min(scored)[1]


def _paper_from_month_json(audit: dict[str, Any], *, workspace: Path) -> dict[str, Any]:
    note_path_text = str(audit.get("source_note_json") or "").strip()
    if not note_path_text:
        return {}
    note_path = Path(note_path_text)
    if not note_path.is_absolute():
        note_path = workspace / note_path
    if not note_path.exists():
        return {}
    record = read_json(note_path)
    arxiv_id = str(audit.get("arxiv_id") or "").strip()
    for paper in record.get("papers") or []:
        if isinstance(paper, dict) and str(paper.get("arxiv_id") or "").strip() == arxiv_id:
            return paper
    return {}


def build_catalog_candidate_inventory(
    *,
    literature_dir: Path,
    arxiv_id: str,
    workspace: Path | None = None,
) -> dict[str, Any]:
    workspace = workspace or literature_dir.parent
    target_dir = paper_dir(literature_dir, arxiv_id)
    audit_path = target_dir / "audit.json"
    audit = read_json(audit_path) if audit_path.exists() else {}
    paper = _paper_from_month_json(audit, workspace=workspace)
    source_dir = _source_dir_from_audit(target_dir, audit)
    tex_paths = sorted(source_dir.rglob("*.tex")) if source_dir is not None else []
    tex_root = find_tex_root(tex_paths)

    table_candidates: list[dict[str, Any]] = []
    local_resources: list[dict[str, Any]] = []
    external_mentions: list[dict[str, Any]] = []
    if source_dir is not None:
        for tex_path in tex_paths:
            table_candidates.extend(extract_table_candidates(tex_path, source_dir=source_dir, workspace=workspace))
        local_resources = find_machine_readable_files(source_dir, workspace=workspace)
        external_mentions = find_external_resource_mentions(tex_paths, source_dir=source_dir, workspace=workspace)

    links = paper.get("links") if isinstance(paper.get("links"), dict) else {}
    return {
        "schema_version": CATALOG_INVENTORY_SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "paper": {
            "arxiv_id": arxiv_id,
            "title": str(paper.get("title") or audit.get("title") or ""),
            "month": str(audit.get("month") or paper.get("month") or ""),
            "source_note_json": str(audit.get("source_note_json") or ""),
            "links": links or {},
        },
        "source": {
            "paper_dir": relative_path(target_dir, workspace=workspace),
            "audit_path": relative_path(audit_path, workspace=workspace) if audit_path.exists() else "",
            "source_dir": relative_path(source_dir, workspace=workspace) if source_dir is not None else "",
            "tex_root": relative_path(Path(tex_root), workspace=workspace) if tex_root else "",
            "source_available": source_dir is not None,
            "tex_file_count": len(tex_paths),
        },
        "table_candidates": table_candidates,
        "local_machine_readable_files": local_resources,
        "external_resource_mentions": external_mentions,
    }


def _review_item(path: Path, review: dict[str, Any], *, workspace: Path) -> dict[str, Any]:
    paper = review.get("paper") or {}
    source = review.get("source") if isinstance(review.get("source"), dict) else {}
    review_meta = review.get("review") or {}
    internal_tables = internal_tables_from_review(review)
    external_resources = external_resources_from_record(review)
    arxiv_id = str(paper.get("arxiv_id") or path.parent.name)
    month = str(paper.get("month") or "")
    year = month[:4] if month else ""
    status = str(review_meta.get("status") or "unknown")
    source_available = source.get("source_available")
    status_warning = ""
    if status == "source_missing" and source_available is True:
        status_warning = "review.status=source_missing conflicts with source.source_available=true"
    internal_table_count = len(internal_tables)
    external_resource_count = len(external_resources)
    has_data_asset = internal_table_count + external_resource_count > 0
    item = {
        "title": str(paper.get("title") or "Untitled"),
        "arxiv_id": arxiv_id,
        "month": month,
        "year": year,
        "review_status": status,
        "review_status_meaning": REVIEW_STATUS_MEANINGS.get(status, REVIEW_STATUS_MEANINGS["unknown"]),
        "review_status_warning": status_warning,
        "reviewed_at": str(review_meta.get("reviewed_at") or ""),
        "has_data_asset": has_data_asset,
        "has_internal_table": bool(internal_tables),
        "internal_table_count": internal_table_count,
        "external_resource_count": external_resource_count,
        "paper_dir": relative_path(path.parent, workspace=workspace),
        "review_json_path": relative_path(path, workspace=workspace),
    }
    item.update(_extraction_item(path.parent, has_extractable_table=bool(internal_tables), workspace=workspace))
    return item


def _run_status(manifest: dict[str, Any]) -> str:
    run = manifest.get("run") if isinstance(manifest.get("run"), dict) else {}
    if not run:
        return ""
    return str(run.get("status") or "")


def _normalize_extraction_status(run_status: str, *, has_extractable_table: bool) -> str:
    if run_status in {"success", "partial", "failed"}:
        return run_status
    if run_status == "skipped" and not has_extractable_table:
        return "not_applicable"
    if run_status == "skipped":
        return "not_started"
    return "failed"


def _status_count(items: list[dict[str, Any]], statuses: set[str]) -> int:
    return sum(1 for item in items if str(item.get("status") or "") in statuses)


def _extraction_item(paper_directory: Path, *, has_extractable_table: bool, workspace: Path) -> dict[str, Any]:
    extraction_path = paper_directory / EXTRACTION_FILENAME
    default_status = "not_started" if has_extractable_table else "not_applicable"
    item: dict[str, Any] = {
        "extraction_status": default_status,
        "extraction_json_path": "",
        "extraction_run_status": "",
        "extraction_manifest_present": False,
        "extraction_error": "",
        "table_success_count": 0,
        "table_failed_count": 0,
        "file_success_count": 0,
        "file_failed_count": 0,
    }
    if not extraction_path.exists():
        return item

    item["extraction_manifest_present"] = True
    item["extraction_json_path"] = relative_path(extraction_path, workspace=workspace)
    try:
        manifest = read_json(extraction_path)
    except (OSError, json.JSONDecodeError) as exc:
        item["extraction_status"] = "failed"
        item["extraction_run_status"] = "manifest_error"
        item["extraction_error"] = f"{type(exc).__name__}: {exc}"
        return item

    run_status = _run_status(manifest)
    item["extraction_run_status"] = run_status
    item["extraction_status"] = _normalize_extraction_status(run_status, has_extractable_table=has_extractable_table)
    tables = [table for table in (manifest.get("tables") or []) if isinstance(table, dict)]
    files = [file for file in (manifest.get("files") or []) if isinstance(file, dict)]
    item.update(
        {
            "table_success_count": _status_count(tables, EXTRACTION_SUCCESS_STATUSES),
            "table_failed_count": _status_count(tables, {"failed"}),
            "file_success_count": _status_count(files, EXTRACTION_SUCCESS_STATUSES | {"written", "success"}),
            "file_failed_count": _status_count(files, {"failed"}),
        }
    )
    return item


def _catalog_sort_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("month") or ""),
        str(item.get("reviewed_at") or ""),
        str(item.get("title") or ""),
    )


def _empty_catalog_index_counts() -> dict[str, int]:
    return {
        "paper_count": 0,
        "reviewed_count": 0,
        "has_data_asset_count": 0,
        "has_internal_table_count": 0,
        "internal_table_count": 0,
        "external_resource_count": 0,
        "needs_review_count": 0,
        "review_status_warning_count": 0,
        "extraction_manifest_count": 0,
        "extraction_success_count": 0,
        "extraction_partial_count": 0,
        "extraction_failed_count": 0,
        "extraction_not_started_count": 0,
        "extraction_not_applicable_count": 0,
        "table_success_count": 0,
        "table_failed_count": 0,
        "file_success_count": 0,
        "file_failed_count": 0,
    }


def _add_catalog_index_counts(counts: dict[str, int], item: dict[str, Any]) -> None:
    counts["paper_count"] += 1
    if item.get("review_status") == "reviewed":
        counts["reviewed_count"] += 1
    if item.get("has_data_asset"):
        counts["has_data_asset_count"] += 1
    if item.get("has_internal_table"):
        counts["has_internal_table_count"] += 1
    counts["internal_table_count"] += int(item.get("internal_table_count") or 0)
    counts["external_resource_count"] += int(item.get("external_resource_count") or 0)
    if item.get("review_status") in {"needs_review", "partial", "unknown"}:
        counts["needs_review_count"] += 1
    if item.get("review_status_warning"):
        counts["review_status_warning_count"] += 1
    if item.get("extraction_manifest_present"):
        counts["extraction_manifest_count"] += 1

    extraction_status = str(item.get("extraction_status") or "")
    if extraction_status in EXTRACTION_STATUS_VALUES:
        counts[f"extraction_{extraction_status}_count"] += 1
    else:
        counts["extraction_failed_count"] += 1

    for field in (
        "table_success_count",
        "table_failed_count",
        "file_success_count",
        "file_failed_count",
    ):
        counts[field] += int(item.get(field) or 0)


def rebuild_catalog_index(literature_dir: Path, *, workspace: Path | None = None) -> dict[str, Any]:
    workspace = workspace or literature_dir.parent
    papers: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    for path in iter_catalog_review_paths(literature_dir):
        try:
            review = read_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            skipped.append({"path": relative_path(path, workspace=workspace), "error": f"{type(exc).__name__}: {exc}"})
            continue
        papers.append(_review_item(path, review, workspace=workspace))

    papers.sort(key=_catalog_sort_key, reverse=True)
    years: dict[str, dict[str, Any]] = {}
    for item in papers:
        year = str(item.get("year") or "unknown")
        bucket = years.setdefault(
            year,
            {
                "year": year,
                **_empty_catalog_index_counts(),
                "papers": [],
            },
        )
        _add_catalog_index_counts(bucket, item)
        bucket["papers"].append(item)

    year_records = [years[year] for year in sorted(years.keys(), reverse=True)]
    summary = _empty_catalog_index_counts()
    for item in papers:
        _add_catalog_index_counts(summary, item)
    summary["skipped_count"] = len(skipped)
    return {
        "schema_version": CATALOG_INDEX_SCHEMA_VERSION,
        "review_schema_version": CATALOG_REVIEW_SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "literature_dir": str(literature_dir),
        "summary": summary,
        "years": year_records,
        "papers": papers,
        "skipped": skipped,
    }


def _markdown_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|")


def _review_status_cell(paper: dict[str, Any]) -> str:
    status = str(paper.get("review_status") or "")
    if paper.get("review_status_warning"):
        return f"{status} (!)"
    return status


def _catalog_sources_cell(paper: dict[str, Any]) -> str:
    return f"{paper.get('internal_table_count', 0)} table, {paper.get('external_resource_count', 0)} external"


def _extraction_status_cell(paper: dict[str, Any]) -> str:
    status = str(paper.get("extraction_status") or "")
    run_status = str(paper.get("extraction_run_status") or "")
    if run_status and run_status != status:
        return f"{status} ({run_status})"
    return status


def _count_pair_cell(paper: dict[str, Any], success_field: str, failed_field: str) -> str:
    if not paper.get("extraction_manifest_present"):
        return "-"
    return f"{paper.get(success_field, 0)} ok, {paper.get(failed_field, 0)} failed"


def _semantics_cell(paper: dict[str, Any]) -> str:
    if not paper.get("extraction_manifest_present"):
        return "-"
    return f"{paper.get('file_success_count', 0)} files, {paper.get('file_failed_count', 0)} failed"


def render_catalog_index(record: dict[str, Any]) -> str:
    summary = record.get("summary") or {}
    papers = record.get("papers") or []
    years = record.get("years") or []
    lines = [
        "# Article Data Asset Workflow Index",
        "",
        f"- Generated at: {record.get('generated_at')}",
        f"- Reviewed papers: {summary.get('reviewed_count', 0)} / {summary.get('paper_count', 0)}",
        f"- Papers with data assets: {summary.get('has_data_asset_count', 0)}",
        f"- Papers with internal tables: {summary.get('has_internal_table_count', 0)}",
        f"- Internal tables: {summary.get('internal_table_count', 0)}",
        f"- External resources: {summary.get('external_resource_count', 0)}",
        f"- Papers needing review: {summary.get('needs_review_count', 0)}",
        f"- Extraction manifests: {summary.get('extraction_manifest_count', 0)}",
        (
            "- Extraction status: "
            f"{summary.get('extraction_success_count', 0)} success / "
            f"{summary.get('extraction_partial_count', 0)} partial / "
            f"{summary.get('extraction_failed_count', 0)} failed / "
            f"{summary.get('extraction_not_started_count', 0)} not started / "
            f"{summary.get('extraction_not_applicable_count', 0)} not applicable"
        ),
        (
            "- Tables: "
            f"{summary.get('table_success_count', 0)} success / "
            f"{summary.get('table_failed_count', 0)} failed"
        ),
        (
            "- Excerpt files: "
            f"{summary.get('file_success_count', 0)} success / "
            f"{summary.get('file_failed_count', 0)} failed"
        ),
    ]
    if summary.get("review_status_warning_count"):
        lines.append(f"- Review status warnings: {summary.get('review_status_warning_count')}")
    if summary.get("skipped_count"):
        lines.append(f"- Skipped malformed review files: {summary.get('skipped_count')}")

    lines.extend(
        [
            "",
            "## Status Legend",
            "",
            "- Review `reviewed`: data asset review is complete for the available paper/source context.",
            "- Review `partial`: data asset review is incomplete or has unresolved coverage questions.",
            "- Review `needs_review`: data asset review has not been completed yet.",
            "- Review `source_missing`: data asset review could not be completed from source files; `(!)` means the review says source is missing but the source metadata says it is available.",
            "- Extraction `success`: the current extraction run completed without table or excerpt-file failures.",
            "- Extraction `partial`: the current extraction run saved at least one table/excerpt file and also had failures.",
            "- Extraction `failed`: the current extraction run or manifest failed.",
            "- Extraction `not_started`: review found internal tables, but no extraction manifest exists yet.",
            "- Extraction `not_applicable`: review found no internal tables, so extraction is not needed.",
        ]
    )

    if papers:
        lines.extend(["", "## Papers", ""])
        lines.append(
            "| Paper | Month | Review | Data assets | Extraction | Tables | Files | Review JSON | Extraction JSON |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for paper in papers:
            title = _markdown_cell(paper.get("title") or "Untitled")
            arxiv_id = str(paper.get("arxiv_id") or "")
            label = f"{title} ({arxiv_id})" if arxiv_id else title
            review_path = str(paper.get("review_json_path") or "")
            review_link = f"[JSON]({review_path})" if review_path else ""
            extraction_path = str(paper.get("extraction_json_path") or "")
            extraction_link = f"[JSON]({extraction_path})" if extraction_path else ""
            lines.append(
                f"| {label} | {paper.get('month') or ''} | {_review_status_cell(paper)} | "
                f"{_catalog_sources_cell(paper)} | {_extraction_status_cell(paper)} | "
                f"{_count_pair_cell(paper, 'table_success_count', 'table_failed_count')} | "
                f"{_semantics_cell(paper)} | {review_link} | {extraction_link} |"
            )

    if years:
        lines.extend(["", "## Year Overview", ""])
        lines.append(
            "| Year | Papers | Reviewed | With data assets | Needs review | Extraction manifests | Success | Partial | Failed | Not started | N/A |"
        )
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for year in years:
            lines.append(
                f"| {year.get('year')} | {year.get('paper_count', 0)} | {year.get('reviewed_count', 0)} | "
                f"{year.get('has_data_asset_count', 0)} | {year.get('needs_review_count', 0)} | "
                f"{year.get('extraction_manifest_count', 0)} | {year.get('extraction_success_count', 0)} | "
                f"{year.get('extraction_partial_count', 0)} | {year.get('extraction_failed_count', 0)} | "
                f"{year.get('extraction_not_started_count', 0)} | "
                f"{year.get('extraction_not_applicable_count', 0)} |"
            )
    lines.append("")
    return "\n".join(lines)


def write_catalog_index_outputs(literature_dir: Path, *, workspace: Path | None = None) -> dict[str, Any]:
    index_record = rebuild_catalog_index(literature_dir, workspace=workspace)
    json_path = literature_dir / INDEX_JSON_FILENAME
    markdown_path = literature_dir / INDEX_MARKDOWN_FILENAME
    write_json(json_path, index_record)
    markdown_path.write_text(render_catalog_index(index_record), encoding="utf-8")
    return {
        "index_record": index_record,
        "index_json_path": str(json_path),
        "index_markdown_path": str(markdown_path),
    }


def cleanup_catalog_workflow_outputs(literature_dir: Path, *, dry_run: bool = False) -> dict[str, Any]:
    targets: list[Path] = []
    if not literature_dir.exists():
        return {
            "dry_run": dry_run,
            "literature_dir": str(literature_dir),
            "removed_count": 0,
            "removed": [],
        }
    for paper_dir in sorted(path for path in literature_dir.iterdir() if path.is_dir()):
        for name in (REVIEW_FILENAME, EXTRACTION_FILENAME, "catalog_sources", "catalog_tables"):
            candidate = paper_dir / name
            if candidate.exists():
                targets.append(candidate)
    for name in (INDEX_JSON_FILENAME, INDEX_MARKDOWN_FILENAME):
        candidate = literature_dir / name
        if candidate.exists():
            targets.append(candidate)

    removed: list[dict[str, str]] = []
    for target in targets:
        kind = "directory" if target.is_dir() else "file"
        if not dry_run:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        removed.append({"path": str(target), "kind": kind, "status": "would_remove" if dry_run else "removed"})
    return {
        "dry_run": dry_run,
        "literature_dir": str(literature_dir),
        "removed_count": len(removed),
        "removed": removed,
    }
