"""Benchmark run operation adapters on the unified workflow runtime.

The benchmark reuses the contribution extractor through ``lit.extraction``
but never writes into ``literature/``: paper execution happens inside the
run directory only. Resume selects unfinished or network-failed papers of an
active run; finalize is one-way and yields complete/partial.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

RESUMABLE_STATUSES = ("pending", "running", "network_failed")


def _run_dir(root: Path, payload: dict | None = None) -> Path:
    run_id = ((payload or {}).get("run_id")) or os.environ.get(
        "STELLA_WORKER_RUN_ID", "brun"
    )
    return Path(root) / "runs" / "benchmark" / run_id


def freeze_method(
    payload: dict, *, root: Path, paper_id: str | None = None
) -> dict[str, Any]:
    """benchmark.freeze_method adapter: freeze the method fingerprint."""

    from stella.workflows import operation_complete

    method = {
        "profile": (payload or {}).get("profile") or "dev10",
        "roster_model": "roster",
        "quantity_model": "quantity",
        "rule_profile": "hvs_contribution_v1",
    }
    body = json.dumps(method, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(body.encode("utf-8")).hexdigest()
    run_dir = _run_dir(root, payload)
    run_dir.mkdir(parents=True, exist_ok=True)
    method_path = run_dir / "method_config.json"
    method_path.write_text(
        json.dumps({"method": method, "method_fingerprint": fingerprint}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return operation_complete(
        artifacts=[str(method_path)], method_fingerprint=fingerprint
    )


def validate_method_freeze(payload: dict, result: dict, *, root: Path) -> list[str]:
    """A completed freeze must leave a fingerprinted method config on disk."""

    if result.get("status") != "complete":
        return []
    method_path = _run_dir(root, payload) / "method_config.json"
    if not method_path.is_file():
        return [f"method freeze reported complete but {method_path} is missing"]
    try:
        frozen = json.loads(method_path.read_text(encoding="utf-8"))
    except ValueError as error:
        return [f"frozen method config is not parseable: {error}"]
    if not frozen.get("method_fingerprint"):
        return ["frozen method config carries no fingerprint"]
    reported = (result.get("detail") or {}).get("method_fingerprint")
    if reported and reported != frozen.get("method_fingerprint"):
        return ["freeze result fingerprint disagrees with the frozen config"]
    return []


def execute(payload: dict, *, root: Path, paper_id: str | None = None) -> dict:
    """benchmark.execute adapter: paper workers, never writing literature/."""

    from stella.workflows import operation_failed

    authorities = (payload or {}).get("authorities") or {}
    missing = [
        kind for kind in ("llm", "network") if not authorities.get(kind)
    ]
    if missing:
        return operation_failed(
            "benchmark execution calls provider models through gateways",
            kind="authority",
            blockers=missing,
        )
    if paper_id is None:
        return operation_failed(
            "execute is a per-paper operation", kind="precondition"
        )
    return operation_failed(
        "benchmark paper execution requires the frozen method and the "
        "authorized provider transport in the worker environment",
        kind="precondition",
        next_action="freeze the method and provide the provider transport",
    )


def validate_run_output(payload: dict, result: dict, *, root: Path) -> list[str]:
    """A completed paper execution must record its attempt in the run."""

    if result.get("status") not in ("complete", "partial"):
        return []
    paper_id = result.get("paper_id")
    if not paper_id:
        return ["execution result does not identify its paper"]
    status_path = _run_dir(root, payload) / "papers" / paper_id / "status.json"
    if not status_path.is_file():
        return [
            f"execution reported success but {status_path} is missing"
        ]
    return []


def resume(payload: dict, *, root: Path, paper_id: str | None = None) -> dict:
    """benchmark.resume adapter: only unfinished or network-failed papers."""

    from stella.workflows import operation_complete

    run_dir = _run_dir(root, payload)
    eligible: list[str] = []
    for paper in (payload or {}).get("papers") or []:
        status_path = run_dir / "papers" / paper / "status.json"
        if not status_path.is_file():
            eligible.append(paper)
            continue
        status = json.loads(status_path.read_text(encoding="utf-8")).get("status")
        if status in RESUMABLE_STATUSES:
            eligible.append(paper)
    return operation_complete(
        eligible_papers=eligible,
        note="resume appends attempts only for unfinished or network-failed papers",
    )


def validate_resume_eligibility(
    payload: dict, result: dict, *, root: Path
) -> list[str]:
    """A completed resume decision must list only resumable papers."""

    if result.get("status") != "complete":
        return []
    run_dir = _run_dir(root, payload)
    eligible = (result.get("detail") or {}).get("eligible_papers") or []
    errors: list[str] = []
    for paper in eligible:
        status_path = run_dir / "papers" / paper / "status.json"
        if not status_path.is_file():
            continue
        status = json.loads(status_path.read_text(encoding="utf-8")).get("status")
        if status not in RESUMABLE_STATUSES:
            errors.append(
                f"resume listed {paper} with terminal status {status!r}"
            )
    return errors


def finalize(payload: dict, *, root: Path, paper_id: str | None = None) -> dict:
    """benchmark.finalize adapter: one-way finalize to complete/partial."""

    from stella.workflows import operation_complete, operation_failed

    run_dir = _run_dir(root, payload)
    marker = run_dir / "finalized.json"
    if marker.is_file():
        return operation_failed(
            "the run is already finalized and immutable; no further attempts",
            kind="precondition",
        )
    statuses: list[str] = []
    for paper in (payload or {}).get("papers") or []:
        status_path = run_dir / "papers" / paper / "status.json"
        status = (
            json.loads(status_path.read_text(encoding="utf-8")).get("status")
            if status_path.is_file()
            else "pending"
        )
        statuses.append(status)
    if statuses and all(status == "complete" for status in statuses):
        final_status = "complete"
    else:
        final_status = "partial"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps({"final_status": final_status}, indent=2) + "\n",
        encoding="utf-8",
    )
    return operation_complete(
        artifacts=[str(marker)],
        final_status=final_status,
        note="finalize is one-way; successful papers cannot be re-attempted",
    )


def validate_finalize(payload: dict, result: dict, *, root: Path) -> list[str]:
    """A completed finalize must leave its one-way marker on disk."""

    if result.get("status") != "complete":
        return []
    marker = _run_dir(root, payload) / "finalized.json"
    if not marker.is_file():
        return [f"finalize reported complete but {marker} is missing"]
    final_status = (result.get("detail") or {}).get("final_status")
    if final_status not in ("complete", "partial"):
        return [f"finalize reported an invalid terminal status: {final_status!r}"]
    return []
