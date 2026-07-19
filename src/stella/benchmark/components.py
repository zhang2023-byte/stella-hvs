"""Central hashes for code and rule components that affect formal artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from stella.benchmark.task_surfaces import FULL, task_surface_sha256
from stella.lit.extraction_rules import rule_profile_sha256


REQUIRED_FORMAL_COMPONENTS = frozenset(
    {
        "prompt",
        "skill",
        "validator",
        "context_packer",
        "task_surface",
        "normalizer",
        "scorer",
        "identity_matching",
        "unit_table",
        "rule_profile",
    }
)


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_sha256(root: Path, workspace: Path) -> str:
    return _canonical_sha256(
        {
            str(path.relative_to(workspace)): _file_sha256(path)
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }
    )


def _prompt_path(workspace: Path, producer: str) -> Path | None:
    relative = {
        "stella-benchmark-extraction": "src/stella/benchmark/extraction_run.py",
        "stella-agentic-extraction": "src/stella/benchmark/agentic_run.py",
    }.get(producer)
    return workspace / relative if relative else None


def build_run_component_hashes(workspace: Path, method: dict[str, Any]) -> dict[str, str]:
    """Compute the current hashes implied by one method contract."""

    workspace = workspace.resolve()
    producer = str(method.get("producer") or "")
    parameters = method.get("parameters") if isinstance(method.get("parameters"), dict) else {}
    skill_root = workspace / "skills" / "hvs-candidates-extraction"
    skill_hash = _tree_sha256(skill_root, workspace)
    prompt_path = _prompt_path(workspace, producer)
    prompt_hash = skill_hash if prompt_path is None else _file_sha256(prompt_path)
    task_surface = str(parameters.get("task_surface") or FULL)

    from stella.benchmark.scoring import UNIT_SYNONYMS, UNIT_SYNONYMS_VERSION

    hashes = {
        "prompt": prompt_hash,
        "skill": skill_hash,
        "validator": _file_sha256(workspace / "scripts" / "validate_hvs_candidates.py"),
        "context_packer": _file_sha256(workspace / "src/stella/benchmark/context_pack.py"),
        "task_surface": task_surface_sha256(workspace, task_surface),
        "normalizer": _canonical_sha256(
            {
                "workflow_mechanics": _file_sha256(
                    workspace / "src/stella/benchmark/mechanical_normalization.py"
                ),
                "surface_hydration": _file_sha256(
                    workspace / "src/stella/benchmark/task_surfaces.py"
                ),
            }
        ),
        "scorer": _file_sha256(workspace / "src/stella/benchmark/scoring.py"),
        "identity_matching": _file_sha256(workspace / "src/stella/benchmark/identity.py"),
        "unit_table": _canonical_sha256(
            {"version": UNIT_SYNONYMS_VERSION, "synonyms": UNIT_SYNONYMS}
        ),
        "rule_profile": rule_profile_sha256(
            workspace, str(parameters.get("rule_profile_id") or "hvs_extractor")
        ),
    }
    if producer in {"stella-benchmark-extraction", "stella-agentic-extraction"}:
        hashes.update(
            {
                "roster_context_packer": _file_sha256(
                    workspace / "src/stella/benchmark/context_pack.py"
                ),
                "reviewer": _file_sha256(
                    workspace / "src/stella/benchmark/extraction_review.py"
                ),
                "roster_bundle": _file_sha256(
                    workspace / "src/stella/benchmark/roster_bundle.py"
                ),
            }
        )
        for key, default_id in (
            ("roster_rule_profile", "hvs_roster"),
            ("review_rule_profile", "hvs_reviewer"),
        ):
            profile_id = str(parameters.get(f"{key}_id") or default_id)
            hashes[key] = rule_profile_sha256(workspace, profile_id)
    if producer == "stella-agentic-extraction":
        hashes["tool_loop"] = _file_sha256(
            workspace / "src/stella/benchmark/tool_loop.py"
        )
    return hashes


def require_formal_component_contract(method: dict[str, Any]) -> dict[str, str]:
    provenance = method.get("provenance") if isinstance(method, dict) else None
    components = provenance.get("components") if isinstance(provenance, dict) else None
    if not isinstance(components, dict):
        raise ValueError("formal run requires component provenance")
    missing = sorted(REQUIRED_FORMAL_COMPONENTS - set(components))
    producer = str(method.get("producer") or "")
    if producer in {"stella-benchmark-extraction", "stella-agentic-extraction"}:
        missing.extend(
            sorted({"roster_context_packer"} - set(components))
        )
    if missing:
        raise ValueError("formal run component provenance is missing: " + ", ".join(missing))
    invalid = sorted(key for key, value in components.items() if not isinstance(value, str) or not value)
    if invalid:
        raise ValueError("formal run component hashes must be non-empty strings: " + ", ".join(invalid))
    return components


def validate_run_component_provenance(
    config: dict[str, Any],
    *,
    workspace: Path,
    current_component_hashes: dict[str, str] | None = None,
) -> dict[str, str]:
    """Fail closed when any recorded formal component differs from current code."""

    method = config.get("method") if isinstance(config.get("method"), dict) else {}
    recorded = require_formal_component_contract(method)
    current = (
        build_run_component_hashes(workspace, method)
        if current_component_hashes is None
        else dict(current_component_hashes)
    )
    component_set_drift = sorted(set(recorded) ^ set(current))
    if component_set_drift:
        raise ValueError(
            "run component set mismatch: " + ", ".join(component_set_drift)
        )
    drift = sorted(
        key for key, current_hash in current.items() if recorded.get(key) != current_hash
    )
    if drift:
        raise ValueError("run component provenance mismatch: " + ", ".join(drift))
    return current
