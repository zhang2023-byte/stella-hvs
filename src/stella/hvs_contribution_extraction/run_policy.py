"""Run-root policy for local, non-formal contribution extraction runs.

Contribution runs never touch a benchmark campaign: they live under an
ignored, clearly non-formal workspace root, each run id is reserved
atomically and is never resumed or overwritten, and these runs are
pre-gold engineering artifacts — not benchmark results.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

CONTRIBUTION_RUNS_RELATIVE_DIR = Path("runs/hvs-contribution-extraction")


def resolve_contribution_run_root(workspace: Path) -> Path:
    return workspace / CONTRIBUTION_RUNS_RELATIVE_DIR


def new_contribution_run_id() -> str:
    """A fresh, never-reused local run id."""

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    salt = hashlib.sha256(os.urandom(16)).hexdigest()[:8]
    return f"crun-{stamp}-{salt}"


def reserve_contribution_run_dir(
    workspace: Path, run_id: str, *, run_root: Path | None = None
) -> Path:
    """Atomically reserve one never-reusable contribution run id."""

    root = run_root or resolve_contribution_run_root(workspace)
    lock_dir = root / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    run_dir = root / run_id
    lock_path = lock_dir / f"{run_id}.lock"
    if run_dir.exists():
        raise FileExistsError(f"contribution run already exists: {run_id}")
    try:
        descriptor = os.open(
            lock_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
    except FileExistsError as exc:
        raise FileExistsError(
            f"contribution run lock already exists: {run_id}"
        ) from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(datetime.now(timezone.utc).isoformat(timespec="seconds") + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise FileExistsError(f"contribution run already exists: {run_id}") from exc
    return run_dir


def assert_run_dir_writable_once(run_dir: Path) -> Path:
    """Contribution stages require an explicit, dedicated run directory."""

    if run_dir is None:
        raise ValueError(
            "run_dir is required: the contribution pipeline never writes "
            "into a benchmark campaign"
        )
    return Path(run_dir)
