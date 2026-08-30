"""Frozen, provider-compatible structured-output contracts.

The benchmark resolves one exact model/provider/mode before creating a run.
Calls then consume that immutable contract: they never probe, downgrade, or
switch response modes while a run is in progress.
"""

from __future__ import annotations

import copy
import json
from typing import Any


TOOL_SUBMISSION = "tool_submission"
JSON_OBJECT = "json_object"
STRICT_JSON_SCHEMA = "strict_json_schema"
STRUCTURED_OUTPUT_MODES = (TOOL_SUBMISSION, JSON_OBJECT, STRICT_JSON_SCHEMA)

_ROUTE_CAPABILITIES: dict[tuple[str, str], dict[str, dict[str, Any]]] = {
    # 2026-08-30 TokenDance probes passed unforced typed-tool submission for
    # both streaming roster and non-streaming quantity request shapes.
    ("qwen3.8-flash", "alibaba"): {
        TOOL_SUBMISSION: {},
    },
    ("deepseek-v4-pro-0813", "deepseek"): {
        TOOL_SUBMISSION: {},
        JSON_OBJECT: {},
    },
    ("deepseek-v4-pro", "deepseek"): {
        # This exact route rejects forced tool_choice while thinking mode is
        # enabled.  The override is therefore part of the declared mode, not a
        # runtime fallback.
        TOOL_SUBMISSION: {"thinking": {"type": "disabled"}},
        JSON_OBJECT: {},
    },
    ("glm-5.2", "bigmodel"): {
        TOOL_SUBMISSION: {},
        JSON_OBJECT: {},
        STRICT_JSON_SCHEMA: {},
    },
    ("glm-5.3-flash", "bigmodel"): {
        TOOL_SUBMISSION: {},
    },
    ("deepseek-v4-flash-0731", "deepseek"): {
        TOOL_SUBMISSION: {},
    },
}

# These gateway routes can submit a typed tool while thinking is active, but
# must not receive a forced ``tool_choice``. The local parser still requires
# exactly one matching call; missing calls enter the bounded format correction
# path instead of silently changing response modes.
_UNFORCED_TOOL_SUBMISSION_ROUTES = frozenset(
    {
        ("qwen3.8-flash", "alibaba"),
        ("deepseek-v4-flash-0731", "deepseek"),
        ("deepseek-v4-pro-0813", "deepseek"),
        ("glm-5.3-flash", "bigmodel"),
    }
)


class StructuredOutputError(ValueError):
    """A provider response did not satisfy the frozen submission contract."""


def _exact_provider(provider: dict[str, Any]) -> str:
    if not isinstance(provider, dict) or set(provider) != {"only"}:
        raise ValueError("structured output requires provider.only with one exact route")
    only = provider.get("only")
    if not isinstance(only, list) or len(only) != 1 or not str(only[0]).strip():
        raise ValueError("structured output requires exactly one provider.only route")
    return str(only[0])


def resolve_structured_output_contract(
    *, model: str, provider: dict[str, Any], mode: str
) -> dict[str, Any]:
    """Resolve one declared route/mode or fail before run initialization."""

    route = _exact_provider(provider)
    capabilities = _ROUTE_CAPABILITIES.get((model, route))
    if capabilities is None:
        raise ValueError(
            f"undeclared structured-output route: model={model!r}, provider={route!r}"
        )
    if mode not in capabilities:
        raise ValueError(
            f"structured-output route {model}/{route} does not support mode {mode!r}"
        )
    contract = {
        "mode": mode,
        "model": model,
        "provider": route,
        "request_overrides": copy.deepcopy(capabilities[mode]),
    }
    if mode == TOOL_SUBMISSION and (model, route) in _UNFORCED_TOOL_SUBMISSION_ROUTES:
        contract["force_tool_choice"] = False
    return contract


def require_structured_output_contract(
    contract: dict[str, Any], *, model: str, provider: dict[str, Any]
) -> dict[str, Any]:
    """Re-resolve frozen data and reject mutation or undeclared fallback."""

    if not isinstance(contract, dict):
        raise ValueError("structured-output contract must be an object")
    expected = resolve_structured_output_contract(
        model=model,
        provider=provider,
        mode=str(contract.get("mode") or ""),
    )
    if contract != expected:
        raise ValueError("structured-output contract does not match the declared route")
    return expected


def apply_structured_output_request(
    base: dict[str, Any],
    *,
    contract: dict[str, Any],
    schema: dict[str, Any],
    tool_name: str,
) -> dict[str, Any]:
    """Compose one request without overriding an existing structured mode."""

    extra = copy.deepcopy(base)
    conflicts = sorted(set(extra) & {"tools", "tool_choice", "response_format", "thinking"})
    if conflicts:
        raise ValueError(
            "structured-output request conflicts with frozen fields: "
            + ", ".join(conflicts)
        )
    extra.update(copy.deepcopy(contract.get("request_overrides") or {}))
    mode = contract.get("mode")
    if mode == TOOL_SUBMISSION:
        extra["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": "Submit the complete typed Stella output.",
                    "parameters": copy.deepcopy(schema),
                },
            }
        ]
        if contract.get("force_tool_choice", True):
            extra["tool_choice"] = {
                "type": "function",
                "function": {"name": tool_name},
            }
    elif mode == JSON_OBJECT:
        extra["response_format"] = {"type": "json_object"}
    elif mode == STRICT_JSON_SCHEMA:
        extra["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": tool_name,
                "strict": True,
                "schema": copy.deepcopy(schema),
            },
        }
    else:
        raise ValueError(f"unknown structured-output mode {mode!r}")
    return extra


