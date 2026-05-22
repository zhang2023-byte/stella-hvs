"""Build the global HVS candidates index from per-paper literature_hvs_candidates.json files."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from high_velocity_lit.catalog_review import relative_path, write_json, read_json
from high_velocity_lit.schema_models import LiteratureHvsCandidatesRecord
from high_velocity_lit.schema_specs import LITERATURE_HVS_CANDIDATES_INDEX_SCHEMA_VERSION


HVS_CANDIDATES_INDEX_SCHEMA_VERSION = LITERATURE_HVS_CANDIDATES_INDEX_SCHEMA_VERSION
HVS_CANDIDATES_FILENAME = "literature_hvs_candidates.json"
INDEX_JSON_FILENAME = "literature_hvs_index.json"
INDEX_MARKDOWN_FILENAME = "literature_hvs_index.md"


def iter_hvs_candidates_paths(literature_dir: Path) -> list[Path]:
    """Return sorted paths to all literature_hvs_candidates.json files."""
    if not literature_dir.exists():
        return []
    return sorted(
        path
        for path in literature_dir.glob(f"*/{HVS_CANDIDATES_FILENAME}")
        if path.is_file() and path.parent.name not in {"catalog_sources", "catalog_tables"}
    )


def _extract_paper_labels(candidates: list[dict[str, Any]]) -> dict[str, int]:
    """Count candidates by non-exclusive paper label."""
    counts: dict[str, int] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        assessment = candidate.get("inclusion_assessment")
        labels = assessment.get("paper_labels") if isinstance(assessment, dict) else None
        if isinstance(labels, list) and labels:
            for label in labels:
                label_text = str(label or "unknown")
                counts[label_text] = counts.get(label_text, 0) + 1
        else:
            counts["unknown"] = counts.get("unknown", 0) + 1
    return counts


def _extract_inclusion_assessment_counts(candidates: list[dict[str, Any]], key: str) -> dict[str, int]:
    """Count candidates by one inclusion_assessment scalar key."""
    counts: dict[str, int] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        assessment = candidate.get("inclusion_assessment")
        if isinstance(assessment, dict):
            value = str(assessment.get(key) or "unknown")
        else:
            value = "unknown"
        counts[value] = counts.get(value, 0) + 1
    return counts


def _extract_candidate_origins(candidates: list[dict[str, Any]]) -> dict[str, int]:
    """Count candidates by candidate_origin.origin_type."""
    counts: dict[str, int] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        origin = candidate.get("candidate_origin")
        origin_type = str(origin.get("origin_type") or "unknown") if isinstance(origin, dict) else "unknown"
        counts[origin_type] = counts.get(origin_type, 0) + 1
    return counts


def _extract_sample_identifier_values(candidates: list[dict[str, Any]], key: str, max_count: int = 5) -> list[str]:
    """Extract sample identifier values from candidates."""
    values: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        ids = candidate.get("identifiers")
        if isinstance(ids, dict):
            value = str(ids.get(key) or "").strip()
            if value:
                values.append(value)
        if len(values) >= max_count:
            break
    return values


def _hvs_paper_item(
    path: Path,
    payload: dict[str, Any],
    *,
    workspace: Path,
) -> dict[str, Any]:
    """Build an index item for one paper's HVS candidates extraction."""
    paper = payload.get("paper") if isinstance(payload.get("paper"), dict) else {}
    extraction = payload.get("extraction") if isinstance(payload.get("extraction"), dict) else {}
    candidates = payload.get("candidates") if isinstance(payload.get("candidates"), list) else []
    inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}

    arxiv_id = str(paper.get("arxiv_id") or path.parent.name)
    month = str(paper.get("month") or "")
    year = month.split("-")[0] if month else "unknown"
    status = str(extraction.get("status") or "")
    candidate_count = len(candidates)
    paper_labels = _extract_paper_labels(candidates)
    galactic_bound_claims = _extract_inclusion_assessment_counts(candidates, "galactic_bound_claim")
    inclusion_bases = _extract_inclusion_assessment_counts(candidates, "inclusion_basis")
    candidate_origins = _extract_candidate_origins(candidates)
    sample_paper_candidate_ids = _extract_sample_identifier_values(candidates, "paper_candidate_id")
    sample_gaia_source_ids = _extract_sample_identifier_values(candidates, "gaia_source_id")

    paper_dir = path.parent
    review_path = paper_dir / "catalog_review.json"
    extraction_json_path = paper_dir / "catalog_extraction.json"

    item: dict[str, Any] = {
        "arxiv_id": arxiv_id,
        "title": str(paper.get("title") or ""),
        "month": month,
        "year": year,
        "extraction_status": status,
        "candidate_count": candidate_count,
        "paper_labels": paper_labels,
        "galactic_bound_claims": galactic_bound_claims,
        "inclusion_bases": inclusion_bases,
        "candidate_origins": candidate_origins,
        "sample_paper_candidate_ids": sample_paper_candidate_ids,
        "sample_gaia_source_ids": sample_gaia_source_ids,
        "paper_dir": relative_path(paper_dir, workspace=workspace),
        "candidates_json_path": relative_path(path, workspace=workspace),
    }

    if review_path.exists():
        item["review_json_path"] = relative_path(review_path, workspace=workspace)
    if extraction_json_path.exists():
        item["extraction_json_path"] = relative_path(extraction_json_path, workspace=workspace)

    extracted_at = extraction.get("extracted_at")
    if extracted_at:
        item["extracted_at"] = str(extracted_at)

    return item


