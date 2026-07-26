"""Dev/test selection and read-only preflight for immutable extraction runs."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from stella.benchmark.campaign import papers_for_split, sha256_file
from stella.benchmark.paths import campaign_paths
from stella.hvs_extraction.method_config import HvsExtractionMethodConfig
from stella.hvs_extraction.prepare import (
    RUNS_RELATIVE_DIR,
    STATUS_PREPARED,
    build_prepared_input,
)
from stella.hvs_extraction.run import validate_hvs_extraction_run_id
from stella.schema_registry import ACTIVE_BENCHMARK_CAMPAIGN, require_schema

EXECUTION_ROOTS = frozenset({"src", "scripts", "skills", "workflows"})


def inspect_scratch_worktree(workspace: Path) -> dict[str, Any]:
    """Block tracked drift and untracked execution files; warn on other files."""

    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tracked_output = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=no"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    tracked_changes = [
        line[3:] for line in tracked_output.splitlines() if line.strip()
    ]
    untracked_output = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    blocking_untracked: list[str] = []
    warnings: list[str] = []
    for raw in untracked_output.splitlines():
        path = raw.strip()
        if not path:
            continue
        first = Path(path).parts[0] if Path(path).parts else ""
        if first in EXECUTION_ROOTS:
            blocking_untracked.append(path)
        else:
            warnings.append(f"non-blocking untracked file: {path}")
    return {
        "revision": revision,
        "tracked_changes": tracked_changes,
        "blocking_untracked": blocking_untracked,
        "warnings": warnings,
        "clean_for_dev": not tracked_changes and not blocking_untracked,
    }


def load_active_manifest(workspace: Path) -> tuple[Path, dict[str, Any], str]:
    path = campaign_paths(
        workspace, ACTIVE_BENCHMARK_CAMPAIGN
    ).campaign_manifest
    manifest = json.loads(path.read_text(encoding="utf-8"))
    require_schema(manifest, "benchmark.campaign", require_current=True)
    return path, manifest, sha256_file(path)


def select_run_papers(
    manifest: dict[str, Any],
    *,
    full_dev: bool,
    requested_ids: list[str] | None,
    allow_test_smoke: bool,
) -> tuple[str, list[str]]:
    """Resolve scope and preserve the manifest's paper order."""

    dev = papers_for_split(manifest, "dev")
    test = papers_for_split(manifest, "test")
    if full_dev:
        if requested_ids:
            raise ValueError("--dev cannot be combined with --arxiv-id")
        if allow_test_smoke:
            raise ValueError("--allow-test-smoke requires one test --arxiv-id")
        return "full_dev", dev
    requested = list(requested_ids or [])
    if not requested:
        raise ValueError("choose --dev or at least one --arxiv-id")
    if len(requested) != len(set(requested)):
        raise ValueError("duplicate --arxiv-id values are not allowed")
    requested_set = set(requested)
    test_requested = requested_set & set(test)
    unknown = requested_set - set(dev) - set(test)
    if unknown:
        raise ValueError(
            "papers are not in the active manifest: " + ", ".join(sorted(unknown))
        )
    if test_requested:
        if not allow_test_smoke:
            raise ValueError(
                "test papers are forbidden by default; use --allow-test-smoke "
                "for one explicit test paper"
            )
        if len(requested) != 1 or len(test_requested) != 1:
            raise ValueError("test smoke must contain exactly one test paper")
        return "test_smoke", [paper for paper in test if paper in requested_set]
    if allow_test_smoke:
        raise ValueError("--allow-test-smoke requires exactly one test paper")
    return "targeted_dev", [paper for paper in dev if paper in requested_set]


def ensure_run_available(workspace: Path, run_id: str) -> None:
    run_id = validate_hvs_extraction_run_id(run_id)
    run_root = workspace / RUNS_RELATIVE_DIR
    if (run_root / run_id).exists():
        raise FileExistsError(f"extraction run already exists: {run_id}")
    if (run_root.parent / "locks" / f"{run_id}.lock").exists():
        raise FileExistsError(f"extraction run lock already exists: {run_id}")


def run_preflight(
    workspace: Path,
    run_id: str,
    papers: list[str],
    *,
    config: HvsExtractionMethodConfig,
    api_key: str,
    base_url: str,
) -> dict[str, Any]:
    """Perform every safe check without creating a run or calling a provider."""

    ensure_run_available(workspace, run_id)
    config.assert_frozen()
    worktree = inspect_scratch_worktree(workspace)
    if not worktree["clean_for_dev"]:
        problems = [
            *[f"tracked change: {path}" for path in worktree["tracked_changes"]],
            *[
                f"untracked execution file: {path}"
                for path in worktree["blocking_untracked"]
            ],
        ]
        raise ValueError("dev preflight blocked: " + "; ".join(problems))
    if not api_key or not base_url:
        raise ValueError("LLM_API_KEY and LLM_BASE_URL are required")
    prepared: dict[str, str] = {}
    for arxiv_id in papers:
        artifact = build_prepared_input(
            workspace,
            arxiv_id,
            roster_budget=config.roster_context_budget,
            field_budget=config.field_context_budget,
        )
        prepared[arxiv_id] = artifact["status"]
        if artifact["status"] != STATUS_PREPARED:
            detail = (artifact.get("failure") or {}).get("detail") or "unknown"
            raise ValueError(f"{arxiv_id} input preflight failed: {detail}")
    return {
        "run_id": run_id,
        "papers": list(papers),
        "worktree": worktree,
        "prepared": prepared,
        "credentials_present": True,
        "run_created": False,
        "api_calls": 0,
    }
