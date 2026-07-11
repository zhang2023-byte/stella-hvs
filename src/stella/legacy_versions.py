"""Explicit, read-only adapters for archived pre-0.2 Stella artifacts."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from stella.schema_registry import LEGACY_ALIASES, schema_ref


def normalize_legacy_schema(payload: Any) -> dict[str, Any]:
    """Return an in-memory structured-envelope copy of one legacy artifact."""

    if not isinstance(payload, dict):
        raise ValueError("legacy artifact must be a JSON object")
    legacy = payload.get("schema_version")
    if not isinstance(legacy, str) or legacy not in LEGACY_ALIASES:
        raise ValueError(f"unsupported legacy schema: {legacy!r}")
    name, version = LEGACY_ALIASES[legacy]
    normalized = deepcopy(payload)
    normalized.pop("schema_version", None)
    normalized["schema"] = schema_ref(name, version)
    return normalized


def legacy_identity(payload: Any) -> tuple[str, int]:
    if not isinstance(payload, dict):
        raise ValueError("legacy artifact must be a JSON object")
    legacy = payload.get("schema_version")
    if not isinstance(legacy, str) or legacy not in LEGACY_ALIASES:
        raise ValueError(f"unsupported legacy schema: {legacy!r}")
    return LEGACY_ALIASES[legacy]
