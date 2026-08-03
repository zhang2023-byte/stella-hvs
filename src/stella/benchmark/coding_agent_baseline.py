"""Isolated comparison harness for a general coding agent.

The adapter receives exactly one paper's maintained extraction input boundary
and the shared scientific rules.  It writes a v3 core document directly.  No
roster proposal, field-stage result, repair, or other staged-workflow artifact
is exposed or reused.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stella.benchmark.campaign import sha256_file
from stella.benchmark.paths import validate_path_segment
from stella.benchmark.run_contract import canonical_sha256, require_v6_run_manifest
from stella.hvs_extraction.method_config import default_hvs_extraction_method_config
from stella.hvs_extraction.prepare import STATUS_PREPARED, build_prepared_input
from stella.hvs_extraction.run import (
    reserve_run_directory,
    validate_hvs_extraction_run_id,
)
from stella.lit.arxiv_ids import validate_unversioned_arxiv_id
from stella.lit.extraction_rules import rule_profile_sha256
from stella.lit.schema_models import validate_literature_hvs_document
from stella.schema_registry import require_schema, schema_ref


BASELINE_PRODUCER = "coding_agent_baseline"
BASELINE_RULE_PROFILE = "coding_agent_baseline"
OUTPUT_RELATIVE_PATH = Path("output/literature_hvs_candidates.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _component_digest(workspace: Path, relative: str) -> str:
    path = workspace / relative
    if path.is_file():
        return sha256_file(path)
    return canonical_sha256({"fixture_component_unavailable": relative})


def build_baseline_component_hashes(workspace: Path) -> dict[str, str]:
    """Fingerprint the independent baseline and shared scoring contract."""

    from stella.benchmark.scoring import UNIT_SYNONYMS, UNIT_SYNONYMS_VERSION

    return {
        "baseline_harness": _component_digest(
            workspace, "src/stella/benchmark/coding_agent_baseline.py"
        ),
        "validator": _component_digest(
            workspace, "scripts/validate_hvs_candidates.py"
        ),
        "scorer": _component_digest(workspace, "src/stella/benchmark/scoring.py"),
        "identity_matching": _component_digest(
            workspace, "src/stella/benchmark/identity.py"
        ),
        "unit_table": canonical_sha256(
            {"version": UNIT_SYNONYMS_VERSION, "synonyms": UNIT_SYNONYMS}
        ),
        "rule_profile": rule_profile_sha256(workspace, BASELINE_RULE_PROFILE),
        "input_preparation": _component_digest(
            workspace, "src/stella/hvs_extraction/prepare.py"
        ),
        "core_schema": _component_digest(
            workspace, "src/stella/lit/schema_models.py"
        ),
    }


def create_baseline_run_config(
    workspace: Path,
    *,
    run_id: str,
    papers: list[str],
    scope: str,
    campaign_binding: dict[str, str],
    runtime_name: str,
    runtime_release: str,
    model_id: str,
    code: dict[str, Any],
) -> dict[str, Any]:
    """Atomically create an immutable V6 baseline run."""

    run_id = validate_hvs_extraction_run_id(run_id)
    papers = [validate_unversioned_arxiv_id(paper) for paper in papers]
    if not papers or len(papers) != len(set(papers)):
        raise ValueError("baseline papers must be non-empty and unique")
    if scope not in {"full_dev", "targeted_dev", "test_smoke"}:
        raise ValueError(f"invalid baseline scope: {scope}")
    if scope == "test_smoke" and len(papers) != 1:
        raise ValueError("test_smoke requires exactly one paper")
    if not all((runtime_name, runtime_release, model_id)):
        raise ValueError("baseline runtime name, release, and model id are required")
    if set(campaign_binding) != {
        "campaign_id",
        "manifest_path",
        "manifest_sha256",
    }:
        raise ValueError("baseline campaign binding is incomplete")
    method = {
        "producer": BASELINE_PRODUCER,
        "runtime": {"name": runtime_name, "release": runtime_release},
        "model": {"id": model_id},
        "input_contract": "canonical_prepared_input_v1",
        "output_contract": "literature_hvs_candidates_v3",
        "rule_profile": {
            "id": BASELINE_RULE_PROFILE,
            "sha256": rule_profile_sha256(workspace, BASELINE_RULE_PROFILE),
        },
    }
    component_hashes = build_baseline_component_hashes(workspace)
    method_fingerprint = canonical_sha256(method)
    stable = {
        "run_id": run_id,
        "campaign": dict(campaign_binding),
        "scope": scope,
        "papers": papers,
        "execution": {
            "kind": BASELINE_PRODUCER,
            "adapter_isolation": "one_paper_bundle",
        },
        "method": method,
        "models": {"coding_agent": model_id},
        "component_hashes": component_hashes,
        "method_fingerprint": method_fingerprint,
        "code": {
            "revision": code.get("revision"),
            "worktree": dict(code),
        },
    }
    config = {
        "schema": schema_ref("benchmark.run_config"),
        "created_at": _utc_now(),
        **stable,
        "run_fingerprint": canonical_sha256(stable),
    }
    run_dir = reserve_run_directory(workspace, run_id)
    _atomic_write_json(run_dir / "run_config.json", config)
    return config


@dataclass(frozen=True)
class CodingAgentBundle:
    run_id: str
    arxiv_id: str
    root: Path
    task_path: Path
    output_path: Path
    input_manifest_path: Path


def _load_config(run_dir: Path) -> dict[str, Any]:
    config = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
    require_schema(config, "benchmark.run_config", require_current=True)
    if (config.get("method") or {}).get("producer") != BASELINE_PRODUCER:
        raise ValueError("run config is not a coding-agent baseline")
    return config


def load_bundle(bundle_root: Path) -> CodingAgentBundle:
    root = bundle_root.expanduser().resolve()
    task_path = root / "task.json"
    try:
        task = json.loads(task_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("bundle task.json is missing or invalid") from exc
    require_schema(task, "benchmark.coding_agent_bundle", require_current=True)
    run_id = validate_path_segment(str(task.get("run_id") or ""), "baseline run id")
    arxiv_id = validate_unversioned_arxiv_id(str(task.get("arxiv_id") or ""))
    if task.get("output") != OUTPUT_RELATIVE_PATH.as_posix():
        raise ValueError("bundle task contains an invalid output path")
    return CodingAgentBundle(
        run_id=run_id,
        arxiv_id=arxiv_id,
        root=root,
        task_path=task_path,
        output_path=root / OUTPUT_RELATIVE_PATH,
        input_manifest_path=root / "input_manifest.json",
    )


def _bundle_files(bundle_root: Path) -> list[Path]:
    return sorted(path for path in bundle_root.rglob("*") if path.is_file())


def prepare_bundle(
    *,
    workspace: Path,
    run_dir: Path,
    bundle_root: Path,
    arxiv_id: str,
) -> CodingAgentBundle:
    """Create one data-minimized paper bundle without invoking an adapter."""

    config = _load_config(run_dir)
    arxiv_id = validate_unversioned_arxiv_id(arxiv_id)
    if arxiv_id not in config["papers"]:
        raise ValueError(f"paper {arxiv_id} is outside the run contract")
    root = bundle_root / config["run_id"] / arxiv_id
    if root.exists():
        raise ValueError(f"bundle already exists: {root}")

    extraction_config = default_hvs_extraction_method_config(workspace)
    prepared = build_prepared_input(
        workspace,
        arxiv_id,
        roster_budget=extraction_config.roster_context_budget,
        field_budget=extraction_config.field_context_budget,
    )
    if prepared["status"] != STATUS_PREPARED:
        detail = (prepared.get("failure") or {}).get("detail") or "unknown"
        raise ValueError(f"paper input preparation failed: {detail}")
    _atomic_write_json(root / "inputs" / "prepared_input.json", prepared)
    paper_dir = workspace / "literature" / arxiv_id
    for item in prepared.get("ecsv", {}).get("selected") or []:
        relative = Path(str(item["ecsv_path"]))
        _copy(paper_dir / relative, root / "inputs" / "ecsv" / relative.name)

    rules_root = workspace / "skills" / "hvs-candidates-extraction"
    for source in sorted(rules_root.rglob("*")):
        if source.is_file():
            _copy(source, root / "skill" / source.relative_to(rules_root))
    _copy(
        workspace / "scripts" / "validate_hvs_candidates.py",
        root / "validator" / "validate_hvs_candidates.py",
    )

    output_path = root / OUTPUT_RELATIVE_PATH
    output_path.parent.mkdir(parents=True, exist_ok=True)
    task = {
        "schema": schema_ref("benchmark.coding_agent_bundle"),
        "run_id": config["run_id"],
        "arxiv_id": arxiv_id,
        "campaign": config["campaign"],
        "method_fingerprint": config["method_fingerprint"],
        "producer": BASELINE_PRODUCER,
        "rule_profile": config["method"]["rule_profile"],
        "output_schema": schema_ref("literature_hvs_candidates"),
        "output": OUTPUT_RELATIVE_PATH.as_posix(),
        "input_policy": (
            "one paper only; canonical prepared manuscript and selected ECSV; "
            "no historical runs, scorecards, reports, or private annotations"
        ),
    }
    task_path = root / "task.json"
    _atomic_write_json(task_path, task)

    manifest_path = root / "input_manifest.json"
    files = [
        {
            "path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in _bundle_files(root)
        if path != manifest_path
    ]
    _atomic_write_json(
        manifest_path,
        {
            "schema": schema_ref("benchmark.coding_agent_bundle"),
            "files": files,
        },
    )
    return CodingAgentBundle(
        config["run_id"],
        arxiv_id,
        root,
        task_path,
        output_path,
        manifest_path,
    )


def launch_adapter(
    *,
    bundle: CodingAgentBundle,
    argv: list[str],
    base_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Launch a user-selected adapter with private-gold variables removed."""

    if not argv:
        raise ValueError("coding-agent adapter argv is required")
    env = dict(os.environ if base_env is None else base_env)
    env.pop("STELLA_GOLD_DIR", None)
    env.update(
        {
            "STELLA_BENCHMARK_TASK": str(bundle.task_path),
            "STELLA_BENCHMARK_OUTPUT": str(bundle.output_path),
            "STELLA_BENCHMARK_BUNDLE": str(bundle.root),
        }
    )
    return subprocess.run(
        argv, cwd=bundle.root, env=env, shell=False, check=False
    )


