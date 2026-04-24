"""Catalog review inventory and index helpers."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


CATALOG_REVIEW_SCHEMA_VERSION = "stella.hvs_catalog.review.v1"
CATALOG_INVENTORY_SCHEMA_VERSION = "stella.hvs_catalog.inventory.v1"
CATALOG_INDEX_SCHEMA_VERSION = "stella.hvs_catalog.index.v1"

REVIEW_FILENAME = "catalog_review.json"
INDEX_JSON_FILENAME = "catalog_index.json"
INDEX_MARKDOWN_FILENAME = "catalog_index.md"

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


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
    review_meta = review.get("review") or {}
    candidates = review.get("catalog_candidates") or []
    external = review.get("external_resources") or []
    rejected = review.get("rejected_candidates") or []
    arxiv_id = str(paper.get("arxiv_id") or path.parent.name)
    month = str(paper.get("month") or "")
    year = month[:4] if month else ""
    status = str(review_meta.get("status") or "unknown")
    confidence_values: list[float] = []
    for item in candidates:
        if not isinstance(item, dict) or item.get("confidence") in {None, ""}:
            continue
        try:
            confidence_values.append(float(item.get("confidence")))
        except (TypeError, ValueError):
            continue
    return {
        "title": str(paper.get("title") or "Untitled"),
        "arxiv_id": arxiv_id,
        "month": month,
        "year": year,
        "review_status": status,
        "reviewed_at": str(review_meta.get("reviewed_at") or ""),
        "has_catalog": bool(candidates),
        "catalog_candidate_count": len(candidates) if isinstance(candidates, list) else 0,
        "external_resource_count": len(external) if isinstance(external, list) else 0,
        "rejected_candidate_count": len(rejected) if isinstance(rejected, list) else 0,
        "max_confidence": max(confidence_values) if confidence_values else None,
        "paper_dir": relative_path(path.parent, workspace=workspace),
        "review_json_path": relative_path(path, workspace=workspace),
    }


def _catalog_sort_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("month") or ""),
        str(item.get("reviewed_at") or ""),
        str(item.get("title") or ""),
    )


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
                "paper_count": 0,
                "reviewed_count": 0,
                "has_catalog_count": 0,
                "needs_review_count": 0,
                "papers": [],
            },
        )
        bucket["paper_count"] += 1
        if item.get("review_status") == "reviewed":
            bucket["reviewed_count"] += 1
        if item.get("has_catalog"):
            bucket["has_catalog_count"] += 1
        if item.get("review_status") in {"needs_review", "partial", "unknown"}:
            bucket["needs_review_count"] += 1
        bucket["papers"].append(item)

    year_records = [years[year] for year in sorted(years.keys(), reverse=True)]
    return {
        "schema_version": CATALOG_INDEX_SCHEMA_VERSION,
        "review_schema_version": CATALOG_REVIEW_SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "literature_dir": str(literature_dir),
        "summary": {
            "paper_count": len(papers),
            "reviewed_count": sum(1 for item in papers if item.get("review_status") == "reviewed"),
            "has_catalog_count": sum(1 for item in papers if item.get("has_catalog")),
            "needs_review_count": sum(
                1 for item in papers if item.get("review_status") in {"needs_review", "partial", "unknown"}
            ),
            "skipped_count": len(skipped),
        },
        "years": year_records,
        "papers": papers,
        "skipped": skipped,
    }


def render_catalog_index(record: dict[str, Any]) -> str:
    summary = record.get("summary") or {}
    papers = record.get("papers") or []
    years = record.get("years") or []
    lines = [
        "# High-Velocity Star Catalog Review Index",
        "",
        f"- Generated at: {record.get('generated_at')}",
        f"- Reviewed papers: {summary.get('reviewed_count', 0)} / {summary.get('paper_count', 0)}",
        f"- Papers with catalog candidates: {summary.get('has_catalog_count', 0)}",
        f"- Papers needing review: {summary.get('needs_review_count', 0)}",
    ]
    if summary.get("skipped_count"):
        lines.append(f"- Skipped malformed review files: {summary.get('skipped_count')}")

    if papers:
        lines.extend(["", "## Reviewed Papers", ""])
        lines.append("| Paper | Month | Status | Catalog candidates | External resources | Review JSON |")
        lines.append("| --- | --- | --- | ---: | ---: | --- |")
        for paper in papers:
            title = str(paper.get("title") or "Untitled").replace("|", "\\|")
            arxiv_id = str(paper.get("arxiv_id") or "")
            label = f"{title} ({arxiv_id})" if arxiv_id else title
            review_path = str(paper.get("review_json_path") or "")
            review_link = f"[JSON]({review_path})" if review_path else ""
            lines.append(
                f"| {label} | {paper.get('month') or ''} | {paper.get('review_status') or ''} | "
                f"{paper.get('catalog_candidate_count', 0)} | {paper.get('external_resource_count', 0)} | {review_link} |"
            )

    if years:
        lines.extend(["", "## Year Overview", ""])
        lines.append("| Year | Papers | Reviewed | With catalog | Needs review |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for year in years:
            lines.append(
                f"| {year.get('year')} | {year.get('paper_count', 0)} | {year.get('reviewed_count', 0)} | "
                f"{year.get('has_catalog_count', 0)} | {year.get('needs_review_count', 0)} |"
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
