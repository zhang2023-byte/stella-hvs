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

    method = {
        "profile": (payload or {}).get("profile") or "dev10",
        "roster_model": "roster",
        "quantity_model": "quantity",
        "rule_profile": "hvs_contribution_v1",
    }
    body = json.dumps(method, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(body.encode("utf-8")).hexdigest()
    run_dir = _run_dir(root)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "method_config.json").write_text(
        json.dumps({"method": method, "method_fingerprint": fingerprint}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return {"status": "complete", "method_fingerprint": fingerprint}


def execute(payload: dict, *, root: Path, paper_id: str | None = None) -> dict:
    """benchmark.execute adapter: paper workers, never writing literature/."""

    authorities = (payload or {}).get("authorities") or {}
    missing = [
        kind for kind in ("llm", "network") if not authorities.get(kind)
    ]
    if missing:
        return {
            "status": "failed",
            "reason": "benchmark execution calls provider models through gateways",
            "missing_authority": missing,
        }
    if paper_id is None:
        return {"status": "failed", "reason": "execute is a per-paper operation"}
    return {
        "status": "failed",
        "reason": (
            "benchmark paper execution requires the frozen method and the "
            "authorized provider transcript in the worker environment"
        ),
    }


def resume(payload: dict, *, root: Path, paper_id: str | None = None) -> dict:
    """benchmark.resume adapter: only unfinished or network-failed papers."""

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
    return {
        "status": "complete",
        "eligible_papers": eligible,
        "detail": "resume appends attempts only for unfinished or network-failed papers",
    }


def finalize(payload: dict, *, root: Path, paper_id: str | None = None) -> dict:
    """benchmark.finalize adapter: one-way finalize to complete/partial."""

    run_dir = _run_dir(root)
    marker = run_dir / "finalized.json"
    if marker.is_file():
        return {
            "status": "failed",
            "reason": "the run is already finalized and immutable; no further attempts",
        }
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
    return {
        "status": "complete",
        "final_status": final_status,
        "detail": "finalize is one-way; successful papers cannot be re-attempted",
    }
