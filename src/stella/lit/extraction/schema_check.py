"""Strict schema validation for contribution documents and artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from stella.lit.hvs_contribution_models import (
    LiteratureHvsContributionsRecord,
    validate_literature_hvs_contributions_document,
)
from stella.schema_registry import require_schema


def validate_contribution_document(payload: Any) -> LiteratureHvsContributionsRecord:
    """Validate a literature_hvs_contributions document through the registry."""

    return validate_literature_hvs_contributions_document(payload)


def validate_contribution_document_file(path: Path) -> LiteratureHvsContributionsRecord:
    import json

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate_contribution_document(payload)


def validate_transient_artifact(
    payload: Any, expected_name: str
) -> tuple[str, int]:
    """Validate one hvs_contribution_extraction transient artifact reference."""

    return require_schema(payload, expected_name)


from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SchemaIssue:
    path: str
    message: str

    def render(self) -> str:
        return f"{self.path}: {self.message}"


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _collect(value: Any, schema: dict[str, Any], path: str, issues: list[SchemaIssue]) -> None:
    if not isinstance(schema, dict):
        return
    if "oneOf" in schema or "anyOf" in schema:
        key = "oneOf" if "oneOf" in schema else "anyOf"
        branches = schema[key]
        matched = 0
        branch_issues: list[SchemaIssue] = []
        for branch in branches:
            probe: list[SchemaIssue] = []
            _collect(value, branch, path, probe)
            if not probe:
                matched += 1
            branch_issues.extend(probe)
        if key == "oneOf" and matched != 1:
            issues.append(
                SchemaIssue(path, f"must match exactly one {key} branch; matched {matched}")
            )
            issues.extend(branch_issues)
        if key == "anyOf" and matched == 0:
            issues.append(SchemaIssue(path, f"does not match any {key} branch"))
            issues.extend(branch_issues)
        return
    if "const" in schema and value != schema["const"]:
        issues.append(SchemaIssue(path, f"must equal {schema['const']!r}"))
        return
    if "enum" in schema and value not in schema["enum"]:
        issues.append(SchemaIssue(path, f"value {value!r} is outside the allowed enum"))
        return
    expected = schema.get("type")
    if expected is not None:
        type_ok = {
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
            "string": isinstance(value, str),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
            "null": value is None,
        }[expected]
        if not type_ok:
            issues.append(
                SchemaIssue(path, f"must have JSON type {expected}, got {_json_type(value)}")
            )
            return
    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        for key in schema.get("required") or []:
            if key not in value:
                issues.append(SchemaIssue(path, f"missing required property {key!r}"))
        if schema.get("additionalProperties") is False:
            for key in sorted(set(value) - set(properties)):
                issues.append(SchemaIssue(path, f"unexpected property {key!r}"))
        for key, item in value.items():
            child = properties.get(key)
            if isinstance(child, dict):
                _collect(item, child, f"{path}.{key}", issues)
    elif isinstance(value, list):
        min_items = schema.get("minItems")
        if isinstance(min_items, int) and len(value) < min_items:
            issues.append(
                SchemaIssue(path, f"must contain at least {min_items} item(s), got {len(value)}")
            )
        max_items = schema.get("maxItems")
        if isinstance(max_items, int) and len(value) > max_items:
            issues.append(
                SchemaIssue(path, f"must contain at most {max_items} item(s), got {len(value)}")
            )
        items = schema.get("items")
        if isinstance(items, dict):
            for index, item in enumerate(value):
                _collect(item, items, f"{path}[{index}]", issues)
    elif isinstance(value, str):
        min_length = schema.get("minLength")
        if isinstance(min_length, int) and len(value) < min_length:
            issues.append(
                SchemaIssue(path, f"string must have length >= {min_length}")
            )
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        if isinstance(minimum, (int, float)) and value < minimum:
            issues.append(SchemaIssue(path, f"must be >= {minimum}"))


def collect_schema_errors(payload: Any, schema: dict[str, Any]) -> list[SchemaIssue]:
    """Return every schema violation with an exact JSON path."""

    issues: list[SchemaIssue] = []
    _collect(payload, schema, "$", issues)
    return issues
