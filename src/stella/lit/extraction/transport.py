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

    Built from the frozen method's model route; the API key is read from
    the ambient credential environment at call time. Tests never
    instantiate this path with a real endpoint.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout: int = 120,
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

    def __call__(self, payload: dict[str, Any], **_: Any) -> dict[str, Any]:
        import urllib.error
        import urllib.request

        self.calls.append(dict(payload))
        request_payload = dict(payload)
        request_payload.setdefault("model", self.model)
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(request_payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise RuntimeError(
                f"provider gateway error {error.code}: {error.read()[:500]!r}"
            ) from error


PROVIDER_BASE_URLS: dict[str, str] = {
    "bigmodel": "https://open.bigmodel.cn/api/paas/v4",
    "openai": "https://api.openai.com/v1",
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
    api_key = source.get(PROVIDER_API_KEY_ENV) or source.get("OPENAI_API_KEY", "")
    route = _method_route(config)
    return ProviderTransport(
        api_key=api_key,
        base_url=str(route.get("base_url") or DEFAULT_BASE_URL),
        model=str(route.get("model") or "glm-4.6"),
    )
