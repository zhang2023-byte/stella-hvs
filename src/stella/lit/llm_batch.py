"""Reusable helpers for direct-API LLM batch pipelines.

These utilities back the batch driver scripts that call an OpenAI-compatible
chat-completions endpoint directly (no interactive agent runtime): strict
JSON-object response parsing, bounded retries, and deterministic sharding of
a work queue across parallel processes.
"""

from __future__ import annotations

import json
import re
import socket
import time
import urllib.error
import urllib.request
from typing import Any

from .llm_options import apply_llm_request_options

DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_ATTEMPTS = 3


def extract_json_object(content: str) -> dict[str, Any]:
    """Parse one JSON object from an LLM reply, tolerating code fences."""

    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("LLM response was not a JSON object")
    return payload


def shard_items(items: list[Any], *, shard_index: int, shard_count: int) -> list[Any]:
    """Deterministically select this shard's slice of a work queue."""

    if shard_count < 1:
        raise ValueError("shard_count must be at least 1")
    if shard_index < 0 or shard_index >= shard_count:
        raise ValueError("shard_index must be between 0 and shard_count - 1")
    return [item for index, item in enumerate(items) if index % shard_count == shard_index]


def chat_completion_json(
    *,
    api_key: str,
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    temperature: float = 0,
    thinking: str | None = None,
    reasoning_effort: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    attempts: int = DEFAULT_ATTEMPTS,
) -> dict[str, Any]:
    """Call an OpenAI-compatible chat endpoint and parse a JSON-object reply.

    Retries transient network/parse failures with exponential backoff;
    HTTP errors (quota, auth) are raised immediately.
    """

    payload: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "messages": messages,
    }
    apply_llm_request_options(payload, thinking=thinking or None, reasoning_effort=reasoning_effort or None)
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read().decode("utf-8")
            result = json.loads(raw)
            return extract_json_object(result["choices"][0]["message"]["content"])
        except urllib.error.HTTPError:
            raise
        except (TimeoutError, socket.timeout, urllib.error.URLError, json.JSONDecodeError, KeyError, ValueError) as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(2 ** (attempt - 1))
    raise RuntimeError(f"LLM call failed: {type(last_error).__name__}: {last_error}")
