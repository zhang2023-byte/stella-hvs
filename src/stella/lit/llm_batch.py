"""Reusable helpers for direct-API LLM batch pipelines.

These utilities back the batch driver scripts that call an OpenAI-compatible
chat-completions endpoint directly (no interactive agent runtime): strict
JSON-object response parsing, bounded retries, and deterministic sharding of
a work queue across parallel processes.
"""

from __future__ import annotations

import http.client
import json
import re
import socket
import time
import urllib.error
import urllib.request
from typing import Any

from .llm_options import apply_llm_request_options

DEFAULT_TIMEOUT_SECONDS = 120
# 5 attempts with 2**attempt backoff rides out ~30s gateway hiccups
# (observed: SSL EOF bursts on TokenDance killed a run at 3 attempts).
DEFAULT_ATTEMPTS = 5


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


RETRYABLE_HTTP_STATUS = (429, 500, 502, 503, 504)


def chat_completion_raw(
    *,
    api_key: str,
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    temperature: float = 0,
    max_tokens: int | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    attempts: int = DEFAULT_ATTEMPTS,
    extra_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call an OpenAI-compatible chat endpoint and return the full response.

    Unlike :func:`chat_completion_json`, the caller gets the complete
    response document (served model id, usage, reasoning fields) — the
    benchmark pipeline archives it as run provenance. Rate-limit and
    server errors (429/5xx) are retried with exponential backoff; other
    HTTP errors (auth, bad request) are raised immediately.

    ``extra_body`` merges additional top-level request fields, e.g. the
    TokenDance gateway's ``provider`` routing preferences and ``models``
    fallback list; it cannot override the explicit parameters above.
    """

    payload: dict[str, Any] = dict(extra_body or {})
    payload.update(
        {
            "model": model,
            "temperature": temperature,
            "messages": messages,
        }
    )
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    body = json.dumps(payload).encode("utf-8")
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            f"{base_url.rstrip('/')}/chat/completions",
            data=body,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRYABLE_HTTP_STATUS:
                raise
            last_error = exc
        # OSError covers URLError, timeouts, and connection resets;
        # HTTPException covers RemoteDisconnected/IncompleteRead raised
        # while the server drops a long-running request mid-response.
        except (OSError, http.client.HTTPException, json.JSONDecodeError) as exc:
            last_error = exc
        if attempt < attempts:
            time.sleep(2**attempt)
    raise RuntimeError(
        f"LLM call failed after {attempts} attempts: "
        f"{type(last_error).__name__}: {last_error}"
    )


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
