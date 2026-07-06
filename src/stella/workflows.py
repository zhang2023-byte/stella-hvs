from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


DEFAULT_ROOT = Path(__file__).resolve().parents[2]
INDEX_RELATIVE_PATH = Path("workflows") / "stella_workflows.yaml"
DEFINITIONS_DIR_NAME = "definitions"


def load_workflow_index(root: Path | None = None) -> dict[str, Any]:
    """Load the workflow index without expanding per-workflow definitions."""
    repo_root = _repo_root(root)
    index_path = repo_root / INDEX_RELATIVE_PATH
    index = _load_yaml_mapping(index_path)
    _validate_index(index, index_path)
    return index


def load_workflow_definition(workflow_id: str, root: Path | None = None) -> dict[str, Any]:
    """Load one workflow definition from the workflow index."""
    repo_root = _repo_root(root)
    index_path = repo_root / INDEX_RELATIVE_PATH
    index = load_workflow_index(repo_root)
    for entry in index["workflows"]:
        if entry["id"] == workflow_id:
            return _load_definition_for_entry(entry, index_path)
    raise KeyError(f"Unknown workflow id: {workflow_id}")


def load_workflow_manifest(root: Path | None = None) -> dict[str, Any]:
    """Load the full workflow manifest with all workflow definitions expanded."""
    repo_root = _repo_root(root)
    index_path = repo_root / INDEX_RELATIVE_PATH
    index = load_workflow_index(repo_root)
    manifest = {
        key: deepcopy(value)
        for key, value in index.items()
        if key != "workflows"
    }
    manifest["workflows"] = [
        _load_definition_for_entry(entry, index_path)
        for entry in index["workflows"]
    ]
    return manifest


def _repo_root(root: Path | None) -> Path:
    return Path(root).resolve() if root is not None else DEFAULT_ROOT


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return payload


def _validate_index(index: dict[str, Any], index_path: Path) -> None:
    workflows = index.get("workflows")
    if not isinstance(workflows, list) or not workflows:
        raise ValueError(f"{index_path} must declare a non-empty workflows list")

    seen_ids: set[str] = set()
    seen_files: set[str] = set()
    for entry in workflows:
        if not isinstance(entry, dict):
            raise ValueError(f"{index_path} workflow entries must be mappings")
        workflow_id = entry.get("id")
        if not isinstance(workflow_id, str) or not workflow_id:
            raise ValueError(f"{index_path} workflow entries must declare id")
        if workflow_id in seen_ids:
            raise ValueError(f"Duplicate workflow id in {index_path}: {workflow_id}")
        seen_ids.add(workflow_id)

        file_value = entry.get("file")
        if file_value is None:
            _validate_legacy_workflow_entry(entry, workflow_id, index_path)
            continue
        if not isinstance(file_value, str) or not file_value:
            raise ValueError(f"Workflow {workflow_id} has invalid definition file")
        if file_value in seen_files:
            raise ValueError(f"Duplicate workflow definition file in {index_path}: {file_value}")
        seen_files.add(file_value)

        definition_path = _definition_path(index_path, file_value, workflow_id)
        if not definition_path.is_file():
            raise ValueError(f"Workflow {workflow_id} definition is missing: {file_value}")


def _validate_legacy_workflow_entry(entry: dict[str, Any], workflow_id: str, index_path: Path) -> None:
    required = {
        "human_intents",
        "required_inputs",
        "optional_inputs",
        "clarify_if_missing",
        "agent_prompt_template",
        "prerequisite_checks",
        "commands",
        "outputs",
        "validators",
        "risk_level",
        "network_policy",
        "generated_files_policy",
    }
    missing = sorted(required - set(entry))
    if missing:
        raise ValueError(f"Legacy workflow {workflow_id} in {index_path} is missing {missing}")


def _load_definition_for_entry(entry: dict[str, Any], index_path: Path) -> dict[str, Any]:
    file_value = entry.get("file")
    if file_value is None:
        return deepcopy(entry)

    workflow_id = entry["id"]
    definition_path = _definition_path(index_path, file_value, workflow_id)
    definition = _load_yaml_mapping(definition_path)
    if definition.get("id") != workflow_id:
        raise ValueError(
            f"Workflow definition id mismatch for {workflow_id}: {definition_path}"
        )

    for key in ("human_intents", "risk_level"):
        if key in entry and entry[key] != definition.get(key):
            raise ValueError(
                f"Workflow {workflow_id} has mismatched {key} between index and definition"
            )
    return definition


def _definition_path(index_path: Path, file_value: str, workflow_id: str) -> Path:
    relative_path = Path(file_value)
    if relative_path.is_absolute():
        raise ValueError(f"Workflow {workflow_id} definition file must be relative")
    if relative_path.name != f"{workflow_id}.yaml":
        raise ValueError(
            f"Workflow {workflow_id} definition file must be named {workflow_id}.yaml"
        )
    if not relative_path.parts or relative_path.parts[0] != DEFINITIONS_DIR_NAME:
        raise ValueError(
            f"Workflow {workflow_id} definition file must live under {DEFINITIONS_DIR_NAME}/"
        )

    workflows_dir = index_path.parent.resolve()
    definition_path = (index_path.parent / relative_path).resolve()
    if not definition_path.is_relative_to(workflows_dir):
        raise ValueError(f"Workflow {workflow_id} definition file escapes workflows/")
    return definition_path