def _verify_inputs(bundle: CodingAgentBundle) -> list[str]:
    manifest = json.loads(
        bundle.input_manifest_path.read_text(encoding="utf-8")
    )
    errors: list[str] = []
    for item in manifest.get("files") or []:
        path = bundle.root / str(item.get("path") or "")
        if not path.is_file():
            errors.append(f"missing input: {item.get('path')}")
        elif _sha256(path) != item.get("sha256"):
            errors.append(f"input hash changed: {item.get('path')}")
    return errors


def _write_report(run_dir: Path, arxiv_id: str, report: dict[str, Any]) -> None:
    _atomic_write_json(run_dir / arxiv_id / "report.json", report)


def _expected_output_bindings(
    document: dict[str, Any],
    *,
    config: dict[str, Any],
    arxiv_id: str,
) -> list[str]:
    errors: list[str] = []
    if document.get("paper", {}).get("arxiv_id") != arxiv_id:
        errors.append("paper.arxiv_id")
    if document.get("inputs", {}).get("campaign_id") != config["campaign"][
        "campaign_id"
    ]:
        errors.append("inputs.campaign_id")
    if document.get("inputs", {}).get("source_run_id") != config["run_id"]:
        errors.append("inputs.source_run_id")
    production = document.get("production") or {}
    if production.get("producer") != BASELINE_PRODUCER:
        errors.append("production.producer")
    if production.get("method_fingerprint") != config["method_fingerprint"]:
        errors.append("production.method_fingerprint")
    if production.get("component_hashes") != config["component_hashes"]:
        errors.append("production.component_hashes")
    return errors


