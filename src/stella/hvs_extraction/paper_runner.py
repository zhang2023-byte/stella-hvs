"""Single-paper extraction pipeline chain: prepare -> roster -> field -> finalize.

Stage short-circuit rules: a failed preparation or roster
stage ends the paper as failed without model calls downstream; after roster
success the field stage and finalization always run, and a partial delivery
keeps the trusted roster and every validated candidate result.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stella.lit.extraction.bounded_call import Transport
from stella.hvs_extraction.core_document import build_core_document
from stella.hvs_extraction.field_stage import run_field_stage
from stella.hvs_extraction.finalize import (
    PAPER_FAILED,
    assemble_paper_result,
)
from stella.hvs_extraction.method_config import HvsExtractionMethodConfig
from stella.lit.extraction.prepare import (
    STATUS_PREPARED,
    build_prepared_input,
    resolve_run_dir,
    write_prepared_input,
)
from stella.hvs_extraction.roster_stage import (
    ROSTER_COMPLETE,
    _atomic_write_json,
    run_roster_stage,
)
from stella.schema_registry import schema_ref


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _emit(progress, event: str, **details: Any) -> None:
    if progress is not None:
        progress(event, **details)


def _write_failed_result(
    workspace: Path,
    run_id: str,
    arxiv_id: str,
    *,
    code: str,
    detail: str,
    run_dir: Path | None = None,
) -> dict[str, Any]:
    artifact = {
        "schema": schema_ref("hvs_extraction.paper_result"),
        "generated_at": _utc_now(),
        "paper": {"arxiv_id": arxiv_id},
        "run_id": run_id,
        "status": PAPER_FAILED,
        "roster_status": None,
        "failure": {"code": code, "detail": detail},
        "roster": None,
        "candidates": [],
    }
    paper_dir = (
        resolve_run_dir(workspace, run_id, run_dir=run_dir) / "papers" / arxiv_id
    )
    _atomic_write_json(paper_dir / "paper_result.json", artifact)
    return artifact


def _write_core_delivery(
    workspace: Path,
    run_id: str,
    arxiv_id: str,
    result: dict[str, Any],
    *,
    config: HvsExtractionMethodConfig,
    run_dir: Path | None = None,
) -> None:
    """Persist the deterministic v3 delivery beside the operational result."""

    document = build_core_document(
        result,
        campaign_id="hvs-extraction-v6",
        method_fingerprint=config.method_fingerprint(),
        component_hashes={
            **config.components.rule_profile_sha256,
            **config.components.prompt_template_sha256,
            **config.components.submission_schema_sha256,
        },
    )
    paper_dir = (
        resolve_run_dir(workspace, run_id, run_dir=run_dir) / "papers" / arxiv_id
    )
    _atomic_write_json(paper_dir / "literature_hvs_candidates.json", document)


def run_paper(
    workspace: Path,
    run_id: str,
    arxiv_id: str,
    *,
    config: HvsExtractionMethodConfig,
    transport: Transport,
    api_key: str = "",
    base_url: str = "",
    sleep=time.sleep,
    candidate_workers: int = 4,
    progress=None,
    run_dir: Path | None = None,
) -> dict[str, Any]:
    """Run the complete extraction pipeline for one paper."""

    _emit(progress, "stage_start", arxiv_id=arxiv_id, stage="prepare")
    prepared = build_prepared_input(
        workspace,
        arxiv_id,
        roster_budget=config.roster_context_budget,
        field_budget=config.field_context_budget,
    )
    write_prepared_input(workspace, run_id, prepared, run_dir=run_dir)
    _emit(
        progress,
        "stage_end",
        arxiv_id=arxiv_id,
        stage="prepare",
        status=prepared["status"],
    )
    if prepared["status"] != STATUS_PREPARED:
        failure = prepared.get("failure") or {}
        _emit(progress, "stage_start", arxiv_id=arxiv_id, stage="finalize")
        result = _write_failed_result(
            workspace,
            run_id,
            arxiv_id,
            code=prepared["status"],
            detail=failure.get("detail") or "input preparation failed",
            run_dir=run_dir,
        )
        _emit(
            progress,
            "stage_end",
            arxiv_id=arxiv_id,
            stage="finalize",
            status=result["status"],
        )
        _write_core_delivery(
            workspace, run_id, arxiv_id, result, config=config, run_dir=run_dir
        )
        return result

    _emit(progress, "stage_start", arxiv_id=arxiv_id, stage="roster")
    roster = run_roster_stage(
        workspace,
        run_id,
        arxiv_id,
        config=config,
        transport=transport,
        api_key=api_key,
        base_url=base_url,
        sleep=sleep,
        progress=progress,
        run_dir=run_dir,
    )
    _emit(
        progress,
        "stage_end",
        arxiv_id=arxiv_id,
        stage="roster",
        status=roster["status"],
    )
    if roster["status"] != ROSTER_COMPLETE:
        _emit(progress, "stage_start", arxiv_id=arxiv_id, stage="finalize")
        result = assemble_paper_result(
            workspace, run_id, arxiv_id, run_dir=run_dir
        )
        _emit(
            progress,
            "stage_end",
            arxiv_id=arxiv_id,
            stage="finalize",
            status=result["status"],
        )
        _write_core_delivery(
            workspace, run_id, arxiv_id, result, config=config, run_dir=run_dir
        )
        return result

    _emit(progress, "stage_start", arxiv_id=arxiv_id, stage="field")
    run_field_stage(
        workspace,
        run_id,
        arxiv_id,
        config=config,
        transport=transport,
        api_key=api_key,
        base_url=base_url,
        sleep=sleep,
        max_workers=candidate_workers,
        progress=progress,
        run_dir=run_dir,
    )
    _emit(progress, "stage_end", arxiv_id=arxiv_id, stage="field", status="complete")
    _emit(progress, "stage_start", arxiv_id=arxiv_id, stage="finalize")
    result = assemble_paper_result(
        workspace, run_id, arxiv_id, run_dir=run_dir
    )
    _emit(
        progress,
        "stage_end",
        arxiv_id=arxiv_id,
        stage="finalize",
        status=result["status"],
    )
    _write_core_delivery(
        workspace, run_id, arxiv_id, result, config=config, run_dir=run_dir
    )
    return result
