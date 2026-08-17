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

from stella.benchmark.campaign import sha256_file
from stella.benchmark.paths import validate_path_segment
from stella.benchmark.run_contract import canonical_sha256
from stella.hvs_extraction.bounded_call import Transport
from stella.hvs_extraction.finalize import (
    PAPER_COMPLETE,
    PAPER_FAILED,
    PAPER_PARTIAL,
)
from stella.hvs_extraction.method_config import HvsExtractionMethodConfig
from stella.hvs_extraction.paper_runner import _write_failed_result, run_paper
from stella.hvs_extraction.prepare import RUNS_RELATIVE_DIR
from stella.hvs_extraction.roster_stage import _atomic_write_json
from stella.schema_registry import (
    ACTIVE_BENCHMARK_CAMPAIGN,
    ACTIVE_BENCHMARK_PRICING_SNAPSHOT,
    require_schema,
    schema_ref,
)

Progress = Callable[..., None]
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
RUN_SCOPES = frozenset({"full_dev", "targeted_dev", "test_smoke"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_hvs_extraction_run_id(run_id: str) -> str:
    run_id = validate_path_segment(run_id, "extraction run id")
    if RUN_ID_RE.fullmatch(run_id) is None:
        raise ValueError(
            "extraction run id must use 1-128 ASCII letters, digits, dot, "
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


def _component_hashes(
    workspace: Path, config: HvsExtractionMethodConfig
) -> dict[str, str]:
    """Hash every executable or declarative component used by the active campaign."""

    from stella.benchmark.scoring import UNIT_SYNONYMS, UNIT_SYNONYMS_VERSION

    recorded = config.components

    def digest(relative: str) -> str:
        path = workspace / relative
        if path.is_file():
            return sha256_file(path)
        # Small isolated fixture workspaces do not copy the installed package.
        # The marker is deterministic and cannot be mistaken for a file hash
        # verified against a real checkout.
        return canonical_sha256({"fixture_component_unavailable": relative})

    hashes = {
        "runner": digest("src/stella/hvs_extraction/run.py"),
        "core_builder": digest("src/stella/hvs_extraction/core_document.py"),
        "validator": digest("scripts/validate_hvs_candidates.py"),
        "scorer": digest("src/stella/benchmark/scoring.py"),
        "identity_matching": digest("src/stella/benchmark/identity.py"),
        "unit_table": canonical_sha256(
            {
                "version": UNIT_SYNONYMS_VERSION,
                "synonyms": UNIT_SYNONYMS,
            }
        ),
    }
    for family, values in (
        ("rules", recorded.rule_profile_sha256),
        ("prompts", recorded.prompt_template_sha256),
        ("schemas", recorded.submission_schema_sha256),
    ):
        for name, digest in values.items():
            hashes[f"{family}.{name}"] = digest
    return hashes


def reserve_run_directory(workspace: Path, run_id: str) -> Path:
    """Atomically reserve one never-reusable run id."""

    run_root = workspace / RUNS_RELATIVE_DIR
    lock_dir = run_root.parent / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    run_dir = run_root / run_id
    lock_path = lock_dir / f"{run_id}.lock"
    if run_dir.exists():
        raise FileExistsError(f"extraction run already exists: {run_id}")
    try:
        descriptor = os.open(
            lock_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
    except FileExistsError as exc:
        raise FileExistsError(f"extraction run lock already exists: {run_id}") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(_utc_now() + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise FileExistsError(f"extraction run already exists: {run_id}") from exc
    return run_dir


def create_run_config(
    workspace: Path,
    run_id: str,
    arxiv_ids: list[str],
    *,
    config: HvsExtractionMethodConfig,
    scope: str = "targeted_dev",
    manifest_path: str = "fixture-manifest.json",
    manifest_sha256: str = "0" * 64,
    code: dict[str, Any] | None = None,
    paper_workers: int = 2,
    candidate_workers: int = 4,
) -> dict[str, Any]:
    """Freeze and atomically create a formal run before any provider request."""

    run_id = validate_hvs_extraction_run_id(run_id)
    if scope not in RUN_SCOPES:
        raise ValueError(f"unknown extraction run scope: {scope!r}")
    if paper_workers < 1 or candidate_workers < 1:
        raise ValueError("worker counts must be positive")
    arxiv_ids = [
        validate_path_segment(str(arxiv_id), "paper id")
        for arxiv_id in arxiv_ids
    ]
    if not arxiv_ids or len(arxiv_ids) != len(set(arxiv_ids)):
        raise ValueError("extraction run papers must be non-empty and unique")
    if scope == "test_smoke" and len(arxiv_ids) != 1:
        raise ValueError("test_smoke requires exactly one paper")
    if not manifest_path or re.fullmatch(r"[0-9a-f]{64}", manifest_sha256) is None:
        raise ValueError("extraction run requires a manifest path and SHA-256")
    config.assert_frozen()
    execution = {
        "paper_workers": paper_workers,
        "candidate_workers": candidate_workers,
        "field_request_policy": config.field_request_policy.model_dump(
            mode="json", by_alias=True
        ),
    }
    code_state = code or {}
    stable = {
        "run_id": run_id,
        "campaign": {
            "campaign_id": ACTIVE_BENCHMARK_CAMPAIGN,
            "manifest_path": manifest_path,
            "manifest_sha256": manifest_sha256,
        },
        "scope": scope,
        "manifest": {"path": manifest_path, "sha256": manifest_sha256},
        "papers": list(arxiv_ids),
        "execution": execution,
        "method": config.model_dump(mode="json", by_alias=True),
        "models": {
            "roster": config.roster_model.model,
            "core_fields": config.core_field_model.model,
        },
        "component_hashes": _component_hashes(workspace, config),
        "method_fingerprint": config.method_fingerprint(),
        "code": {
            "revision": code_state.get("revision"),
            "worktree": code_state,
        },
    }
    artifact = {
        "schema": schema_ref("benchmark.run_config"),
        "created_at": _utc_now(),
        **stable,
        "run_fingerprint": canonical_sha256(stable),
    }
    run_dir = reserve_run_directory(workspace, run_id)
    _atomic_write_json(run_dir / "run_config.json", artifact)
    return artifact


def load_run_config(workspace: Path, run_id: str) -> dict[str, Any]:
    run_id = validate_hvs_extraction_run_id(run_id)
    path = workspace / RUNS_RELATIVE_DIR / run_id / "run_config.json"
    artifact = json.loads(path.read_text(encoding="utf-8"))
    require_schema(
        artifact,
        "benchmark.run_config",
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


USAGE_NUMERIC_FIELDS = (
    "prompt_tokens",
    "cached_input_tokens",
    "uncached_input_tokens",
    "completion_tokens",
    "reasoning_tokens",
    "total_tokens",
)
FORMAT_OUTCOMES = (
    "valid_first_pass",
    "valid_after_correction",
    "invalid",
    "not_observed",
)


def _integer_token(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0:
        return None
    return int(value)


def _normalize_usage(usage: dict[str, Any]) -> tuple[dict[str, int], list[str]]:
    warnings: list[str] = []
    prompt = _integer_token(usage.get("prompt_tokens"))
    completion = _integer_token(usage.get("completion_tokens"))
    total = _integer_token(usage.get("total_tokens"))
    flat_cached = _integer_token(usage.get("prompt_cache_hit_tokens"))
    prompt_details = usage.get("prompt_tokens_details") or {}
    nested_cached = (
        _integer_token(prompt_details.get("cached_tokens"))
        if isinstance(prompt_details, dict)
        else None
    )
    if (
        flat_cached is not None
        and nested_cached is not None
        and flat_cached != nested_cached
    ):
        warnings.append("cache_token_conflict")
    cached = flat_cached if flat_cached is not None else nested_cached
    if cached is None:
        cached = 0
        warnings.append("cache_tokens_missing")
    if prompt is None:
        prompt = 0
        warnings.append("prompt_tokens_missing")
    if cached > prompt:
        cached = prompt
        warnings.append("cached_tokens_exceed_prompt")
    if completion is None:
        completion = 0
        warnings.append("completion_tokens_missing")
    if total is None:
        total = prompt + completion
        warnings.append("total_tokens_missing")
    details = usage.get("completion_tokens_details") or {}
    reasoning = (
        _integer_token(details.get("reasoning_tokens"))
        if isinstance(details, dict)
        else None
    )
    reasoning = reasoning or 0
    if reasoning > completion:
        reasoning = completion
        warnings.append("reasoning_tokens_exceed_completion")
    miss = _integer_token(usage.get("prompt_cache_miss_tokens"))
    if miss is not None and miss != prompt - cached:
        warnings.append("cache_miss_token_conflict")
    return (
        {
            "prompt_tokens": prompt,
            "cached_input_tokens": cached,
            "uncached_input_tokens": prompt - cached,
            "completion_tokens": completion,
            "reasoning_tokens": reasoning,
            "total_tokens": total,
        },
        warnings,
    )


def _aggregate_usage(units: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {key: 0 for key in USAGE_NUMERIC_FIELDS}
    api_calls = 0
    responses_received = 0
    usages: list[dict[str, Any]] = []
    warnings: set[str] = set()
    for unit in units:
        attempts = unit.get("attempts") or []
        api_calls += len(attempts)
        responses_received += sum(
            1
            for attempt in attempts
            if isinstance(attempt, dict)
            and attempt.get("outcome") == "response_received"
        )
        usages.extend(
            usage
            for usage in unit.get("usages") or []
            if isinstance(usage, dict)
        )
    for usage in usages:
        normalized, usage_warnings = _normalize_usage(usage)
        for key in USAGE_NUMERIC_FIELDS:
            totals[key] += normalized[key]
        warnings.update(usage_warnings)
    if api_calls == 0:
        telemetry_status = "not_applicable"
    elif not usages:
        telemetry_status = "unavailable"
        warnings.add("usage_missing")
    elif warnings or len(usages) != responses_received:
        telemetry_status = "partial"
        if len(usages) != responses_received:
            warnings.add("usage_response_count_mismatch")
    else:
        telemetry_status = "complete"
    return {
        **totals,
        "api_calls": api_calls,
        "telemetry_status": telemetry_status,
        "warnings": sorted(warnings),
    }


def _format_outcome(unit: dict[str, Any], *, accepted_status: str) -> str:
    repairs = [
        repair
        for repair in unit.get("repair_history") or []
        if isinstance(repair, dict) and repair.get("type") == "format_correction"
    ]
    if repairs:
        return (
            "valid_after_correction"
            if repairs[-1].get("final_result") == "accepted"
            else "invalid"
        )
    attempts = [
        attempt
        for attempt in unit.get("attempts") or []
        if isinstance(attempt, dict)
    ]
    if unit.get("status") == accepted_status:
        return "valid_first_pass"
    if any(
        isinstance(repair, dict) and repair.get("type") == "evidence_correction"
        for repair in unit.get("repair_history") or []
    ):
        return "valid_first_pass"
    if any(attempt.get("outcome") == "response_received" for attempt in attempts):
        return "invalid"
    return "not_observed"


def _format_validation(units: list[tuple[dict[str, Any], str]]) -> dict[str, Any]:
    counts = {key: 0 for key in FORMAT_OUTCOMES}
    for unit, accepted_status in units:
        counts[_format_outcome(unit, accepted_status=accepted_status)] += 1
    observed = sum(counts[key] for key in FORMAT_OUTCOMES[:-1])
    return {
        "observed_units": observed,
        **counts,
        "first_pass_rate": (
            round(counts["valid_first_pass"] / observed, 6) if observed else 0.0
        ),
        "final_valid_rate": (
            round(
                (counts["valid_first_pass"] + counts["valid_after_correction"])
                / observed,
                6,
            )
            if observed
            else 0.0
        ),
    }


def _paper_ledger(workspace: Path, run_id: str, arxiv_id: str) -> dict[str, Any]:
    paper_dir = workspace / RUNS_RELATIVE_DIR / run_id / "papers" / arxiv_id
    ledger: dict[str, Any] = {
        "roster_calls": 0,
        "core_field_calls": 0,
        "tokens": 0,
        "roster_units": [],
        "core_field_units": [],
        "format_units": [],
    }
    for proposal_path in sorted(paper_dir.glob("roster_proposal-slot-*.json")):
        proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
        ledger["roster_calls"] += len(proposal.get("attempts") or [])
        ledger["roster_units"].append(proposal)
        ledger["format_units"].append((proposal, "valid"))
    result_path = paper_dir / "paper_result.json"
    if result_path.is_file():
        result = json.loads(result_path.read_text(encoding="utf-8"))
        for entry in result.get("candidates") or []:
            ledger["core_field_calls"] += len(entry.get("attempts") or [])
            ledger["core_field_units"].append(entry)
            ledger["format_units"].append((entry, "fields_complete"))
    roster_usage = _aggregate_usage(ledger["roster_units"])
    core_usage = _aggregate_usage(ledger["core_field_units"])
    ledger["usage"] = {"roster": roster_usage, "core_fields": core_usage}
    ledger["format_validation"] = _format_validation(ledger["format_units"])
    ledger["tokens"] = roster_usage["total_tokens"] + core_usage["total_tokens"]
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
    role_units: dict[str, list[dict[str, Any]]] = {
        "roster": [],
        "core_fields": [],
    }
    format_units: list[tuple[dict[str, Any], str]] = []
    total_calls = 0
    wall_seconds = wall_seconds or {}
    for arxiv_id in run_config["papers"]:
        path = _paper_result_path(workspace, run_id, arxiv_id)
        if not path.is_file():
            status = "missing"
            totals[status] += 1
            format_units.append(({"status": "missing", "attempts": []}, "valid"))
            papers[arxiv_id] = {
                "status": status,
                "roster_status": None,
                "failure_code": "missing_paper_result",
                "candidates": {},
                "stage_calls": {
                    "roster": 0,
                    "core_fields": 0,
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
            ledger["roster_calls"] + ledger["core_field_calls"]
        )
        total_calls += calls
        role_units["roster"].extend(ledger["roster_units"])
        role_units["core_fields"].extend(ledger["core_field_units"])
        format_units.extend(ledger["format_units"])
        papers[arxiv_id] = {
            "status": status,
            "roster_status": result.get("roster_status"),
            "failure_code": (result.get("failure") or {}).get("code"),
            "candidates": {
                entry["record_id"]: entry["status"]
                for entry in result.get("candidates") or []
            },
            "stage_calls": {
                "roster": ledger["roster_calls"],
                "core_fields": ledger["core_field_calls"],
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
            "tokens": sum(
                _aggregate_usage(units)["total_tokens"]
                for units in role_units.values()
            ),
            "elapsed_seconds": round(elapsed_seconds, 3),
        }
    )
    by_role = {
        role: _aggregate_usage(units) for role, units in role_units.items()
    }
    total_usage = {key: 0 for key in USAGE_NUMERIC_FIELDS}
    for usage in by_role.values():
        for key in USAGE_NUMERIC_FIELDS:
            total_usage[key] += usage[key]
    total_usage["api_calls"] = sum(usage["api_calls"] for usage in by_role.values())
    statuses = {usage["telemetry_status"] for usage in by_role.values()}
    if statuses <= {"not_applicable"}:
        total_status = "not_applicable"
    elif "unavailable" in statuses and not any(
        usage["total_tokens"] for usage in by_role.values()
    ):
        total_status = "unavailable"
    elif statuses <= {"complete", "not_applicable"}:
        total_status = "complete"
    else:
        total_status = "partial"
    total_usage["telemetry_status"] = total_status
    total_usage["warnings"] = sorted(
        {
            warning
            for usage in by_role.values()
            for warning in usage["warnings"]
        }
    )
    return {
        "schema": schema_ref("benchmark.run_summary"),
        "generated_at": _utc_now(),
        "run_id": run_id,
        "run_fingerprint": run_config["run_fingerprint"],
        "scope": run_config["scope"],
        "state": state,
        "papers": papers,
        "totals": totals,
        "format_validation": _format_validation(format_units),
        "usage": {"by_role": by_role, "total": total_usage},
    }


def _write_summary(workspace: Path, run_id: str, summary: dict[str, Any]) -> None:
    path = workspace / RUNS_RELATIVE_DIR / run_id / "run_summary.json"
    _atomic_write_json(path, summary)


def build_run_manifest(
    workspace: Path, run_id: str, summary: dict[str, Any]
) -> dict[str, Any]:
    """Build the V6 L0/L1/L2 delivery contract from frozen config order."""

    config = load_run_config(workspace, run_id)
    run_dir = workspace / RUNS_RELATIVE_DIR / run_id
    l1 = {"complete": [], "failed": [], "missing": []}
    l2 = {"complete": [], "partial": [], "failed": [], "missing": []}
    artifacts: dict[str, dict[str, dict[str, Any]]] = {}
    candidate_counts = {
        "total": 0,
        "fields_complete": 0,
        "field_extraction_failed": 0,
    }
    for arxiv_id in config["papers"]:
        result_path = _paper_result_path(workspace, run_id, arxiv_id)
        core_path = result_path.with_name("literature_hvs_candidates.json")
        if not result_path.is_file():
            l1["missing"].append(arxiv_id)
            l2["missing"].append(arxiv_id)
            continue
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("roster_status") in {"candidates_found", "no_candidates"}:
            l1["complete"].append(arxiv_id)
        else:
            l1["failed"].append(arxiv_id)
        status = str(result.get("status") or "failed")
        if status not in l2:
            status = "failed"
        if not core_path.is_file():
            status = "failed"
        l2[status].append(arxiv_id)
        for candidate in result.get("candidates") or []:
            candidate_counts["total"] += 1
            candidate_status = candidate.get("status")
            if candidate_status in candidate_counts:
                candidate_counts[candidate_status] += 1
        paper_artifacts: dict[str, dict[str, Any]] = {}
        for artifact_path in (result_path, core_path):
            if artifact_path.is_file():
                paper_artifacts[artifact_path.name] = {
                    "sha256": sha256_file(artifact_path),
                    "bytes": artifact_path.stat().st_size,
                }
        artifacts[arxiv_id] = paper_artifacts

    if len(l2["complete"]) == len(config["papers"]):
        status = "complete"
    elif l1["complete"]:
        status = "partial"
    else:
        status = "failed"
    manifest = {
        "schema": schema_ref("benchmark.run_manifest"),
        "run_id": run_id,
        "campaign": config["campaign"],
        "scope": config["scope"],
        "papers": list(config["papers"]),
        "method_fingerprint": config["method_fingerprint"],
        "component_hashes": config["component_hashes"],
        "run_fingerprint": config["run_fingerprint"],
        "run_config_sha256": sha256_file(run_dir / "run_config.json"),
        "run_summary_sha256": sha256_file(run_dir / "run_summary.json"),
        "sealed_at": _utc_now(),
        "status": status,
        "l1_roster_delivery": l1,
        "l2_core_field_delivery": {
            **l2,
            "candidate_counts": candidate_counts,
        },
        "l0": {"format_validation": summary["format_validation"]},
        "usage": summary["usage"],
        "artifacts": artifacts,
    }
    from stella.benchmark.run_contract import require_v6_run_manifest

    require_v6_run_manifest(manifest)
    _atomic_write_json(run_dir / "run_manifest.json", manifest)
    return manifest


def run_papers(
    workspace: Path,
    run_id: str,
    *,
    config: HvsExtractionMethodConfig,
    transport: Transport,
    api_key: str = "",
    base_url: str = "",
    sleep=time.sleep,
    progress: Progress | None = None,
    pricing_snapshot_path: Path | None = None,
) -> dict[str, Any]:
    """Execute one fresh immutable run exactly once."""

    if pricing_snapshot_path is None:
        default_pricing_path = (
            workspace
            / "benchmark"
            / "pricing"
            / "tokendance"
            / f"{ACTIVE_BENCHMARK_PRICING_SNAPSHOT}.json"
        )
        if default_pricing_path.is_file():
            pricing_snapshot_path = default_pricing_path
    run_config = load_run_config(workspace, run_id)
    if run_config["method_fingerprint"] != config.method_fingerprint():
        raise ValueError("method fingerprint does not match immutable run config")
    execution = run_config["execution"]
    run_dir = workspace / RUNS_RELATIVE_DIR / run_id
    if (run_dir / "run_summary.json").exists():
        raise FileExistsError("extraction run already has a terminal summary")
    residual = [
        arxiv_id
        for arxiv_id in run_config["papers"]
        if _paper_result_path(workspace, run_id, arxiv_id).exists()
    ]
    if residual:
        raise FileExistsError(
            "extraction run contains paper results and cannot be resumed: "
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
                transport=transport,
                api_key=api_key,
                base_url=base_url,
                sleep=sleep,
                candidate_workers=execution["candidate_workers"],
                progress=progress,
            )
        except Exception as exc:  # noqa: BLE001 - isolate harness defects per paper
            result = _write_failed_result(
                workspace,
                run_id,
                arxiv_id,
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
        if pricing_snapshot_path is not None:
            from stella.benchmark.run_cost import write_run_cost_once

            write_run_cost_once(run_dir, pricing_snapshot_path)
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
    build_run_manifest(workspace, run_id, summary)
    if pricing_snapshot_path is not None:
        from stella.benchmark.run_cost import write_run_cost_once

        write_run_cost_once(run_dir, pricing_snapshot_path)
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