def _empty_hvs_index_counts() -> dict[str, Any]:
    return {
        "paper_count": 0,
        "candidates_found_count": 0,
        "no_candidates_count": 0,
        "partial_count": 0,
        "needs_review_count": 0,
        "source_missing_count": 0,
        "total_candidate_count": 0,
        "total_by_paper_label": {},
        "total_by_galactic_bound_claim": {},
        "total_by_inclusion_basis": {},
        "total_by_origin": {},
    }


def _add_hvs_index_counts(bucket: dict[str, Any], item: dict[str, Any]) -> None:
    bucket["paper_count"] += 1
    status = item.get("extraction_status") or ""
    if status == "candidates_found":
        bucket["candidates_found_count"] += 1
    elif status == "no_candidates":
        bucket["no_candidates_count"] += 1
    elif status == "partial":
        bucket["partial_count"] += 1
    elif status == "needs_review":
        bucket["needs_review_count"] += 1
    elif status == "source_missing":
        bucket["source_missing_count"] += 1

    candidate_count = item.get("candidate_count") or 0
    bucket["total_candidate_count"] += candidate_count

    for label, count in (item.get("paper_labels") or {}).items():
        bucket["total_by_paper_label"][label] = bucket["total_by_paper_label"].get(label, 0) + count
    for claim, count in (item.get("galactic_bound_claims") or {}).items():
        bucket["total_by_galactic_bound_claim"][claim] = (
            bucket["total_by_galactic_bound_claim"].get(claim, 0) + count
        )
    for basis, count in (item.get("inclusion_bases") or {}).items():
        bucket["total_by_inclusion_basis"][basis] = bucket["total_by_inclusion_basis"].get(basis, 0) + count
    for origin_key, count in (item.get("candidate_origins") or {}).items():
        bucket["total_by_origin"][origin_key] = bucket["total_by_origin"].get(origin_key, 0) + count


def _catalog_sort_key(item: dict[str, Any]) -> tuple[str, ...]:
    """Sort by year desc, month desc, arxiv_id desc."""
    month = str(item.get("month") or "")
    year = str(item.get("year") or "")
    arxiv_id = str(item.get("arxiv_id") or "")
    return (year, month, arxiv_id)


