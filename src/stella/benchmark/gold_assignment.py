"""Public, value-free assignment of benchmark papers to expert annotators."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stella.benchmark.campaign import sha256_file
from stella.benchmark.gold import validate_annotator_handle
from stella.benchmark.paths import validate_path_segment
from stella.schema_registry import (
    require_campaign_readable,
    require_campaign_writable,
    require_schema,
    schema_ref,
)


def load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return payload


def _campaign_identity(
    campaign_path: Path, *, require_writable: bool
) -> tuple[dict[str, Any], str, list[str]]:
    campaign = load_json_object(campaign_path, label="campaign manifest")
    require_schema(campaign, "benchmark.campaign", require_current=True)
    campaign_id = (
        require_campaign_writable(str(campaign.get("campaign_id") or ""))
        if require_writable
        else require_campaign_readable(str(campaign.get("campaign_id") or ""))
    )
    papers = campaign.get("papers")
    if not isinstance(papers, list):
        raise ValueError("campaign papers must be a list")
    paper_ids = [
        str(paper.get("arxiv_id") or "") if isinstance(paper, dict) else ""
        for paper in papers
    ]
    if not all(paper_ids) or len(paper_ids) != len(set(paper_ids)):
        raise ValueError("campaign papers require unique non-empty arxiv_id values")
    return campaign, campaign_id, paper_ids


def _normalized_papers(
    paper_ids: list[str], assignments: dict[str, dict[str, object]]
) -> list[dict[str, object]]:
    supplied = set(assignments)
    expected = set(paper_ids)
    missing = sorted(expected - supplied)
    extra = sorted(supplied - expected)
    if missing or extra:
        parts = []
        if missing:
            parts.append("missing: " + ", ".join(missing))
        if extra:
            parts.append("extra: " + ", ".join(extra))
        raise ValueError(
            "assignments must exactly cover the campaign; " + "; ".join(parts)
        )

    papers: list[dict[str, object]] = []
    for arxiv_id in paper_ids:
        assignment = assignments[arxiv_id]
        if not isinstance(assignment, dict):
            raise ValueError(f"assignment must be an object: {arxiv_id}")
        if set(assignment) != {"primary_annotator", "additional_annotators"}:
            raise ValueError(
                f"assignment fields must be primary_annotator and additional_annotators: {arxiv_id}"
            )
        primary = validate_annotator_handle(
            str(assignment.get("primary_annotator") or "")
        )
        additional_raw = assignment.get("additional_annotators")
        if not isinstance(additional_raw, list):
            raise ValueError(f"additional_annotators must be a list: {arxiv_id}")
        additional = [
            validate_annotator_handle(value) for value in additional_raw
        ]
        if len(additional) != len(set(additional)):
            raise ValueError(f"additional annotators must be unique: {arxiv_id}")
        if primary in additional:
            raise ValueError(
                f"primary annotator cannot also be additional: {arxiv_id}/{primary}"
            )
        papers.append(
            {
                "arxiv_id": arxiv_id,
                "primary_annotator": primary,
                "additional_annotators": additional,
            }
        )
    return papers


def build_gold_assignment(
    *,
    campaign_path: Path,
    assignment_id: str,
    assignments: dict[str, dict[str, object]],
) -> dict[str, Any]:
    """Build one complete public assignment profile in campaign order."""

    safe_id = validate_path_segment(assignment_id, "gold assignment id")
    _, campaign_id, paper_ids = _campaign_identity(
        campaign_path, require_writable=True
    )
    papers = _normalized_papers(paper_ids, assignments)
    return {
        "schema": schema_ref("benchmark.gold_assignment"),
        "assignment_id": safe_id,
        "campaign": {
            "campaign_id": campaign_id,
            "sha256": sha256_file(campaign_path),
        },
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "papers": papers,
    }


def load_gold_assignment(path: Path, campaign_path: Path) -> dict[str, Any]:
    """Validate an assignment profile against the exact current campaign."""

    profile = load_json_object(path, label="gold assignment profile")
    require_schema(profile, "benchmark.gold_assignment", require_current=True)
    assignment_id = validate_path_segment(
        str(profile.get("assignment_id") or ""), "gold assignment id"
    )
    if path.name != f"{assignment_id}.json":
        raise ValueError("gold assignment filename must match assignment_id")
    _, campaign_id, paper_ids = _campaign_identity(
        campaign_path, require_writable=False
    )
    expected_campaign = {
        "campaign_id": campaign_id,
        "sha256": sha256_file(campaign_path),
    }
    if profile.get("campaign") != expected_campaign:
        raise ValueError("gold assignment campaign binding does not match campaign")
    raw_papers = profile.get("papers")
    if not isinstance(raw_papers, list):
        raise ValueError("gold assignment papers must be a list")
    assignments: dict[str, dict[str, object]] = {}
    for paper in raw_papers:
        if not isinstance(paper, dict):
            raise ValueError("gold assignment papers must contain objects")
        arxiv_id = str(paper.get("arxiv_id") or "")
        if arxiv_id in assignments:
            raise ValueError(f"duplicate gold assignment paper: {arxiv_id}")
        assignments[arxiv_id] = {
            "primary_annotator": paper.get("primary_annotator"),
            "additional_annotators": paper.get("additional_annotators"),
        }
    normalized = _normalized_papers(paper_ids, assignments)
    if raw_papers != normalized:
        raise ValueError("gold assignment papers must match exact campaign order and fields")
    return profile


def primary_annotator_map(
    profile: dict[str, Any], paper_ids: list[str]
) -> dict[str, str]:
    """Return the primary scorer mapping for an exact requested paper subset."""

    require_schema(profile, "benchmark.gold_assignment", require_current=True)
    by_id = {
        str(paper.get("arxiv_id") or ""): str(paper.get("primary_annotator") or "")
        for paper in profile.get("papers") or []
        if isinstance(paper, dict)
    }
    missing = [arxiv_id for arxiv_id in paper_ids if arxiv_id not in by_id]
    if missing:
        raise ValueError("gold assignment is missing papers: " + ", ".join(missing))
    return {
        arxiv_id: validate_annotator_handle(by_id[arxiv_id])
        for arxiv_id in paper_ids
    }


def annotation_queue(
    profile: dict[str, Any],
    gold_manifest: dict[str, Any],
    gold_dir: Path,
    annotator: str,
) -> list[dict[str, str]]:
    """Classify one annotator's assigned papers without reading gold contents."""

    require_schema(profile, "benchmark.gold_assignment", require_current=True)
    require_schema(gold_manifest, "benchmark.gold_manifest", require_current=True)
    safe_annotator = validate_annotator_handle(annotator)
    files = {
        str(record.get("file") or "")
        for record in gold_manifest.get("files") or []
        if isinstance(record, dict)
    }
    queue: list[dict[str, str]] = []
    for paper in profile.get("papers") or []:
        if not isinstance(paper, dict):
            raise ValueError("gold assignment papers must contain objects")
        arxiv_id = str(paper.get("arxiv_id") or "")
        primary = validate_annotator_handle(
            str(paper.get("primary_annotator") or "")
        )
        additional_raw = paper.get("additional_annotators")
        if not isinstance(additional_raw, list):
            raise ValueError(f"additional_annotators must be a list: {arxiv_id}")
        additional = [
            validate_annotator_handle(value) for value in additional_raw
        ]
        if safe_annotator == primary:
            role = "primary"
        elif safe_annotator in additional:
            role = "additional"
        else:
            continue
        stem = f"{arxiv_id}/annotation_{safe_annotator}"
        yaml_exists = f"{stem}.yaml" in files
        json_exists = f"{stem}.json" in files
        if yaml_exists != json_exists:
            raise ValueError(
                f"partial final twin in gold manifest: {arxiv_id}/{safe_annotator}"
            )
        if yaml_exists:
            status = "completed"
        elif (gold_dir / arxiv_id / f"draft_{safe_annotator}.json").is_file():
            status = "resume"
        else:
            status = "new"
        queue.append({"arxiv_id": arxiv_id, "role": role, "status": status})
    return queue


def write_gold_assignment_once(path: Path, profile: dict[str, Any]) -> Path:
    require_schema(profile, "benchmark.gold_assignment", require_current=True)
    assignment_id = validate_path_segment(
        str(profile.get("assignment_id") or ""), "gold assignment id"
    )
    if path.name != f"{assignment_id}.json":
        raise ValueError("gold assignment filename must match assignment_id")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(profile, ensure_ascii=False, indent=2) + "\n")
    except FileExistsError as exc:
        raise ValueError(f"gold assignment already exists: {path}") from exc
    return path
