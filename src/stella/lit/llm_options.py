"""Shared LLM request option helpers."""

from __future__ import annotations

import json
import os
from typing import Any


def _first_configured_value(explicit: str | None, env_keys: tuple[str, ...]) -> str | None:
    if explicit is not None:
        return explicit
    for key in env_keys:
        value = os.environ.get(key)
        if value:
            return value
    return None


def resolve_llm_thinking(explicit: str | None = None) -> dict[str, Any] | None:
    value = _first_configured_value(explicit, ("LLM_THINKING", "DEEPSEEK_THINKING"))
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    lowered = normalized.lower()
    if lowered in {"none", "null", "default"}:
        return None
    if lowered in {"true", "t", "1", "yes", "y", "on", "enabled", "enable"}:
        return {"type": "enabled"}
    if lowered in {"false", "f", "0", "no", "n", "off", "disabled", "disable"}:
        return {"type": "disabled"}
    if normalized.startswith("{"):
        parsed = json.loads(normalized)
        if not isinstance(parsed, dict):
            raise ValueError("LLM_THINKING JSON must be an object")
        return parsed
    return {"type": normalized}


def resolve_llm_reasoning_effort(explicit: str | None = None) -> str | None:
    value = _first_configured_value(explicit, ("LLM_REASONING_EFFORT", "DEEPSEEK_REASONING_EFFORT"))
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def apply_llm_request_options(
    payload: dict[str, Any],
    *,
    thinking: str | None = None,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    resolved_thinking = resolve_llm_thinking(thinking)
    if resolved_thinking is not None:
        payload["thinking"] = resolved_thinking
    resolved_effort = resolve_llm_reasoning_effort(reasoning_effort)
    if resolved_effort is not None:
        payload["reasoning_effort"] = resolved_effort
    return payload