def collect_bundle(
    *,
    workspace: Path,
    run_dir: Path,
    bundle: CodingAgentBundle,
    validator_module: Any,
) -> dict[str, Any]:
    """Validate and archive one direct v3 baseline result."""

    config = _load_config(run_dir)
    report_base = {
        "schema": schema_ref("benchmark.run_event"),
        "generated_at": _utc_now(),
        "run_id": config["run_id"],
        "arxiv_id": bundle.arxiv_id,
        "producer": BASELINE_PRODUCER,
    }
    input_errors = _verify_inputs(bundle)
    if input_errors:
        report = {
            **report_base,
            "status": "failed",
            "roster_status": None,
            "failure": {"code": "input_mutated", "details": input_errors},
            "candidate_counts": {},
            "usage": {},
        }
        _write_report(run_dir, bundle.arxiv_id, report)
        return report
    if not bundle.output_path.is_file():
        report = {
            **report_base,
            "status": "failed",
            "roster_status": None,
            "failure": {"code": "missing_output"},
            "candidate_counts": {},
            "usage": {},
        }
        _write_report(run_dir, bundle.arxiv_id, report)
        return report
    try:
        document = json.loads(bundle.output_path.read_text(encoding="utf-8"))
        require_schema(
            document, "literature_hvs_candidates", require_current=True
        )
        validate_literature_hvs_document(document)
    except (json.JSONDecodeError, ValueError) as exc:
        report = {
            **report_base,
            "status": "failed",
            "roster_status": None,
            "failure": {"code": "invalid_output", "detail": str(exc)},
            "candidate_counts": {},
            "usage": {},
        }
        _write_report(run_dir, bundle.arxiv_id, report)
        return report
    binding_errors = _expected_output_bindings(
        document, config=config, arxiv_id=bundle.arxiv_id
    )
    validation = validator_module.validate_hvs_candidates_report(
        document, workspace=workspace, require_complete=True
    )
    errors = [
        *[f"binding mismatch: {field}" for field in binding_errors],
        *list(validation.errors),
    ]
    if errors:
        report = {
            **report_base,
            "status": "failed",
            "roster_status": None,
            "failure": {"code": "validator_errors", "details": errors},
            "candidate_counts": {},
            "usage": {},
        }
        _write_report(run_dir, bundle.arxiv_id, report)
        return report

    status = document["extraction"]["status"]
    roster_status = document["extraction"].get("roster_status")
    candidates = document.get("candidates") or []
    counts = {
        "total": len(candidates),
        "fields_complete": sum(
            item.get("field_status") == "fields_complete"
            for item in candidates
        ),
        "field_extraction_failed": sum(
            item.get("field_status") == "field_extraction_failed"
            for item in candidates
        ),
    }
    paper_dir = run_dir / bundle.arxiv_id
    _atomic_write_json(
        paper_dir / "literature_hvs_candidates.json", document
    )
    _atomic_write_json(
        paper_dir / "context_manifest.json",
        json.loads(bundle.input_manifest_path.read_text(encoding="utf-8")),
    )
    report = {
        **report_base,
        "status": status,
        "roster_status": roster_status,
        "failure": None,
        "candidate_counts": counts,
        "usage": {},
    }
    _write_report(run_dir, bundle.arxiv_id, report)
    return report


