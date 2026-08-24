"""Run-root policy for local, non-formal contribution extraction runs.

Contribution runs never touch a benchmark campaign: they live under an
ignored, clearly non-formal workspace root, each run id is reserved
atomically and is never resumed or overwritten, and these runs are
pre-gold engineering artifacts — not benchmark results.
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path

CONTRIBUTION_RUNS_RELATIVE_DIR = Path("runs/hvs-contribution-extraction")
CONTRIBUTION_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def resolve_contribution_run_root(workspace: Path) -> Path:
    return (Path(workspace).resolve() / CONTRIBUTION_RUNS_RELATIVE_DIR).resolve()


def validate_contribution_run_id(run_id: str) -> str:
    """Return one safe path-segment run id or fail closed."""

    value = str(run_id or "")
    if not CONTRIBUTION_RUN_ID_RE.fullmatch(value) or value in {".", ".."}:
        raise ValueError(
            "contribution run_id must be one safe path segment containing only "
            "letters, digits, dot, underscore, or hyphen"
        )
    return value


def contribution_run_dir(workspace: Path, run_id: str) -> Path:
    """Resolve one run strictly beneath the fixed contribution run root."""

    root = resolve_contribution_run_root(workspace)
    safe_run_id = validate_contribution_run_id(run_id)
    run_dir = (root / safe_run_id).resolve()
    if run_dir.parent != root:
        raise ValueError("contribution run path escaped its fixed run root")
    return run_dir


def new_contribution_run_id() -> str:
    """A fresh, never-reused local run id."""

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    salt = hashlib.sha256(os.urandom(16)).hexdigest()[:8]
    return f"crun-{stamp}-{salt}"


def reserve_contribution_run_dir(workspace: Path, run_id: str) -> Path:
    """Atomically reserve one never-reusable contribution run id."""

    safe_run_id = validate_contribution_run_id(run_id)
    root = resolve_contribution_run_root(workspace)
    lock_dir = root / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    run_dir = contribution_run_dir(workspace, safe_run_id)
    lock_path = lock_dir / f"{safe_run_id}.lock"
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


def assert_contribution_run_dir(
    workspace: Path, run_id: str, run_dir: Path | None
) -> Path:
    """Require the exact fixed-root directory for this contribution run."""

    if run_dir is None:
        raise ValueError(
            "run_dir is required: the contribution pipeline never writes "
            "into a benchmark campaign"
        )
    expected = contribution_run_dir(workspace, run_id)
    actual = Path(run_dir).resolve()
    if actual != expected:
        raise ValueError(
            f"contribution run_dir must be {expected}; got {actual}"
        )
    return actual
