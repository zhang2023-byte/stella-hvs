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
from typing import Any, Callable

from .llm_options import apply_llm_request_options

DEFAULT_TIMEOUT_SECONDS = 120
# 5 attempts with 2**attempt backoff rides out ~30s gateway hiccups
# (observed: SSL EOF bursts on TokenDance killed a run at 3 attempts).
DEFAULT_ATTEMPTS = 5
PROVIDER_PARSE_MAX_ATTEMPTS = 2
MAX_ERROR_BODY_BYTES = 32 * 1024
_SENSITIVE_JSON_RE = re.compile(
    r'(?i)("(?:api[_-]?key|authorization|token|access[_-]?token|secret|password)"\s*:\s*)"[^"]*"'
)
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|authorization|access[_-]?token|secret|password)"
    r"(\s*[:=]\s*)([^\s,;&]+)"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")


class LLMTransportError(RuntimeError):
    """Structured, persistable failure from an LLM provider transport."""

    def __init__(
        self,
        message: str,
        *,
        category: str,
        http_status: int | None = None,
        automatic_retryable: bool = False,
        manual_retry_eligible: bool = False,
        provider_request_id: str = "",
        response_body_excerpt: str = "",
        stage: str = "",
        call_id: str = "",
        attempts: int = 1,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.http_status = http_status
        self.automatic_retryable = automatic_retryable
        self.manual_retry_eligible = manual_retry_eligible
        self.provider_request_id = provider_request_id
        self.response_body_excerpt = response_body_excerpt
        self.stage = stage
        self.call_id = call_id
        self.attempts = attempts

    def with_context(self, *, stage: str, call_id: str) -> "LLMTransportError":
        self.stage = stage
        self.call_id = call_id
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "http_status": self.http_status,
            "automatic_retryable": self.automatic_retryable,
            "manual_retry_eligible": self.manual_retry_eligible,
            "provider_request_id": self.provider_request_id,
            "response_body_excerpt": self.response_body_excerpt,
            "stage": self.stage,
            "call_id": self.call_id,
            "attempts": self.attempts,
        }


def _truncate_utf8(value: str, limit: int = MAX_ERROR_BODY_BYTES) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= limit:
        return value
    suffix = "\n[truncated]"
    suffix_bytes = suffix.encode("utf-8")
    return encoded[: limit - len(suffix_bytes)].decode("utf-8", errors="ignore") + suffix


def sanitize_error_body(value: str) -> str:
    redacted = _SENSITIVE_JSON_RE.sub(r'\1"[REDACTED]"', value)
    redacted = _BEARER_RE.sub("Bearer [REDACTED]", redacted)
    redacted = _SENSITIVE_ASSIGNMENT_RE.sub(r"\1\2[REDACTED]", redacted)
    return _truncate_utf8(redacted)


def _read_http_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read(MAX_ERROR_BODY_BYTES + 1)
    except OSError:
        raw = b""
    return sanitize_error_body(raw.decode("utf-8", errors="replace"))


def _provider_request_id(exc: urllib.error.HTTPError) -> str:
    headers = getattr(exc, "headers", None)
    if headers is None:
        return ""
    for name in ("x-request-id", "request-id", "cf-ray"):
        value = headers.get(name)
        if value:
            return str(value)
    return ""


def _http_error_category(status: int, detail: str) -> tuple[str, bool, bool]:
    lower = detail.lower()
    if status == 400 and any(
        marker in lower
        for marker in ("context length", "context_length", "maximum context", "too many tokens")
    ):
        return "context_limit", False, False
    if status == 400 and any(
        marker in lower
        for marker in (
            "error when parsing request",
            "failed to parse request",
            "request parsing failed",
        )
    ):
        # Some OpenAI-compatible gateways return this bare 400 transiently
        # even when the locally serialized JSON request is valid. Retry it
        # only once: repeated failures are more likely a real API mismatch.
        return "provider_parse_error", True, True
    if status == 429:
        return "rate_limit", True, True
    if status == 408:
        return "timeout", True, True
    if status >= 500:
        return "server", True, True
    if status in {401, 403}:
        return "authentication", False, True
    if status in {400, 404, 409, 415, 422}:
        return "invalid_request", False, False
    return "protocol", False, False


