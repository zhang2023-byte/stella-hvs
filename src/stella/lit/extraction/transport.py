"""Provider transport construction for contribution extraction.

The production transport is a real provider gateway client built from the
frozen method configuration; credentials come from the ambient key
environment, never from the scientific request. Scripted replay is an
explicit test injection (a session file or worker transcript), never the
only execution mechanism.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from stella.lit.extraction.method_config import HvsContributionMethodConfig

Transport = Callable[..., dict[str, Any]]

PROVIDER_API_KEY_ENV = "STELLA_PROVIDER_API_KEY"
DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"


class TransportExhausted(RuntimeError):
    """A scripted transport ran out of responses."""


class ScriptedTransport:
    """Replay canned provider tool responses in call order (tests only)."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = [
            scripted_tool_response(item["tool_name"], item.get("arguments", {}))
            for item in responses
        ]
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if not self._responses:
            raise TransportExhausted("scripted transport exhausted")
        return self._responses.pop(0)


def scripted_tool_response(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_scripted",
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(arguments, ensure_ascii=False),
                            },
                        },
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }


class ProviderTransport:
    """Production provider gateway client (real network calls).

    Thin binding of the maintained raw chat transport
    (:func:`stella.lit.llm_batch.chat_completion_raw`) to one frozen route.
    Per-call kwargs follow the route contract produced by the roster and
    quantity stages (``messages``, ``model``, ``temperature``,
    ``max_tokens``, ``timeout_seconds``, ``attempts``, ``extra_body``,
    ``stream``); streaming aggregates server-sent events into one complete
    response document, and failures raise ``LLMTransportError`` so the
    bounded caller classifies retries. Tests never instantiate this path
    with a real endpoint.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout: int = 600,
    ) -> None:
        if not api_key:
            raise ValueError(
                f"{PROVIDER_API_KEY_ENV} must be set for the production transport"
            )
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        from stella.lit.llm_batch import chat_completion_raw

        self.calls.append(
            {
                key: kwargs.get(key)
                for key in (
                    "model",
                    "temperature",
                    "max_tokens",
                    "stream",
                    "extra_body",
                )
            }
        )
        temperature = kwargs.get("temperature")
        return chat_completion_raw(
            api_key=str(kwargs.get("api_key") or self.api_key),
            base_url=str(kwargs.get("base_url") or self.base_url),
            model=str(kwargs.get("model") or self.model),
            messages=list(kwargs.get("messages") or []),
            temperature=0.0 if temperature is None else float(temperature),
            max_tokens=kwargs.get("max_tokens"),
            timeout_seconds=int(kwargs.get("timeout_seconds") or self.timeout),
            attempts=max(1, int(kwargs.get("attempts") or 1)),
            extra_body=dict(kwargs.get("extra_body") or {}),
            stream=bool(kwargs.get("stream")),
        )


PROVIDER_BASE_URLS: dict[str, str] = {
    "bigmodel": "https://open.bigmodel.cn/api/paas/v4",
    "openai": "https://api.openai.com/v1",
    # The DeepSeek V4 roster ids (deepseek-v4-pro, deepseek-v4-flash-0731,
    # ...) are TokenDance gateway models; the first-party DeepSeek API does
    # not serve them. This is the pinned V6-lineage route: no fallback.
    "deepseek": "https://tokendance.space/gateway/v1",
}


def _method_route(config: HvsContributionMethodConfig | None) -> dict[str, Any]:
    if config is None:
        return {}
    route = getattr(config, "roster_model", None)
    model = getattr(route, "model", None) if route is not None else None
    provider = getattr(route, "provider", None) if route is not None else None
    base_url = PROVIDER_BASE_URLS.get(str(provider or ""), DEFAULT_BASE_URL)
    return {"model": model, "base_url": base_url}


def build_transport(
    config: HvsContributionMethodConfig | None,
    *,
    session_model_responses: list[dict[str, Any]] | None = None,
    transcript_path: str | None = None,
    env: dict[str, str] | None = None,
) -> Transport:
    """Build the transport for one worker run.

    Order: explicit session responses (test injection), an explicit
    transcript file (test injection), then the production provider
    transport from the frozen method configuration.
    """

    if session_model_responses is not None:
        # An explicitly declared (even empty) response list is a scripted
        # session: exhaustion models a quota failure in tests.
        return ScriptedTransport(session_model_responses)
    if transcript_path:
        path = Path(transcript_path)
        transcript = json.loads(path.read_text(encoding="utf-8"))
        return ScriptedTransport(transcript.get("responses", []))
    source = env if env is not None else os.environ
    api_key = (
        source.get(PROVIDER_API_KEY_ENV)
        or source.get("OPENAI_API_KEY", "")
        or source.get("LLM_API_KEY", "")
    )
    route = _method_route(config)
    return ProviderTransport(
        api_key=api_key,
        base_url=str(route.get("base_url") or DEFAULT_BASE_URL),
        model=str(route.get("model") or "glm-4.6"),
    )