def rebuild_hvs_candidates_index(
    literature_dir: Path,
    *,
    workspace: Path | None = None,
) -> dict[str, Any]:
    """Rebuild the HVS candidates index from all per-paper JSON files."""
    workspace = workspace or literature_dir.parent
    papers: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    for path in iter_hvs_candidates_paths(literature_dir):
        try:
            payload = read_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            skipped.append({"path": relative_path(path, workspace=workspace), "error": f"{type(exc).__name__}: {exc}"})
            continue
        try:
            LiteratureHvsCandidatesRecord.model_validate(payload)
        except Exception as exc:
            skipped.append({"path": relative_path(path, workspace=workspace), "error": f"{type(exc).__name__}: {exc}"})
            continue
        papers.append(_hvs_paper_item(path, payload, workspace=workspace))

    papers.sort(key=_catalog_sort_key, reverse=True)

    years: dict[str, dict[str, Any]] = {}
    for item in papers:
        year = str(item.get("year") or "unknown")
        bucket = years.setdefault(
            year,
            {
                "year": year,
                **_empty_hvs_index_counts(),
                "papers": [],
            },
        )
        _add_hvs_index_counts(bucket, item)
        bucket["papers"].append(item)

    year_records = [years[year] for year in sorted(years.keys(), reverse=True)]
    summary = _empty_hvs_index_counts()
    for item in papers:
        _add_hvs_index_counts(summary, item)
    summary["skipped_count"] = len(skipped)

    return {
        "schema_version": HVS_CANDIDATES_INDEX_SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "literature_dir": str(literature_dir),
        "summary": summary,
        "years": year_records,
        "papers": papers,
        "skipped": skipped,
    }


def _markdown_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|")


def _status_badge(status: str) -> str:
    """Return a short status label for markdown tables."""
    badges = {
        "candidates_found": "candidates found",
        "no_candidates": "no candidates",
        "partial": "partial",
        "needs_review": "needs review",
        "source_missing": "source missing",
    }
    return badges.get(status, status)


def _counts_cell(counts: dict[str, int]) -> str:
    if not counts:
        return "-"
    parts = []
    for key in sorted(counts.keys()):
        parts.append(f"{key}: {counts[key]}")
    return "; ".join(parts)


def _identifiers_cell(identifiers: list[str]) -> str:
    if not identifiers:
        return "-"
    return ", ".join(identifiers)