def _resolve_ref(root: dict[str, Any], ref: str) -> dict[str, Any]:
    if not ref.startswith("#/"):
        raise StructuredOutputError(f"unsupported schema reference {ref!r}")
    value: Any = root
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or part not in value:
            raise StructuredOutputError(f"unresolved schema reference {ref!r}")
        value = value[part]
    if not isinstance(value, dict):
        raise StructuredOutputError(f"schema reference {ref!r} is not an object")
    return value


def _validate_schema(value: Any, schema: dict[str, Any], root: dict[str, Any], path: str) -> None:
    if "$ref" in schema:
        _validate_schema(value, _resolve_ref(root, str(schema["$ref"])), root, path)
        return
    if "oneOf" in schema:
        matches = 0
        for option in schema["oneOf"]:
            try:
                _validate_schema(value, option, root, path)
            except StructuredOutputError:
                continue
            matches += 1
        if matches != 1:
            raise StructuredOutputError(f"{path} must match exactly one schema branch")
        return
    if "anyOf" in schema:
        for option in schema["anyOf"]:
            try:
                _validate_schema(value, option, root, path)
                return
            except StructuredOutputError:
                continue
        raise StructuredOutputError(f"{path} does not match any schema branch")
    if "const" in schema and value != schema["const"]:
        raise StructuredOutputError(f"{path} must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise StructuredOutputError(f"{path} is outside the allowed enum")
    expected = schema.get("type")
    valid_type = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(expected, True)
    if not valid_type:
        raise StructuredOutputError(f"{path} must have JSON type {expected}")
    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        required = schema.get("required") or []
        missing = [key for key in required if key not in value]
        if missing:
            raise StructuredOutputError(f"{path} is missing required keys: {missing}")
        if schema.get("additionalProperties") is False:
            extras = sorted(set(value) - set(properties))
            if extras:
                raise StructuredOutputError(f"{path} has unexpected keys: {extras}")
        for key, item in value.items():
            child = properties.get(key)
            if isinstance(child, dict):
                _validate_schema(item, child, root, f"{path}.{key}")
    elif isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            _validate_schema(item, schema["items"], root, f"{path}[{index}]")


def validate_typed_payload(payload: Any, schema: dict[str, Any]) -> dict[str, Any]:
    _validate_schema(payload, schema, schema, "$")
    if not isinstance(payload, dict):
        raise StructuredOutputError("structured output must be a JSON object")
    return payload


def parse_structured_output(
    response: dict[str, Any],
    *,
    mode: str,
    schema: dict[str, Any],
    tool_name: str,
) -> dict[str, Any]:
    """Parse without fences, substring extraction, or tool-call guessing."""

    choice = (response.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    if mode == TOOL_SUBMISSION:
        calls = message.get("tool_calls") or []
        if len(calls) != 1:
            raise StructuredOutputError(
                f"expected exactly one {tool_name} tool call, got {len(calls)}"
            )
        function = calls[0].get("function") or {}
        if function.get("name") != tool_name:
            raise StructuredOutputError(
                f"expected tool {tool_name!r}, got {function.get('name')!r}"
            )
        raw = function.get("arguments")
        if not isinstance(raw, str):
            raise StructuredOutputError("tool arguments must be a JSON string")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise StructuredOutputError(f"malformed tool arguments: {exc}") from exc
    elif mode in {JSON_OBJECT, STRICT_JSON_SCHEMA}:
        if message.get("tool_calls"):
            raise StructuredOutputError("content mode must not return tool calls")
        raw = message.get("content")
        if not isinstance(raw, str):
            raise StructuredOutputError("structured response content is missing")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise StructuredOutputError(f"malformed JSON content: {exc}") from exc
    else:
        raise StructuredOutputError(f"unknown structured-output mode {mode!r}")
    return validate_typed_payload(payload, schema)


def synthetic_long_context(minimum_chars: int = 120_000) -> str:
    """Return content-free repeated text for capability probes."""

    token = "SYNTHETIC-CONTEXT "
    return token * ((max(0, minimum_chars) + len(token) - 1) // len(token))


def review_payload_json_schema() -> dict[str, Any]:
    """Typed schema shared by workflow and agentic review submission."""

    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "challenges": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "candidate_index": {"type": "integer"},
                        "field": {"type": "string"},
                        "issue": {"type": "string"},
                        "severity": {"type": "string", "enum": ["high", "low"]},
                    },
                    "required": ["candidate_index", "field", "issue", "severity"],
                },
            },
            "summary": {"type": "string"},
        },
        "required": ["challenges", "summary"],
    }


def generation_payload_json_schema(stage: str, task_surface: str) -> dict[str, Any]:
    """Typed stage envelopes; existing stage/final validators own semantics."""

    del task_surface
    if stage == "scaffold":
        return {
            "type": "object",
            "properties": {
                "extraction": {"type": "object"},
                "method_chain": {"type": "array", "items": {"type": "object"}},
                "candidates": {"type": "array", "items": {"type": "object"}},
                "candidate_groups_considered": {
                    "type": "array",
                    "items": {"type": "object"},
                },
            },
            "required": [
                "extraction",
                "method_chain",
                "candidates",
                "candidate_groups_considered",
            ],
        }
    if stage == "batch":
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "candidates": {
                    "type": "array",
                    "items": {"type": "object"},
                }
            },
            "required": ["candidates"],
        }
    raise ValueError(f"unknown generation stage {stage!r}")