def finalize_baseline_run(run_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Seal a baseline run once from config order and accepted core documents."""

    config = _load_config(run_dir)
    if (run_dir / "run_summary.json").exists() or (
        run_dir / "run_manifest.json"
    ).exists():
        raise ValueError("baseline run is already finalized")
    l1 = {"complete": [], "failed": [], "missing": []}
    l2 = {
        "complete": [],
        "partial": [],
        "failed": [],
        "missing": [],
    }
    artifacts: dict[str, dict[str, dict[str, Any]]] = {}
    candidate_counts = {
        "total": 0,
        "fields_complete": 0,
        "field_extraction_failed": 0,
    }
    paper_summary: dict[str, Any] = {}
    for arxiv_id in config["papers"]:
        report_path = run_dir / arxiv_id / "report.json"
        core_path = run_dir / arxiv_id / "literature_hvs_candidates.json"
        if not report_path.is_file():
            l1["missing"].append(arxiv_id)
            l2["missing"].append(arxiv_id)
            paper_summary[arxiv_id] = {"status": "missing"}
            continue
        report = json.loads(report_path.read_text(encoding="utf-8"))
        roster_status = report.get("roster_status")
        if roster_status in {"candidates_found", "no_candidates"} and core_path.is_file():
            l1["complete"].append(arxiv_id)
        else:
            l1["failed"].append(arxiv_id)
        status = str(report.get("status") or "failed")
        if status not in l2 or not core_path.is_file():
            status = "failed"
        l2[status].append(arxiv_id)
        counts = report.get("candidate_counts") or {}
        for key in candidate_counts:
            candidate_counts[key] += int(counts.get(key) or 0)
        paper_artifacts: dict[str, dict[str, Any]] = {}
        for path in (report_path, core_path):
            if path.is_file():
                paper_artifacts[path.name] = {
                    "sha256": sha256_file(path),
                    "bytes": path.stat().st_size,
                }
        artifacts[arxiv_id] = paper_artifacts
        paper_summary[arxiv_id] = {
            "status": status,
            "roster_status": roster_status,
            "candidate_counts": counts,
        }

    delivered = len(l1["complete"])
    empty_format_validation = {
        "observed_units": 0,
        "valid_first_pass": 0,
        "valid_after_correction": 0,
        "invalid": 0,
        "not_observed": 0,
        "first_pass_rate": 0.0,
        "final_valid_rate": 0.0,
    }
    not_applicable_usage = {
        "prompt_tokens": 0,
        "cached_input_tokens": 0,
        "uncached_input_tokens": 0,
        "completion_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
        "api_calls": 0,
        "telemetry_status": "not_applicable",
        "warnings": [],
    }
    usage = {
        "by_role": {
            "roster": dict(not_applicable_usage),
            "core_fields": dict(not_applicable_usage),
        },
        "total": dict(not_applicable_usage),
    }
    summary = {
        "schema": schema_ref("benchmark.run_summary"),
        "generated_at": _utc_now(),
        "run_id": config["run_id"],
        "run_fingerprint": config["run_fingerprint"],
        "scope": config["scope"],
        "state": "completed",
        "papers": paper_summary,
        "format_validation": dict(empty_format_validation),
        "usage": usage,
        "totals": {
            "expected": len(config["papers"]),
            "delivered": delivered,
            "delivery_rate": (
                round(delivered / len(config["papers"]), 6)
                if config["papers"]
                else 0.0
            ),
            "complete": len(l2["complete"]),
            "partial": len(l2["partial"]),
            "failed": len(l2["failed"]),
            "missing": len(l2["missing"]),
            "api_calls": 0,
            "tokens": 0,
            "elapsed_seconds": 0.0,
        },
    }
    _atomic_write_json(run_dir / "run_summary.json", summary)
    if len(l2["complete"]) == len(config["papers"]):
        run_status = "complete"
    elif l1["complete"]:
        run_status = "partial"
    else:
        run_status = "failed"
    manifest = {
        "schema": schema_ref("benchmark.run_manifest"),
        "run_id": config["run_id"],
        "campaign": config["campaign"],
        "scope": config["scope"],
        "papers": list(config["papers"]),
        "method_fingerprint": config["method_fingerprint"],
        "component_hashes": config["component_hashes"],
        "run_fingerprint": config["run_fingerprint"],
        "run_config_sha256": sha256_file(run_dir / "run_config.json"),
        "run_summary_sha256": sha256_file(run_dir / "run_summary.json"),
        "sealed_at": _utc_now(),
        "status": run_status,
        "l1_roster_delivery": l1,
        "l2_core_field_delivery": {
            **l2,
            "candidate_counts": candidate_counts,
        },
        "l0": {"format_validation": dict(empty_format_validation)},
        "usage": usage,
        "artifacts": artifacts,
    }
    require_v6_run_manifest(manifest)
    _atomic_write_json(run_dir / "run_manifest.json", manifest)
    return summary, manifest
