"""Tool-neutral, data-minimizing harness for method-A benchmark runs.

The harness limits accidental context contamination by constructing one
paper-local bundle. It is not a security sandbox against an adapter that
deliberately opens arbitrary absolute paths.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BUNDLE_SCHEMA_VERSION = "stella.benchmark_agent_bundle.v0.1"
TEXT_SUFFIXES = {".tex", ".bib", ".bbl"}


@dataclass(frozen=True)
class AgentBundle:
    run_id: str
    arxiv_id: str
    root: Path
    task_path: Path
    output_path: Path
    input_manifest_path: Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _bundle_files(bundle_root: Path) -> list[Path]:
    return sorted(path for path in bundle_root.rglob("*") if path.is_file())


def _expected_harness(config: dict[str, Any]) -> tuple[str, str, str, str]:
    method = config.get("method") if isinstance(config.get("method"), dict) else {}
    harness = method.get("harness") if isinstance(method.get("harness"), dict) else {}
    models = method.get("models") if isinstance(method.get("models"), dict) else {}
    versions = method.get("versions") if isinstance(method.get("versions"), dict) else {}
    name = str(harness.get("name") or "")
    version = str(harness.get("version") or "")
    model = str(models.get("extractor") or "")
    prompt = str(versions.get("prompt") or "")
    if not all((name, version, model, prompt)):
        raise ValueError("method-A run config needs harness, model, and prompt versions")
    return name, version, model, prompt


def prepare_bundle(
    *,
    workspace: Path,
    run_dir: Path,
    bundle_root: Path,
    arxiv_id: str,
    run_config: dict[str, Any],
) -> AgentBundle:
    if arxiv_id not in run_config.get("expected_papers", []):
        raise ValueError(f"paper {arxiv_id} is outside the run contract")
    name, version, model, prompt = _expected_harness(run_config)
    root = bundle_root / run_config["run_id"] / arxiv_id
    if root.exists():
        raise ValueError(f"bundle already exists: {root}")
    paper_dir = workspace / "literature" / arxiv_id
    source_dir = paper_dir / "arxiv_source"
    if not source_dir.is_dir():
        raise FileNotFoundError(f"missing TeX source: {source_dir}")

    for filename in ("catalog_review.json", "catalog_extraction.json"):
        source = paper_dir / filename
        if not source.is_file():
            raise FileNotFoundError(f"missing required input: {source}")
        _copy(source, root / "inputs" / filename)
    for source in sorted(source_dir.rglob("*")):
        if source.is_file() and source.suffix.lower() in TEXT_SUFFIXES:
            _copy(source, root / "inputs" / "arxiv_source" / source.relative_to(source_dir))
    tables = paper_dir / "catalog_tables"
    for source in sorted(tables.rglob("*.ecsv")) if tables.is_dir() else []:
        _copy(source, root / "inputs" / "catalog_tables" / source.relative_to(tables))

    skill_dir = workspace / "skills" / "hvs-candidates-extraction"
    for source in sorted(skill_dir.rglob("*")):
        if source.is_file():
            _copy(source, root / "skill" / source.relative_to(skill_dir))
    validator = workspace / "scripts" / "validate_hvs_candidates.py"
    if not validator.is_file():
        raise FileNotFoundError(f"missing validator: {validator}")
    _copy(validator, root / "validator" / validator.name)

    output_path = root / "output" / "literature_hvs_candidates.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    task_path = root / "task.json"
    task = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "run_id": run_config["run_id"],
        "arxiv_id": arxiv_id,
        "method_fingerprint": run_config["method_fingerprint"],
        "tooling": {
            "agent_runtime": f"{name}/{version}",
            "model_id": model,
            "prompt_version": prompt,
        },
        "output": "output/literature_hvs_candidates.json",
        "input_policy": "one paper only; no historical runs, scoring, reports, or private annotations",
    }
    task_path.parent.mkdir(parents=True, exist_ok=True)
    task_path.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    manifest_path = root / "input_manifest.json"
    files = []
    for path in _bundle_files(root):
        if path == manifest_path:
            continue
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    manifest = {"schema_version": BUNDLE_SCHEMA_VERSION, "files": files}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return AgentBundle(run_config["run_id"], arxiv_id, root, task_path, output_path, manifest_path)


def launch_adapter(
    *, bundle: AgentBundle,
    argv: list[str],
    base_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    if not argv:
        raise ValueError("agent adapter argv is required")
    env = dict(os.environ if base_env is None else base_env)
    env.pop("STELLA_GOLD_DIR", None)
    env.update(
        {
            "STELLA_BENCHMARK_TASK": str(bundle.task_path),
            "STELLA_BENCHMARK_OUTPUT": str(bundle.output_path),
            "STELLA_BENCHMARK_BUNDLE": str(bundle.root),
        }
    )
    return subprocess.run(argv, cwd=bundle.root, env=env, shell=False, check=False)


def _verify_inputs(bundle: AgentBundle) -> list[str]:
    manifest = json.loads(bundle.input_manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    for item in manifest.get("files", []):
        path = bundle.root / str(item.get("path") or "")
        if not path.is_file():
            errors.append(f"missing input: {item.get('path')}")
        elif _sha256(path) != item.get("sha256"):
            errors.append(f"input hash changed: {item.get('path')}")
    return errors


def _write_report(paper_dir: Path, payload: dict[str, Any]) -> None:
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def collect_bundle(
    *,
    workspace: Path,
    run_dir: Path,
    bundle: AgentBundle,
    run_config: dict[str, Any],
    validator_module: Any,
) -> dict[str, Any]:
    paper_dir = run_dir / bundle.arxiv_id
    base_report: dict[str, Any] = {"arxiv_id": bundle.arxiv_id, "method": "agent_harness"}
    input_errors = _verify_inputs(bundle)
    if input_errors:
        report = {**base_report, "status": "input_mutated", "errors": input_errors}
        _write_report(paper_dir, report)
        return report
    if not bundle.output_path.is_file():
        report = {**base_report, "status": "missing_output", "errors": ["adapter output missing"]}
        _write_report(paper_dir, report)
        return report
    try:
        document = json.loads(bundle.output_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        report = {**base_report, "status": "invalid_json", "output_sha256": _sha256(bundle.output_path)}
        _write_report(paper_dir, report)
        return report
    name, version, model, prompt = _expected_harness(run_config)
    extraction = document.get("extraction") if isinstance(document, dict) else None
    tooling = extraction.get("tooling") if isinstance(extraction, dict) else None
    parameters = tooling.get("request_parameters") if isinstance(tooling, dict) else None
    expected = {
        "agent_runtime": f"{name}/{version}",
        "model_id": model,
        "prompt_version": prompt,
        "method_fingerprint": run_config["method_fingerprint"],
    }
    actual = {
        "agent_runtime": tooling.get("agent_runtime") if isinstance(tooling, dict) else None,
        "model_id": tooling.get("model_id") if isinstance(tooling, dict) else None,
        "prompt_version": tooling.get("prompt_version") if isinstance(tooling, dict) else None,
        "method_fingerprint": parameters.get("method_fingerprint") if isinstance(parameters, dict) else None,
    }
    mismatch = [key for key, value in expected.items() if actual.get(key) != value]
    if mismatch:
        report = {**base_report, "status": "tooling_mismatch", "fields": mismatch, "output_sha256": _sha256(bundle.output_path)}
        _write_report(paper_dir, report)
        return report
    validation = validator_module.validate_hvs_candidates_report(document, workspace=workspace, require_complete=True)
    if validation.errors:
        report = {**base_report, "status": "validator_errors", "errors": list(validation.errors), "output_sha256": _sha256(bundle.output_path)}
        _write_report(paper_dir, report)
        return report
    paper_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(bundle.output_path, paper_dir / "literature_hvs_candidates.json")
    inputs = json.loads(bundle.input_manifest_path.read_text(encoding="utf-8"))
    (paper_dir / "context_manifest.json").write_text(
        json.dumps({"packer_version": BUNDLE_SCHEMA_VERSION, "files": inputs["files"]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report = {**base_report, "status": "ok", "validator_warnings_count": len(validation.warnings)}
    _write_report(paper_dir, report)
    return report
