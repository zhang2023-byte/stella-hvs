"""Run-level scratch orchestration: run identity, resume, and cost ledger.

A scratch run freezes its method config and git state before any paper runs
(D051 gate) and never writes into formal campaign paths. Papers that already
reached a terminal complete/partial state are skipped on resume; failed
papers rerun only on explicit request. The run summary records per-stage
calls, tokens, wall time, and failure classes separately for each variant so
the D047 ensemble-vs-single cost comparison has its data.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from stella.benchmark.run_contract import git_state
from stella.benchmark.scratch.bounded_call import Transport
from stella.benchmark.scratch.finalize import (
    PAPER_COMPLETE,
    PAPER_FAILED,
    PAPER_PARTIAL,
)
from stella.benchmark.scratch.method_config import ScratchMethodConfig
from stella.benchmark.scratch.paper_runner import run_paper
from stella.benchmark.scratch.prepare import RUNS_RELATIVE_DIR
from stella.benchmark.scratch.roster_stage import _atomic_write_json
from stella.schema_registry import schema_ref


def _utc_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def create_run_config(
    workspace: Path,
    run_id: str,
    arxiv_ids: list[str],
    *,
    config: ScratchMethodConfig,
    variant: str,
    code: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Freeze the scratch run identity before any model request."""

    config.assert_frozen()
    artifact = {
        "schema": schema_ref("benchmark.hvs_extraction_scratch.run_config"),
        "created_at": _utc_now(),
        "run_id": run_id,
        "variant": variant,
        "papers": sorted(arxiv_ids),
        "method": config.model_dump(mode="json", by_alias=True),
        "method_fingerprint": config.method_fingerprint(),
        "code": code if code is not None else git_state(workspace),
    }
    path = workspace / RUNS_RELATIVE_DIR / run_id / "run_config.json"
    _atomic_write_json(path, artifact)
    return artifact


def _paper_result_path(workspace: Path, run_id: str, arxiv_id: str) -> Path:
    return (
        workspace / RUNS_RELATIVE_DIR / run_id / "papers" / arxiv_id / "paper_result.json"
    )


def _sum_tokens(usages: list[Any]) -> int:
    total = 0
    for usage in usages or []:
        if isinstance(usage, dict):
            value = usage.get("total_tokens")
            if isinstance(value, (int, float)):
                total += int(value)
    return total


def _paper_ledger(workspace: Path, run_id: str, arxiv_id: str) -> dict[str, Any]:
    paper_dir = workspace / RUNS_RELATIVE_DIR / run_id / "papers" / arxiv_id
    ledger: dict[str, Any] = {
        "roster_extractor_calls": 0,
        "adjudicator_calls": 0,
        "field_calls": 0,
        "tokens": 0,
    }
    for proposal_path in sorted(paper_dir.glob("roster_proposal-slot-*.json")):
        proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
        ledger["roster_extractor_calls"] += len(proposal.get("attempts") or [])
        ledger["tokens"] += _sum_tokens(proposal.get("usages"))
    result_path = paper_dir / "paper_result.json"
    if result_path.is_file():
        result = json.loads(result_path.read_text(encoding="utf-8"))
        roster = result.get("roster") or {}
        provenance = roster.get("provenance") or {}
        ledger["adjudicator_calls"] += len(
            provenance.get("adjudicator_attempts") or []
        )
        ledger["tokens"] += _sum_tokens(provenance.get("adjudicator_usages"))
        for entry in result.get("candidates") or []:
            ledger["field_calls"] += len(entry.get("attempts") or [])
            ledger["tokens"] += _sum_tokens(entry.get("usages"))
    return ledger


def build_run_summary(
    workspace: Path,
    run_id: str,
    arxiv_ids: list[str],
    *,
    variant: str,
    wall_seconds: dict[str, float],
) -> dict[str, Any]:
    """Aggregate the run_summary artifact from persisted paper artifacts."""

    papers: dict[str, Any] = {}
    totals = {PAPER_COMPLETE: 0, PAPER_PARTIAL: 0, PAPER_FAILED: 0, "skipped": 0}
    for arxiv_id in arxiv_ids:
        path = _paper_result_path(workspace, run_id, arxiv_id)
        if not path.is_file():
            totals["skipped"] += 1
            continue
        result = json.loads(path.read_text(encoding="utf-8"))
        status = result["status"]
        totals[status] += 1
        ledger = _paper_ledger(workspace, run_id, arxiv_id)
        papers[arxiv_id] = {
            "status": status,
            "roster_status": result.get("roster_status"),
            "failure_code": (result.get("failure") or {}).get("code"),
            "candidates": {
                entry["record_id"]: entry["status"]
                for entry in result.get("candidates") or []
            },
            "stage_calls": {
                "roster_extractor": ledger["roster_extractor_calls"],
                "adjudicator": ledger["adjudicator_calls"],
                "field": ledger["field_calls"],
            },
            "total_tokens": ledger["tokens"],
            "wall_seconds": round(wall_seconds.get(arxiv_id, 0.0), 3),
        }
    return {
        "schema": schema_ref("benchmark.hvs_extraction_scratch.run_summary"),
        "generated_at": _utc_now(),
        "run_id": run_id,
        "variant": variant,
        "papers": papers,
        "totals": totals,
    }


def run_papers(
    workspace: Path,
    run_id: str,
    arxiv_ids: list[str],
    *,
    config: ScratchMethodConfig,
    variant: str,
    transport: Transport,
    api_key: str = "",
    base_url: str = "",
    sleep=time.sleep,
    rerun_failed: bool = False,
    paper_workers: int = 2,
    candidate_workers: int = 4,
) -> dict[str, Any]:
    """Run (or resume) the scratch pipeline for a list of papers."""

    todo: list[str] = []
    for arxiv_id in arxiv_ids:
        path = _paper_result_path(workspace, run_id, arxiv_id)
        if path.is_file():
            status = json.loads(path.read_text(encoding="utf-8"))["status"]
            if status in (PAPER_COMPLETE, PAPER_PARTIAL):
                continue
            if status == PAPER_FAILED and not rerun_failed:
                continue
        todo.append(arxiv_id)

    wall_seconds: dict[str, float] = {}

    def execute(arxiv_id: str) -> None:
        started = time.monotonic()
        run_paper(
            workspace,
            run_id,
            arxiv_id,
            config=config,
            variant=variant,
            transport=transport,
            api_key=api_key,
            base_url=base_url,
            sleep=sleep,
            candidate_workers=candidate_workers,
        )
        wall_seconds[arxiv_id] = time.monotonic() - started

    if todo:
        with ThreadPoolExecutor(max_workers=paper_workers) as pool:
            list(pool.map(execute, todo))

    summary = build_run_summary(
        workspace, run_id, arxiv_ids, variant=variant, wall_seconds=wall_seconds
    )
    path = workspace / RUNS_RELATIVE_DIR / run_id / "run_summary.json"
    _atomic_write_json(path, summary)
    return summary
