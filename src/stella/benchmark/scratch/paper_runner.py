"""Single-paper scratch pipeline chain: prepare -> roster -> field -> finalize.

Stage short-circuit rules (D001, D045, D047): a failed preparation or roster
stage ends the paper as failed without model calls downstream; after roster
success the field stage and finalization always run, and a partial delivery
keeps the trusted roster and every validated candidate result.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any

from stella.benchmark.scratch.bounded_call import Transport
from stella.benchmark.scratch.field_stage import run_field_stage
from stella.benchmark.scratch.finalize import (
    PAPER_FAILED,
    assemble_paper_result,
)
from stella.benchmark.scratch.method_config import ScratchMethodConfig
from stella.benchmark.scratch.prepare import (
    RUNS_RELATIVE_DIR,
    STATUS_PREPARED,
    build_prepared_input,
    write_prepared_input,
)
from stella.benchmark.scratch.roster_stage import (
    ROSTER_COMPLETE,
    _atomic_write_json,
    run_roster_stage,
)
from stella.schema_registry import schema_ref


def _utc_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _write_failed_result(
    workspace: Path,
    run_id: str,
    arxiv_id: str,
    *,
    variant: str,
    code: str,
    detail: str,
) -> dict[str, Any]:
    artifact = {
        "schema": schema_ref("benchmark.hvs_extraction_scratch.paper_result"),
        "generated_at": _utc_now(),
        "paper": {"arxiv_id": arxiv_id},
        "run_id": run_id,
        "variant": variant,
        "status": PAPER_FAILED,
        "roster_status": None,
        "failure": {"code": code, "detail": detail},
        "roster": None,
        "candidates": [],
    }
    paper_dir = workspace / RUNS_RELATIVE_DIR / run_id / "papers" / arxiv_id
    _atomic_write_json(paper_dir / "paper_result.json", artifact)
    return artifact


def run_paper(
    workspace: Path,
    run_id: str,
    arxiv_id: str,
    *,
    config: ScratchMethodConfig,
    variant: str,
    transport: Transport,
    api_key: str = "",
    base_url: str = "",
    sleep=time.sleep,
    candidate_workers: int = 4,
) -> dict[str, Any]:
    """Run the complete scratch pipeline for one paper."""

    prepared = build_prepared_input(
        workspace,
        arxiv_id,
        roster_budget=config.roster_context_budget,
        field_budget=config.field_context_budget,
    )
    write_prepared_input(workspace, run_id, prepared)
    if prepared["status"] != STATUS_PREPARED:
        failure = prepared.get("failure") or {}
        return _write_failed_result(
            workspace,
            run_id,
            arxiv_id,
            variant=variant,
            code=prepared["status"],
            detail=failure.get("detail") or "input preparation failed",
        )

    roster = run_roster_stage(
        workspace,
        run_id,
        arxiv_id,
        config=config,
        variant=variant,
        transport=transport,
        api_key=api_key,
        base_url=base_url,
        sleep=sleep,
    )
    if roster["status"] != ROSTER_COMPLETE:
        return assemble_paper_result(workspace, run_id, arxiv_id, variant=variant)

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
    )
    return assemble_paper_result(workspace, run_id, arxiv_id, variant=variant)
