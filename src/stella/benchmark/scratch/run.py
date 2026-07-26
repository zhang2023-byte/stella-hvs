"""Immutable run identity, orchestration, progress, and cost ledger."""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TextIO

from stella.benchmark.paths import validate_path_segment
from stella.benchmark.run_contract import canonical_sha256
from stella.benchmark.scratch.bounded_call import Transport
from stella.benchmark.scratch.finalize import (
    PAPER_COMPLETE,
    PAPER_FAILED,
    PAPER_PARTIAL,
)
from stella.benchmark.scratch.method_config import ScratchMethodConfig
from stella.benchmark.scratch.paper_runner import _write_failed_result, run_paper
from stella.benchmark.scratch.prepare import RUNS_RELATIVE_DIR
from stella.benchmark.scratch.roster_stage import _atomic_write_json
from stella.schema_registry import require_schema, schema_ref

Progress = Callable[..., None]
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
RUN_SCOPES = frozenset({"full_dev", "targeted_dev", "test_smoke"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_scratch_run_id(run_id: str) -> str:
    run_id = validate_path_segment(run_id, "scratch run id")
    if RUN_ID_RE.fullmatch(run_id) is None:
        raise ValueError(
            "scratch run id must use 1-128 ASCII letters, digits, dot, "
            "underscore, or hyphen and must start with a letter or digit"
        )
    return run_id


class ProgressReporter:
    """Thread-safe, line-buffered terminal progress without model content."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream or sys.stdout
        self._lock = threading.Lock()
        self._cumulative_tokens = 0

    def __call__(self, event: str, **details: Any) -> None:
        with self._lock:
            if event == "api_attempt_end":
                tokens = details.get("tokens")
                if isinstance(tokens, (int, float)) and not isinstance(tokens, bool):
                    self._cumulative_tokens += int(tokens)
                details = {
                    **details,
                    "cumulative_tokens": self._cumulative_tokens,
                }
            safe: list[str] = []
            for key in sorted(details):
                value = details[key]
                if value is None:
                    continue
                if isinstance(value, float):
                    rendered = f"{value:.3f}"
                else:
                    rendered = str(value).replace("\n", " ")
                safe.append(f"{key}={rendered}")
            line = " | ".join([_utc_now(), event, *safe])
            print(line, file=self.stream, flush=True)


def _emit(progress: Progress | None, event: str, **details: Any) -> None:
    if progress is not None:
        progress(event, **details)


def _reserve_run_directory(workspace: Path, run_id: str) -> Path:
    """Atomically reserve one never-reusable run id."""

    run_root = workspace / RUNS_RELATIVE_DIR
    lock_dir = run_root.parent / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    run_dir = run_root / run_id
    lock_path = lock_dir / f"{run_id}.lock"
    if run_dir.exists():
        raise FileExistsError(f"scratch run already exists: {run_id}")
    try:
        descriptor = os.open(
            lock_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
    except FileExistsError as exc:
        raise FileExistsError(f"scratch run lock already exists: {run_id}") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(_utc_now() + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise FileExistsError(f"scratch run already exists: {run_id}") from exc
    return run_dir


def create_run_config(
    workspace: Path,
    run_id: str,
    arxiv_ids: list[str],
    *,
    config: ScratchMethodConfig,
    variant: str,
    scope: str = "targeted_dev",
    manifest_path: str = "fixture-manifest.json",
    manifest_sha256: str = "0" * 64,
    code: dict[str, Any] | None = None,
    roster_only: bool = False,
    paper_workers: int = 2,
    candidate_workers: int = 4,
) -> dict[str, Any]:
    """Freeze and atomically create a v2 run before any provider request."""

    run_id = validate_scratch_run_id(run_id)
    if scope not in RUN_SCOPES:
        raise ValueError(f"unknown scratch run scope: {scope!r}")
    if variant not in {"single", "ensemble"}:
        raise ValueError(f"unknown scratch variant: {variant!r}")
    if paper_workers < 1 or candidate_workers < 1:
        raise ValueError("worker counts must be positive")
    arxiv_ids = [
        validate_path_segment(str(arxiv_id), "paper id")
        for arxiv_id in arxiv_ids
    ]
    if not arxiv_ids or len(arxiv_ids) != len(set(arxiv_ids)):
        raise ValueError("scratch run papers must be non-empty and unique")
    if scope == "test_smoke" and len(arxiv_ids) != 1:
        raise ValueError("test_smoke requires exactly one paper")
    if not manifest_path or re.fullmatch(r"[0-9a-f]{64}", manifest_sha256) is None:
        raise ValueError("scratch run requires a manifest path and SHA-256")
    config.assert_frozen()
    execution = {
        "variant": variant,
        "roster_only": roster_only,
        "paper_workers": paper_workers,
        "candidate_workers": candidate_workers,
        "field_request_policy": {
            "scope": "per_candidate_field_stage",
            "max_physical_provider_requests": 3,
            "shared_across": [
                "initial",
                "transport_retry",
                "format_correction",
                "evidence_correction",
            ],
        },
    }
    code_state = code or {}
    stable = {
        "run_id": run_id,
        "scope": scope,
        "manifest": {"path": manifest_path, "sha256": manifest_sha256},
        "papers": list(arxiv_ids),
        "execution": execution,
        "method": config.model_dump(mode="json", by_alias=True),
        "method_fingerprint": config.method_fingerprint(),
        "code": code_state,
    }
    artifact = {
        "schema": schema_ref("benchmark.hvs_extraction_scratch.run_config"),
        "created_at": _utc_now(),
        **stable,
        "run_fingerprint": canonical_sha256(stable),
    }
    run_dir = _reserve_run_directory(workspace, run_id)
    _atomic_write_json(run_dir / "run_config.json", artifact)
    return artifact


def load_run_config(workspace: Path, run_id: str) -> dict[str, Any]:
    run_id = validate_scratch_run_id(run_id)
    path = workspace / RUNS_RELATIVE_DIR / run_id / "run_config.json"
    artifact = json.loads(path.read_text(encoding="utf-8"))
    require_schema(
        artifact,
        "benchmark.hvs_extraction_scratch.run_config",
        require_current=True,
    )
    return artifact


def _paper_result_path(workspace: Path, run_id: str, arxiv_id: str) -> Path:
    return (
        workspace
        / RUNS_RELATIVE_DIR
        / run_id
        / "papers"
        / arxiv_id
        / "paper_result.json"
    )


def _sum_tokens(usages: list[Any]) -> int:
    total = 0
    for usage in usages or []:
        if isinstance(usage, dict):
            value = usage.get("total_tokens")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
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
    *,
    wall_seconds: dict[str, float] | None = None,
    state: str = "completed",
    elapsed_seconds: float = 0.0,
) -> dict[str, Any]:
    """Build only from the immutable config paper list, never directories."""

    run_config = load_run_config(workspace, run_id)
    papers: dict[str, Any] = {}
    totals = {
        PAPER_COMPLETE: 0,
        PAPER_PARTIAL: 0,
        PAPER_FAILED: 0,
        "missing": 0,
    }
    total_calls = 0
    total_tokens = 0
    wall_seconds = wall_seconds or {}
    for arxiv_id in run_config["papers"]:
        path = _paper_result_path(workspace, run_id, arxiv_id)
        if not path.is_file():
            status = "missing"
            totals[status] += 1
            papers[arxiv_id] = {
                "status": status,
                "roster_status": None,
                "failure_code": "missing_paper_result",
                "candidates": {},
                "stage_calls": {
                    "roster_extractor": 0,
                    "adjudicator": 0,
                    "field": 0,
                },
                "total_tokens": 0,
                "wall_seconds": round(wall_seconds.get(arxiv_id, 0.0), 3),
            }
            continue
        result = json.loads(path.read_text(encoding="utf-8"))
        status = result["status"]
        if status not in (PAPER_COMPLETE, PAPER_PARTIAL, PAPER_FAILED):
            raise ValueError(f"unknown paper terminal status for {arxiv_id}: {status}")
        totals[status] += 1
        ledger = _paper_ledger(workspace, run_id, arxiv_id)
        calls = (
            ledger["roster_extractor_calls"]
            + ledger["adjudicator_calls"]
            + ledger["field_calls"]
        )
        total_calls += calls
        total_tokens += ledger["tokens"]
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
    expected = len(run_config["papers"])
    delivered = totals[PAPER_COMPLETE] + totals[PAPER_PARTIAL]
    totals.update(
        {
            "expected": expected,
            "delivered": delivered,
            "delivery_rate": round(delivered / expected, 6) if expected else 0.0,
            "api_calls": total_calls,
            "tokens": total_tokens,
            "elapsed_seconds": round(elapsed_seconds, 3),
        }
    )
    return {
        "schema": schema_ref("benchmark.hvs_extraction_scratch.run_summary"),
        "generated_at": _utc_now(),
        "run_id": run_id,
        "run_fingerprint": run_config["run_fingerprint"],
        "scope": run_config["scope"],
        "state": state,
        "papers": papers,
        "totals": totals,
    }


def _write_summary(workspace: Path, run_id: str, summary: dict[str, Any]) -> None:
    path = workspace / RUNS_RELATIVE_DIR / run_id / "run_summary.json"
    _atomic_write_json(path, summary)


def run_papers(
    workspace: Path,
    run_id: str,
    *,
    config: ScratchMethodConfig,
    transport: Transport,
    api_key: str = "",
    base_url: str = "",
    sleep=time.sleep,
    progress: Progress | None = None,
) -> dict[str, Any]:
    """Execute one fresh immutable run exactly once."""

    run_config = load_run_config(workspace, run_id)
    if run_config["method_fingerprint"] != config.method_fingerprint():
        raise ValueError("method fingerprint does not match immutable run config")
    execution = run_config["execution"]
    run_dir = workspace / RUNS_RELATIVE_DIR / run_id
    if (run_dir / "run_summary.json").exists():
        raise FileExistsError("scratch run already has a terminal summary")
    residual = [
        arxiv_id
        for arxiv_id in run_config["papers"]
        if _paper_result_path(workspace, run_id, arxiv_id).exists()
    ]
    if residual:
        raise FileExistsError(
            "scratch run contains paper results and cannot be resumed: "
            + ", ".join(residual)
        )
    started = time.monotonic()
    wall_seconds: dict[str, float] = {}
    _emit(
        progress,
        "run_start",
        run_id=run_id,
        scope=run_config["scope"],
        papers=len(run_config["papers"]),
    )

    def execute(arxiv_id: str) -> None:
        paper_started = time.monotonic()
        _emit(progress, "paper_start", run_id=run_id, arxiv_id=arxiv_id)
        try:
            result = run_paper(
                workspace,
                run_id,
                arxiv_id,
                config=config,
                variant=execution["variant"],
                transport=transport,
                api_key=api_key,
                base_url=base_url,
                sleep=sleep,
                candidate_workers=execution["candidate_workers"],
                roster_only=execution["roster_only"],
                progress=progress,
            )
        except Exception as exc:  # noqa: BLE001 - isolate harness defects per paper
            result = _write_failed_result(
                workspace,
                run_id,
                arxiv_id,
                variant=execution["variant"],
                code="harness_failure",
                detail=f"{type(exc).__name__}: {exc}",
            )
        duration = time.monotonic() - paper_started
        wall_seconds[arxiv_id] = duration
        ledger = _paper_ledger(workspace, run_id, arxiv_id)
        _emit(
            progress,
            "paper_end",
            run_id=run_id,
            arxiv_id=arxiv_id,
            status=result["status"],
            duration_seconds=duration,
            tokens=ledger["tokens"],
        )

    pool = ThreadPoolExecutor(max_workers=execution["paper_workers"])
    futures = [pool.submit(execute, paper) for paper in run_config["papers"]]
    try:
        for future in as_completed(futures):
            future.result()
    except KeyboardInterrupt:
        for future in futures:
            future.cancel()
        pool.shutdown(wait=False, cancel_futures=True)
        elapsed = time.monotonic() - started
        summary = build_run_summary(
            workspace,
            run_id,
            wall_seconds=wall_seconds,
            state="interrupted",
            elapsed_seconds=elapsed,
        )
        _write_summary(workspace, run_id, summary)
        _emit(progress, "run_interrupted", run_id=run_id, duration_seconds=elapsed)
        raise
    else:
        pool.shutdown(wait=True)
    elapsed = time.monotonic() - started
    summary = build_run_summary(
        workspace,
        run_id,
        wall_seconds=wall_seconds,
        state="completed",
        elapsed_seconds=elapsed,
    )
    _write_summary(workspace, run_id, summary)
    _emit(
        progress,
        "run_end",
        run_id=run_id,
        duration_seconds=elapsed,
        delivered=summary["totals"]["delivered"],
        failed=summary["totals"][PAPER_FAILED],
        missing=summary["totals"]["missing"],
        tokens=summary["totals"]["tokens"],
    )
    return summary