def _http_transport_error(
    exc: urllib.error.HTTPError,
    detail: str,
    *,
    attempts: int,
) -> LLMTransportError:
    category, automatic, manual = _http_error_category(exc.code, detail)
    return LLMTransportError(
        f"HTTP {exc.code}: {exc.reason}",
        category=category,
        http_status=exc.code,
        automatic_retryable=automatic,
        manual_retry_eligible=manual,
        provider_request_id=_provider_request_id(exc),
        response_body_excerpt=detail,
        attempts=attempts,
    )


def _exception_transport_error(exc: Exception, *, attempts: int) -> LLMTransportError:
    if isinstance(exc, LLMTransportError):
        exc.attempts = attempts
        return exc
    if isinstance(exc, (TimeoutError, socket.timeout)):
        category = "timeout"
        retryable = True
    elif isinstance(exc, json.JSONDecodeError):
        category = "protocol"
        retryable = False
    else:
        category = "network"
        retryable = True
    return LLMTransportError(
        f"{type(exc).__name__}: {exc}",
        category=category,
        automatic_retryable=retryable,
        manual_retry_eligible=retryable,
        attempts=attempts,
    )


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


StreamEventCallback = Callable[[dict[str, Any]], None]


def build_chat_completion_payload(
    *,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float = 0,
    max_tokens: int | None = None,
    extra_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the exact JSON body sent to a chat-completions endpoint."""

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
    return payload


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
    stream: bool = False,
    on_stream_event: StreamEventCallback | None = None,
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

    effective_extra = dict(extra_body or {})
    if stream:
        effective_extra.update({"stream": True, "stream_options": {"include_usage": True}})
    payload = build_chat_completion_payload(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        extra_body=effective_extra,
    )
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
                if not stream:
                    return json.loads(response.read().decode("utf-8"))
                return _read_chat_completion_stream(
                    response,
                    attempt=attempt,
                    on_event=on_stream_event,
                )
        except urllib.error.HTTPError as exc:
            detail = _read_http_error_body(exc)
            if stream and _streaming_unsupported(exc, detail):
                if on_stream_event is not None:
                    on_stream_event(
                        {
                            "type": "stream.unsupported",
                            "attempt": attempt,
                            "status_code": exc.code,
                        }
                    )
                return chat_completion_raw(
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout_seconds=timeout_seconds,
                    attempts=attempts,
                    extra_body=extra_body,
                    stream=False,
                    on_stream_event=on_stream_event,
                )
            transport_error = _http_transport_error(exc, detail, attempts=attempt)
            if not transport_error.automatic_retryable:
                raise transport_error from exc
            if (
                transport_error.category == "provider_parse_error"
                and attempt >= min(attempts, PROVIDER_PARSE_MAX_ATTEMPTS)
            ):
                raise transport_error from exc
            last_error = transport_error
        # OSError covers URLError, timeouts, and connection resets;
        # HTTPException covers RemoteDisconnected/IncompleteRead raised
        # while the server drops a long-running request mid-response.
        except (OSError, http.client.HTTPException, json.JSONDecodeError) as exc:
            transport_error = _exception_transport_error(exc, attempts=attempt)
            if not transport_error.automatic_retryable:
                raise transport_error from exc
            last_error = transport_error
        if attempt < attempts:
            if on_stream_event is not None:
                on_stream_event(
                    {
                        "type": "retry.scheduled",
                        "attempt": attempt,
                        "next_attempt": attempt + 1,
                        "error_type": type(last_error).__name__,
                        "delay_seconds": 2**attempt,
                    }
                )
            time.sleep(2**attempt)
    if on_stream_event is not None:
        on_stream_event(
            {
                "type": "retry.exhausted",
                "attempt": attempts,
                "error_type": type(last_error).__name__,
            }
        )
    structured = _exception_transport_error(last_error or RuntimeError("unknown transport failure"), attempts=attempts)
    structured.args = (f"LLM call failed after {attempts} attempts: {structured}",)
    raise structured


def _streaming_unsupported(exc: urllib.error.HTTPError, detail: str | None = None) -> bool:
    if exc.code not in {400, 404, 415, 422}:
        return False
    if detail is None:
        detail = _read_http_error_body(exc)
    detail = detail.lower()
    if "stream" not in detail:
        return False
    return any(
        marker in detail
        for marker in (
            "not support",
            "unsupported",
            "does not support",
            "unknown parameter",
            "streaming is disabled",
            "stream not available",
        )
    )


def _append_tool_call(message: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
    calls = message.setdefault("tool_calls", [])
    index = int(delta.get("index") or 0)
    while len(calls) <= index:
        calls.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
    target = calls[index]
    if delta.get("id"):
        target["id"] = str(delta["id"])
    if delta.get("type"):
        target["type"] = str(delta["type"])
    function = delta.get("function") if isinstance(delta.get("function"), dict) else {}
    target_function = target.setdefault("function", {"name": "", "arguments": ""})
    if function.get("name"):
        target_function["name"] += str(function["name"])
    if function.get("arguments"):
        target_function["arguments"] += str(function["arguments"])
    return target


def _stream_lines(
    response: Any,
    *,
    attempt: int,
    on_event: StreamEventCallback | None,
):
    try:
        yield from response
    except (OSError, http.client.HTTPException) as exc:
        if on_event is not None:
            on_event(
                {
                    "type": "stream.interrupted",
                    "attempt": attempt,
                    "error_type": type(exc).__name__,
                }
            )
        raise


def _read_chat_completion_stream(
    response: Any,
    *,
    attempt: int,
    on_event: StreamEventCallback | None,
) -> dict[str, Any]:
    """Reconstruct one OpenAI-compatible response from SSE data lines."""

    document: dict[str, Any] = {
        "id": "",
        "object": "chat.completion",
        "created": 0,
        "model": "",
        "choices": [],
    }
    choices: dict[int, dict[str, Any]] = {}
    saw_delta = False
    saw_terminal = False
    if on_event is not None:
        on_event({"type": "stream.started", "attempt": attempt})
    for raw_line in _stream_lines(response, attempt=attempt, on_event=on_event):
        line = raw_line.decode("utf-8", errors="replace").strip() if isinstance(raw_line, bytes) else str(raw_line).strip()
        if not line or line.startswith(":") or not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            saw_terminal = True
            break
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError as exc:
            if on_event is not None:
                on_event(
                    {
                        "type": "stream.interrupted",
                        "attempt": attempt,
                        "error_type": type(exc).__name__,
                    }
                )
            raise
        for key in ("id", "created", "model", "system_fingerprint"):
            if chunk.get(key) not in (None, ""):
                document[key] = chunk[key]
        if isinstance(chunk.get("usage"), dict):
            document["usage"] = chunk["usage"]
        for raw_choice in chunk.get("choices") or []:
            index = int(raw_choice.get("index") or 0)
            choice = choices.setdefault(
                index,
                {
                    "index": index,
                    "message": {"role": "assistant", "content": ""},
                    "finish_reason": None,
                },
            )
            delta = raw_choice.get("delta") or raw_choice.get("message") or {}
            message = choice["message"]
            if delta.get("role"):
                message["role"] = str(delta["role"])
            for source_key, channel in (("content", "content"), ("reasoning_content", "reasoning"), ("reasoning", "reasoning")):
                value = delta.get(source_key)
                if not isinstance(value, str) or not value:
                    continue
                target_key = "reasoning_content" if channel == "reasoning" else "content"
                message[target_key] = str(message.get(target_key) or "") + value
                saw_delta = True
                if on_event is not None:
                    on_event(
                        {
                            "type": "response.delta",
                            "attempt": attempt,
                            "choice_index": index,
                            "channel": channel,
                            "text": value,
                        }
                    )
            for tool_delta in delta.get("tool_calls") or []:
                target = _append_tool_call(message, tool_delta)
                saw_delta = True
                if on_event is not None:
                    on_event(
                        {
                            "type": "response.delta",
                            "attempt": attempt,
                            "choice_index": index,
                            "channel": "tool_call",
                            "tool_call_index": int(tool_delta.get("index") or 0),
                            "tool_call": target,
                        }
                    )
            if raw_choice.get("finish_reason") is not None:
                choice["finish_reason"] = raw_choice.get("finish_reason")
                saw_terminal = True
        if chunk.get("choices") and not saw_delta:
            saw_delta = True
    if not saw_terminal:
        if on_event is not None:
            on_event(
                {
                    "type": "stream.interrupted",
                    "attempt": attempt,
                    "error_type": "IncompleteRead",
                }
            )
        raise http.client.IncompleteRead(b"")
    document["choices"] = [choices[index] for index in sorted(choices)]
    if on_event is not None:
        on_event(
            {
                "type": "stream.completed",
                "attempt": attempt,
                "model": str(document.get("model") or ""),
                "usage": document.get("usage") or {},
            }
        )
    return document


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