def render_hvs_candidates_index(record: dict[str, Any]) -> str:
    """Render the HVS candidates index as Markdown."""
    summary = record.get("summary") or {}
    papers = record.get("papers") or []
    years = record.get("years") or []

    lines = [
        "# Literature HVS Candidates Index",
        "",
        f"- Generated at: {record.get('generated_at')}",
        f"- Papers with candidate extractions: {summary.get('paper_count', 0)}",
        f"- Candidates found: {summary.get('candidates_found_count', 0)}",
        f"- No candidates: {summary.get('no_candidates_count', 0)}",
        f"- Partial extractions: {summary.get('partial_count', 0)}",
        f"- Needs review: {summary.get('needs_review_count', 0)}",
        f"- Source missing: {summary.get('source_missing_count', 0)}",
        f"- Total candidates: {summary.get('total_candidate_count', 0)}",
    ]

    total_by_label = summary.get("total_by_paper_label") or {}
    if total_by_label:
        label_parts = [f"{k}: {v}" for k, v in sorted(total_by_label.items())]
        lines.append(f"- By paper label: {', '.join(label_parts)}")
    total_by_bound_claim = summary.get("total_by_galactic_bound_claim") or {}
    if total_by_bound_claim:
        claim_parts = [f"{k}: {v}" for k, v in sorted(total_by_bound_claim.items())]
        lines.append(f"- By Galactic bound claim: {', '.join(claim_parts)}")
    total_by_basis = summary.get("total_by_inclusion_basis") or {}
    if total_by_basis:
        basis_parts = [f"{k}: {v}" for k, v in sorted(total_by_basis.items())]
        lines.append(f"- By inclusion basis: {', '.join(basis_parts)}")
    total_by_origin = summary.get("total_by_origin") or {}
    if total_by_origin:
        origin_parts = [f"{k}: {v}" for k, v in sorted(total_by_origin.items())]
        lines.append(f"- By origin: {', '.join(origin_parts)}")

    skipped_count = summary.get("skipped_count", 0)
    if skipped_count:
        lines.append(f"- Skipped malformed files: {skipped_count}")

    lines.extend(
        [
            "",
            "## Status Legend",
            "",
            "- `candidates_found`: extraction completed and at least one candidate was identified.",
            "- `no_candidates`: extraction completed but no objects met inclusion boundaries.",
            "- `partial`: extraction is incomplete or has unresolved coverage questions.",
            "- `needs_review`: extraction has not been completed yet.",
            "- `source_missing`: extraction could not be completed because source files are missing.",
        ]
    )

    if papers:
        lines.extend(["", "## Papers", ""])
        lines.append(
            "| Paper | Month | Status | Candidates | Paper labels | Bound claims | Inclusion bases | Origin breakdown | Sample paper candidate IDs | Sample Gaia source IDs | Candidates JSON |"
        )
        lines.append("| --- | --- | --- | ---: | --- | --- | --- | --- | --- | --- | --- |")
        for paper in papers:
            title = _markdown_cell(paper.get("title") or "Untitled")
            arxiv_id = str(paper.get("arxiv_id") or "")
            label = f"{title} ({arxiv_id})" if arxiv_id else title
            candidates_path = str(paper.get("candidates_json_path") or "")
            candidates_link = f"[JSON]({candidates_path})" if candidates_path else ""
            lines.append(
                f"| {label} | {paper.get('month') or ''} | {_status_badge(paper.get('extraction_status') or '')} | "
                f"{paper.get('candidate_count', 0)} | {_counts_cell(paper.get('paper_labels') or {})} | "
                f"{_counts_cell(paper.get('galactic_bound_claims') or {})} | "
                f"{_counts_cell(paper.get('inclusion_bases') or {})} | "
                f"{_counts_cell(paper.get('candidate_origins') or {})} | "
                f"{_identifiers_cell(paper.get('sample_paper_candidate_ids') or [])} | "
                f"{_identifiers_cell(paper.get('sample_gaia_source_ids') or [])} | {candidates_link} |"
            )

    if years:
        lines.extend(["", "## Year Overview", ""])
        lines.append(
            "| Year | Papers | Candidates found | No candidates | Partial | Needs review | Source missing | Total candidates |"
        )
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for year in years:
            lines.append(
                f"| {year.get('year')} | {year.get('paper_count', 0)} | "
                f"{year.get('candidates_found_count', 0)} | {year.get('no_candidates_count', 0)} | "
                f"{year.get('partial_count', 0)} | {year.get('needs_review_count', 0)} | "
                f"{year.get('source_missing_count', 0)} | {year.get('total_candidate_count', 0)} |"
            )

    lines.append("")
    return "\n".join(lines)


def write_hvs_candidates_index_outputs(
    literature_dir: Path,
    *,
    workspace: Path | None = None,
) -> dict[str, Any]:
    """Rebuild and write both JSON and Markdown index files."""
    index_record = rebuild_hvs_candidates_index(literature_dir, workspace=workspace)
    json_path = literature_dir / INDEX_JSON_FILENAME
    markdown_path = literature_dir / INDEX_MARKDOWN_FILENAME
    write_json(json_path, index_record)
    markdown_path.write_text(render_hvs_candidates_index(index_record), encoding="utf-8")
    return {
        "index_record": index_record,
        "index_json_path": str(json_path),
        "index_markdown_path": str(markdown_path),
    }
