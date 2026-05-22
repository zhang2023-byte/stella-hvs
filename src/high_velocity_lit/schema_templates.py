"""Template builders for Stella JSON fact sources."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .catalog_extraction import parse_latex_table_excerpt
from .catalog_review import build_catalog_candidate_inventory, relative_path
from .schema_models import (
    BoundAssessment,
    CatalogReviewRecord,
    CandidateCore,
    DerivedKinematics,
    ExternalResource,
    ExternalResourceSourceRef,
    HvsExtractionMeta,
    HvsInputs,
    HvsPaper,
    InternalTable,
    LinkSet,
    LiteratureHvsCandidatesRecord,
    ObservedPhaseSpace,
    ReviewColumn,
    ReviewMeta,
    ReviewPaper,
    ReviewSource,
    ReviewTableSourceRef,
    dump_template,
)
from .schema_specs import CATALOG_REVIEW_SCHEMA_VERSION, LITERATURE_HVS_CANDIDATES_SCHEMA_VERSION


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_workspace_path(value: str, *, workspace: Path, fallback_dir: Path | None = None) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    workspace_path = workspace / path
    if workspace_path.exists() or len(path.parts) > 1:
        return workspace_path
    return (fallback_dir or workspace) / path


def _ads_bibcode_from_payload(payload: dict[str, Any]) -> str:
    docs = ((payload.get("response") or {}).get("docs") or []) if isinstance(payload, dict) else []
    if not docs or not isinstance(docs[0], dict):
        return ""
    return str(docs[0].get("bibcode") or "").strip()


def _paper_bibcode_from_audit(audit: dict[str, Any], *, workspace: Path, paper_dir: Path) -> str:
    metadata = audit.get("ads_metadata")
    if isinstance(metadata, dict):
        legacy_bibcode = str(metadata.get("ads_bibcode") or "").strip()
        if legacy_bibcode:
            return legacy_bibcode
        local_path = str(metadata.get("local_path") or "").strip()
        if local_path:
            path = _resolve_workspace_path(local_path, workspace=workspace, fallback_dir=paper_dir)
            if path.exists():
                try:
                    return _ads_bibcode_from_payload(read_json(path))
                except Exception:
                    return ""
    return ""


def safe_slug(value: str, *, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-")
    return cleaned or fallback


def unique_id(base: str, seen: set[str]) -> str:
    candidate = base
    suffix = 2
    while candidate in seen:
        candidate = f"{base}-{suffix}"
        suffix += 1
    seen.add(candidate)
    return candidate


def _links_from(value: Any) -> LinkSet:
    links = value if isinstance(value, dict) else {}
    return LinkSet(abs=str(links.get("abs") or ""), pdf=str(links.get("pdf") or ""))


def _review_columns_from_latex(excerpt: str) -> list[ReviewColumn]:
    parsed = parse_latex_table_excerpt(excerpt)
    columns = []
    for column in parsed.get("columns") or []:
        if not isinstance(column, dict):
            continue
        original_header = str(column.get("original_header") or column.get("name") or "")
        columns.append(
            ReviewColumn(
                name=original_header or str(column.get("name") or ""),
                meaning="",
                unit_text=str(column.get("unit_text") or ""),
                source_of_definition="table header",
                confidence=0.0,
            )
        )
    return columns


def build_catalog_review_template(
    *,
    literature_dir: Path,
    arxiv_id: str,
    workspace: Path | None = None,
) -> dict[str, Any]:
    """Build a strict catalog_review.json skeleton from archived paper assets."""

    workspace = workspace or literature_dir.parent
    inventory = build_catalog_candidate_inventory(
        literature_dir=literature_dir,
        arxiv_id=arxiv_id,
        workspace=workspace,
    )
    now = datetime.now().isoformat(timespec="seconds")
    paper = inventory.get("paper") if isinstance(inventory.get("paper"), dict) else {}
    source = inventory.get("source") if isinstance(inventory.get("source"), dict) else {}
    seen_ids: set[str] = set()

    internal_tables: list[InternalTable] = []
    for index, item in enumerate(inventory.get("table_candidates") or [], start=1):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "")
        base_id = "table-" + safe_slug(label, fallback=f"{index:03d}") if label else f"table-{index:03d}"
        table_id = unique_id(base_id, seen_ids)
        source_ref = ReviewTableSourceRef(
            path=str(item.get("path") or ""),
            start_line=int(item.get("start_line") or 0),
            end_line=int(item.get("end_line") or 0),
            caption=str(item.get("caption") or ""),
            label=label,
        )
        internal_tables.append(
            InternalTable(
                id=table_id,
                kind="latex_table",
                asset_type="",
                role_in_paper="",
                source_refs=[source_ref],
                columns=_review_columns_from_latex(str(item.get("latex_excerpt") or "")),
                evidence=str(item.get("caption") or ""),
                comments="",
            )
        )

    external_resources: list[ExternalResource] = []
    for index, item in enumerate(inventory.get("external_resource_mentions") or [], start=1):
        if not isinstance(item, dict):
            continue
        resource_id = unique_id(f"resource-{index:03d}", seen_ids)
        line = int(item.get("line") or 0)
        external_resources.append(
            ExternalResource(
                id=resource_id,
                kind="external_url" if item.get("url") else "external_resource_mention",
                url=str(item.get("url") or ""),
                local_path="",
                description="",
                source_refs=[
                    ExternalResourceSourceRef(
                        path=str(item.get("path") or ""),
                        start_line=line,
                        end_line=line,
                        context=str(item.get("context") or ""),
                    )
                ],
                evidence=str(item.get("context") or ""),
                comments="",
            )
        )

    local_resource_start = len(external_resources) + 1
    for offset, item in enumerate(inventory.get("local_machine_readable_files") or [], start=local_resource_start):
        if not isinstance(item, dict):
            continue
        resource_id = unique_id(f"resource-{offset:03d}", seen_ids)
        external_resources.append(
            ExternalResource(
                id=resource_id,
                kind="local_machine_readable_file",
                url="",
                local_path=str(item.get("path") or ""),
                description="",
                source_refs=[],
                evidence="",
                comments=f"Discovered local machine-readable file with suffix {item.get('suffix') or ''}.",
            )
        )

    record = CatalogReviewRecord(
        schema_version=CATALOG_REVIEW_SCHEMA_VERSION,
        paper=ReviewPaper(
            arxiv_id=arxiv_id,
            title=str(paper.get("title") or ""),
            month=str(paper.get("month") or ""),
            source_note_json=str(paper.get("source_note_json") or ""),
            links=_links_from(paper.get("links")),
        ),
        source=ReviewSource(
            paper_dir=str(source.get("paper_dir") or relative_path(literature_dir / arxiv_id, workspace=workspace)),
            audit_path=str(source.get("audit_path") or ""),
            source_dir=str(source.get("source_dir") or ""),
            tex_root=str(source.get("tex_root") or ""),
            source_available=bool(source.get("source_available")),
        ),
        review=ReviewMeta(
            status="needs_review",
            reviewed_at=now,
            reviewer="agent",
            summary="",
        ),
        internal_tables=internal_tables,
        external_resources=external_resources,
    )
    return dump_template(record)


def _paper_from_month_json(audit: dict[str, Any], *, workspace: Path) -> dict[str, Any]:
    note_path_text = str(audit.get("source_note_json") or "").strip()
    if not note_path_text:
        return {}
    note_path = Path(note_path_text)
    if not note_path.is_absolute():
        note_path = workspace / note_path
    if not note_path.exists():
        return {}
    month_record = read_json(note_path)
    arxiv_id = str(audit.get("arxiv_id") or "").strip()
    for paper in month_record.get("papers") or []:
        if isinstance(paper, dict) and str(paper.get("arxiv_id") or "").strip() == arxiv_id:
            return paper
    return {}


def build_hvs_candidates_template(
    *,
    literature_dir: Path,
    arxiv_id: str,
    workspace: Path | None = None,
) -> dict[str, Any]:
    """Build a strict literature_hvs_candidates.json skeleton."""

    workspace = workspace or literature_dir.parent
    paper_dir = literature_dir / arxiv_id
    audit_path = paper_dir / "audit.json"
    review_path = paper_dir / "catalog_review.json"
    extraction_path = paper_dir / "catalog_extraction.json"
    audit = read_json(audit_path) if audit_path.exists() else {}
    month_paper = _paper_from_month_json(audit, workspace=workspace)
    extraction = read_json(extraction_path) if extraction_path.exists() else {}
    extraction_tables = extraction.get("tables") if isinstance(extraction.get("tables"), list) else []
    ecsv_paths = [
        str(table.get("ecsv_path") or "")
        for table in extraction_tables
        if isinstance(table, dict) and table.get("status") in {"success", "skipped_existing"} and table.get("ecsv_path")
    ]
    links = month_paper.get("links") if isinstance(month_paper.get("links"), dict) else {}
    now = datetime.now().isoformat(timespec="seconds")
    record = LiteratureHvsCandidatesRecord(
        schema_version=LITERATURE_HVS_CANDIDATES_SCHEMA_VERSION,
        generated_at=now,
        paper=HvsPaper(
            arxiv_id=arxiv_id,
            bibcode=_paper_bibcode_from_audit(audit, workspace=workspace, paper_dir=paper_dir) or None,
            title=str(month_paper.get("title") or audit.get("title") or ""),
            month=str(audit.get("month") or month_paper.get("month") or ""),
            source_note_json=str(audit.get("source_note_json") or ""),
            links=_links_from(links),
        ),
        inputs=HvsInputs(
            paper_dir=relative_path(paper_dir, workspace=workspace),
            audit_path=relative_path(audit_path, workspace=workspace) if audit_path.exists() else "",
            catalog_review_path=relative_path(review_path, workspace=workspace),
            catalog_extraction_path=relative_path(extraction_path, workspace=workspace),
            ecsv_paths=ecsv_paths,
        ),
        extraction=HvsExtractionMeta(
            status="needs_review",
            extracted_at=now,
            extractor="agent",
            summary="",
        ),
        method_chain=[],
        candidates=[],
        candidate_groups_considered=[],
    )
    return dump_template(record)


def empty_candidate_core() -> dict[str, Any]:
    """Return the standard empty HVS candidate core groups."""

    return dump_template(
        CandidateCore(
            observed_phase_space=ObservedPhaseSpace(),
            derived_kinematics=DerivedKinematics(),
            bound_assessment=BoundAssessment(),
        )
    )
