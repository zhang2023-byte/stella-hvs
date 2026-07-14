"""Shared immutable run contract for formal benchmark campaigns."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stella.benchmark.campaign import papers_for_split, sha256_file
from stella.benchmark.paths import validate_path_segment
from stella.schema_registry import require_schema, schema_ref
from stella.benchmark.task_surfaces import FULL, validate_surface_document

SUCCESS_STATUSES = {"ok", "ok_with_cjk_warnings"}
ARTIFACT_NAMES = (
    "literature_hvs_candidates.json",
    "report.json",
    "context_manifest.json",
)
DEFAULT_LEAKAGE_AUDIT_NAME = "leakage_audit.json"


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def git_state(workspace: Path) -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {"commit": commit, "dirty": bool(status.strip())}


def build_method_fingerprint(method: dict[str, Any]) -> str:
    return canonical_sha256(method)


def build_run_config(
    *,
    run_id: str,
    method: dict[str, Any],
    expected_papers: list[str],
    code: dict[str, Any],
    campaign: dict[str, Any] | None = None,
    campaign_sha256: str | None = None,
    split: str = "experimental",
) -> dict[str, Any]:
    run_id = validate_path_segment(run_id, "run id")
    expected_papers = [
        validate_path_segment(str(arxiv_id), "paper id")
        for arxiv_id in expected_papers
    ]
    if len(expected_papers) != len(set(expected_papers)):
        raise ValueError("expected paper set contains duplicates")
    formal = campaign is not None
    if formal:
        if split not in {"dev", "test"}:
            raise ValueError("formal run split must be dev or test")
        campaign_papers = papers_for_split(campaign, split)
        if expected_papers != campaign_papers:
            raise ValueError("expected papers must exactly match campaign split order")
        if code.get("dirty") is not False:
            raise ValueError("formal runs require a clean worktree")
        models = method.get("models") if isinstance(method, dict) else None
        if isinstance(models, dict):
            reviewer = models.get("reviewer")
            if reviewer and reviewer == models.get("extractor"):
                raise ValueError(
                    "formal reviewed methods require distinct extractor and reviewer model ids"
                )
    fingerprint = build_method_fingerprint(method)
    campaign_ref = None
    if campaign is not None:
        campaign_ref = {
            "campaign_id": campaign["campaign_id"],
            "sha256": campaign_sha256 or canonical_sha256(campaign),
        }
    return {
        "schema": schema_ref("benchmark.run_config"),
        "run_id": run_id,
        "mode": "formal" if formal else "experimental",
        "campaign": campaign_ref,
        "split": split,
        "expected_papers": expected_papers,
        "code": code,
        "method": method,
        "method_fingerprint": fingerprint,
        "state": "open",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def ensure_run_config(run_dir: Path, desired: dict[str, Any]) -> dict[str, Any]:
    if (run_dir / "run_manifest.json").exists():
        raise ValueError("run is sealed and cannot be modified")
    path = run_dir / "run_config.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        try:
            require_schema(existing, "benchmark.run_config", require_current=True)
        except ValueError:
            raise ValueError("formal campaign refuses legacy run_config")
        stable_keys = (
            "run_id",
            "mode",
            "campaign",
            "split",
            "expected_papers",
            "code",
            "method",
            "method_fingerprint",
        )
        drift = [key for key in stable_keys if existing.get(key) != desired.get(key)]
        if drift:
            raise ValueError(f"run config drift: {', '.join(drift)}")
        return existing
    run_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(desired, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return desired


def paper_status(paper_dir: Path) -> str:
    report = paper_dir / "report.json"
    if not report.is_file():
        return "missing"
    try:
        payload = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "invalid_report"
    return str(payload.get("status") or "invalid_report")


def prepare_paper_retry(run_dir: Path, arxiv_id: str) -> Path | None:
    """Archive a failed attempt and return its archive path.

    A successful paper is immutable even while the run is open. Sealed runs
    reject every retry. Missing paper directories need no archive.
    """

    arxiv_id = validate_path_segment(arxiv_id, "paper id")
    if (run_dir / "run_manifest.json").exists():
        raise ValueError("run is sealed and cannot be retried")
    paper_dir = run_dir / arxiv_id
    if not paper_dir.exists():
        return None
    status = paper_status(paper_dir)
    if status in SUCCESS_STATUSES:
        raise ValueError(f"successful paper {arxiv_id} cannot be rerun")
    archive_root = run_dir / "_failed_attempts" / arxiv_id
    archive_root.mkdir(parents=True, exist_ok=True)
    attempt = 1
    while (archive_root / f"attempt-{attempt:03d}").exists():
        attempt += 1
    destination = archive_root / f"attempt-{attempt:03d}"
    shutil.move(str(paper_dir), str(destination))
    return destination


def prepare_run_resume(run_dir: Path, papers: list[str]) -> dict[str, Any]:
    """Return the pending queue while preserving immutable successes.

    Failed or interrupted paper directories with actual run attempts are
    archived before they are queued. A context-only directory is safe to
    reuse because no model call or result has been persisted there.
    """

    if (run_dir / "run_manifest.json").exists():
        raise ValueError("run is sealed and cannot be resumed")
    pending: list[str] = []
    skipped_success: list[str] = []
    archived: dict[str, str] = {}
    for value in papers:
        arxiv_id = validate_path_segment(str(value), "paper id")
        paper_dir = run_dir / arxiv_id
        if paper_status(paper_dir) in SUCCESS_STATUSES:
            skipped_success.append(arxiv_id)
            continue
        has_attempt = any(
            (paper_dir / name).exists()
            for name in ("attempts", "report.json", "literature_hvs_candidates.json")
        )
        if has_attempt:
            destination = prepare_paper_retry(run_dir, arxiv_id)
            if destination is not None:
                archived[arxiv_id] = str(destination)
        pending.append(arxiv_id)
    return {
        "pending": pending,
        "skipped_success": skipped_success,
        "archived": archived,
    }


def _paper_fingerprint(document: dict[str, Any]) -> str:
    extraction = document.get("extraction") if isinstance(document, dict) else None
    provenance = extraction.get("provenance") if isinstance(extraction, dict) else None
    parameters = provenance.get("parameters") if isinstance(provenance, dict) else None
    return str(parameters.get("method_fingerprint") or "") if isinstance(parameters, dict) else ""


def load_leakage_audit(run_dir: Path, audit_path: Path | None = None) -> dict[str, Any]:
    path = audit_path or run_dir / DEFAULT_LEAKAGE_AUDIT_NAME
    if not path.is_file():
        raise ValueError("leakage audit report is required before sealing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("leakage audit report is not valid JSON") from exc
    try:
        require_schema(payload, "benchmark.leakage_audit", require_current=True)
    except ValueError:
        raise ValueError("leakage audit report has an unsupported schema")
    try:
        audited_run = Path(str(payload["run_dir"])).resolve()
    except (KeyError, TypeError) as exc:
        raise ValueError("leakage audit report is missing run_dir") from exc
    if audited_run != run_dir.resolve():
        raise ValueError("leakage audit report belongs to a different run")
    status = payload.get("status")
    if status not in {"clean", "contaminated"}:
        raise ValueError("leakage audit report has an invalid status")
    try:
        relative_path = str(path.resolve().relative_to(run_dir.resolve()))
    except ValueError as exc:
        raise ValueError("leakage audit report must live inside the run directory") from exc
    return {
        "path": relative_path,
        "sha256": sha256_file(path),
        "status": status,
        "files_scanned": int(payload.get("files_scanned", 0)),
        "markers_scanned": int(payload.get("markers_scanned", 0)),
        "hits_count": len(payload.get("hits") or []),
    }


def seal_run(
    run_dir: Path,
    *,
    workspace: Path,
    validator_module: Any,
    audit_path: Path | None = None,
) -> dict[str, Any]:
    manifest_path = run_dir / "run_manifest.json"
    if manifest_path.exists():
        raise ValueError("run is already sealed")
    config_path = run_dir / "run_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    try:
        require_schema(config, "benchmark.run_config", require_current=True)
    except ValueError:
        raise ValueError("cannot seal a legacy run")
    leakage_audit = load_leakage_audit(run_dir, audit_path)
    method_parameters = (config.get("method") or {}).get("parameters") or {}
    task_surface = str(method_parameters.get("task_surface") or FULL)

    outcomes: dict[str, list[str]] = {"valid": [], "invalid": [], "missing": []}
    artifacts: dict[str, dict[str, dict[str, Any]]] = {}
    for arxiv_id in config["expected_papers"]:
        arxiv_id = validate_path_segment(str(arxiv_id), "paper id")
        paper_dir = run_dir / arxiv_id
        if not paper_dir.is_dir():
            outcomes["missing"].append(arxiv_id)
            continue
        files: dict[str, dict[str, Any]] = {}
        missing_artifacts = False
        for name in ARTIFACT_NAMES:
            path = paper_dir / name
            if not path.is_file():
                missing_artifacts = True
                continue
            files[name] = {"sha256": sha256_file(path), "bytes": path.stat().st_size}
        artifacts[arxiv_id] = files
        output_path = paper_dir / "literature_hvs_candidates.json"
        try:
            document = json.loads(output_path.read_text(encoding="utf-8"))
            surface_errors = validate_surface_document(document, task_surface)
            report = validator_module.validate_hvs_candidates_report(
                document, workspace=workspace, require_complete=True
            )
            valid = (
                not missing_artifacts
                and paper_status(paper_dir) in SUCCESS_STATUSES
                and not surface_errors
                and not report.errors
                and _paper_fingerprint(document) == config["method_fingerprint"]
            )
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            valid = False
        outcomes["valid" if valid else "invalid"].append(arxiv_id)

    manifest = {
        "schema": schema_ref("benchmark.run_manifest"),
        "run_id": config["run_id"],
        "campaign": config["campaign"],
        "split": config["split"],
        "method_fingerprint": config["method_fingerprint"],
        "run_config_sha256": sha256_file(config_path),
        "sealed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "papers": outcomes,
        "artifacts": artifacts,
        "leakage_audit": leakage_audit,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest
