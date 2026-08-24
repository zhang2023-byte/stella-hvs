"""Paper-level index over ``literature_hvs_contributions`` documents.

Reads only the contribution artifact family and derives a value-free paper
index with delivery and quantity-status counts. Old
``literature_hvs_candidates`` index builders stay untouched.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stella.lit.hvs_contribution_models import (
    validate_literature_hvs_contributions_document,
)
from stella.schema_registry import schema_ref

INDEX_JSON_FILENAME = "01_literature_hvs_contributions_index.json"
INDEX_MARKDOWN_FILENAME = "01_literature_hvs_contributions_index.md"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_contribution_documents(
    literature_dir: Path,
) -> tuple[list[tuple[Path, dict[str, Any]]], list[dict[str, Any]]]:
    """Load and validate every contribution document under literature/."""

    documents: list[tuple[Path, dict[str, Any]]] = []
    skipped: list[dict[str, Any]] = []
    for paper_dir in sorted(Path(literature_dir).iterdir()):
        if not paper_dir.is_dir():
            continue
        path = paper_dir / "literature_hvs_contributions.json"
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            validate_literature_hvs_contributions_document(payload)
        except Exception as exc:
            skipped.append({"path": str(path), "reason": str(exc)})
            continue
        documents.append((path, payload))
    return documents, skipped


def build_hvs_contributions_index(
    literature_dir: Path,
) -> dict[str, Any]:
    """Build the paper-level contribution index record."""

    documents, skipped = load_contribution_documents(literature_dir)
    papers = []
    status_counts = {"complete": 0, "partial": 0, "failed": 0}
    roster_counts = {"contributions_found": 0, "no_contributions": 0, "null": 0}
    quantity_counts = {"complete": 0, "failed": 0}
    total_contributions = 0
    total_reviewed_exclusions = 0
    for path, payload in sorted(documents, key=lambda item: str(item[1]["paper"]["arxiv_id"])):
        arxiv_id = payload["paper"]["arxiv_id"]
        extraction = payload.get("extraction") or {}
        roster_status = extraction.get("roster_status")
        contributions = payload.get("object_contributions") or []
        status_counts[extraction.get("status") or "failed"] = status_counts.get(
            extraction.get("status") or "failed", 0
        ) + 1
        roster_key = roster_status if roster_status in roster_counts else "null"
        roster_counts[roster_key] += 1
        type_counts: dict[str, int] = {}
        for contribution in contributions:
            quantity_counts[contribution.get("quantity_extraction_status") or "?"] = (
                quantity_counts.get(contribution.get("quantity_extraction_status") or "?", 0) + 1
            )
            contribution_type = contribution.get("contribution_type") or ""
            type_counts[contribution_type] = type_counts.get(contribution_type, 0) + 1
        papers.append(
            {
                "arxiv_id": arxiv_id,
                "extraction_status": extraction.get("status"),
                "roster_status": roster_status,
                "contribution_count": len(contributions),
                "contribution_types": type_counts,
                "reviewed_exclusion_count": len(payload.get("reviewed_exclusions") or []),
                "contributions_json_path": str(path),
                "contributions_sha256": _sha256_file(path),
            }
        )
        total_contributions += len(contributions)
        total_reviewed_exclusions += len(payload.get("reviewed_exclusions") or [])
    return {
        "schema": schema_ref("literature_hvs_contributions.index"),
        "generated_at": _utc_now(),
        "summary": {
            "paper_count": len(papers),
            "status_counts": status_counts,
            "roster_counts": roster_counts,
            "quantity_extraction_counts": quantity_counts,
            "total_contributions": total_contributions,
            "total_reviewed_exclusions": total_reviewed_exclusions,
            "skipped_count": len(skipped),
        },
        "papers": papers,
        "skipped": skipped,
    }


def render_hvs_contributions_index(record: dict[str, Any]) -> str:
    summary = record.get("summary") or {}
    lines = [
        "# Literature HVS Contributions Index",
        "",
        f"- Generated at: {record.get('generated_at')}",
        f"- Papers with contribution extractions: {summary.get('paper_count', 0)}",
        f"- Total contributions: {summary.get('total_contributions', 0)}",
        f"- Total reviewed exclusions: {summary.get('total_reviewed_exclusions', 0)}",
        "- This index covers the pre-campaign contribution-first artifact family.",
        "",
        "## Papers",
        "",
        "| Paper | Status | Roster | Contributions | Reviewed exclusions | JSON |",
        "| --- | --- | --- | ---: | ---: | --- |",
    ]
    for paper in record.get("papers") or []:
        lines.append(
            f"| {paper.get('arxiv_id')} | {paper.get('extraction_status')} | "
            f"{paper.get('roster_status')} | {paper.get('contribution_count', 0)} | "
            f"{paper.get('reviewed_exclusion_count', 0)} | "
            f"[JSON]({paper.get('contributions_json_path')}) |"
        )
    lines.append("")
    return "\n".join(lines)


def write_hvs_contributions_index_outputs(literature_dir: Path) -> dict[str, Any]:
    record = build_hvs_contributions_index(literature_dir)
    json_path = Path(literature_dir) / INDEX_JSON_FILENAME
    markdown_path = Path(literature_dir) / INDEX_MARKDOWN_FILENAME
    json_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    markdown_path.write_text(render_hvs_contributions_index(record), encoding="utf-8")
    return {
        "index_record": record,
        "index_json_path": str(json_path),
        "index_markdown_path": str(markdown_path),
    }


def build(payload: dict, *, root: Path, paper_id: str | None = None) -> dict:
    """literature.build_contribution_index adapter."""

    from stella.workflows import operation_complete, operation_failed

    literature_dir = Path(root) / "literature"
    if not literature_dir.is_dir() or not any(literature_dir.glob("*/literature_hvs_contributions.json")):
        return operation_failed(
            "no canonical contribution documents found to index",
            kind="precondition",
        )
    outputs = write_hvs_contributions_index_outputs(literature_dir)
    return operation_complete(
        artifacts=[outputs["index_json_path"], outputs["index_markdown_path"]],
        index=outputs["index_record"],
    )


def validate_index(payload: dict, result: dict, *, root: Path) -> list[str]:
    """A completed index build must leave parseable index outputs."""

    if result.get("status") != "complete":
        return []
    errors: list[str] = []
    literature_dir = Path(root) / "literature"
    for filename in (INDEX_JSON_FILENAME, INDEX_MARKDOWN_FILENAME):
        path = literature_dir / filename
        if not path.is_file():
            errors.append(f"index build reported complete but {path} is missing")
    if (literature_dir / INDEX_JSON_FILENAME).is_file():
        try:
            json.loads((literature_dir / INDEX_JSON_FILENAME).read_text(encoding="utf-8"))
        except ValueError as error:
            errors.append(f"index artifact is not parseable: {error}")
    return errors
