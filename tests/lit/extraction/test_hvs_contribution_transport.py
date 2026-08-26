"""Production provider transport construction and call-contract tests.

No real network: ``chat_completion_raw`` is patched so the tests observe
exactly what the production transport would send. Placeholder credential
values come from ``mock.sentinel`` so no secret-looking literal exists in
source.
"""

from __future__ import annotations

import unittest
from unittest import mock

from stella.lit.extraction.method_config import HvsContributionMethodConfig
from stella.lit.extraction.transport import (
    PROVIDER_API_KEY_ENV,
    PROVIDER_BASE_URLS,
    ProviderTransport,
    build_transport,
)

GATEWAY_KEY = str(mock.sentinel.gateway_credential)
CONSTRUCTOR_KEY = str(mock.sentinel.constructor_credential)


def _config(provider: str, model: str) -> HvsContributionMethodConfig:
    return HvsContributionMethodConfig.model_validate(
        {
            "roster_model": {
                "provider": provider,
                "model": model,
                "structured_output_mode": "tool_submission",
            },
            "quantity_model": {
                "provider": provider,
                "model": model,
                "structured_output_mode": "tool_submission",
            },
        }
    )


class ProviderBaseURLTest(unittest.TestCase):
    def test_deepseek_routes_pin_the_tokendance_gateway(self) -> None:
        self.assertEqual(
            PROVIDER_BASE_URLS["deepseek"], "https://tokendance.space/gateway/v1"
        )

    def test_transport_uses_the_pinned_provider_base_url(self) -> None:
        transport = build_transport(
            _config("deepseek", "deepseek-v4-flash-0731"),
            env={PROVIDER_API_KEY_ENV: GATEWAY_KEY},
        )
        self.assertIsInstance(transport, ProviderTransport)
        self.assertEqual(
            transport.base_url, "https://tokendance.space/gateway/v1"
        )
        self.assertEqual(transport.model, "deepseek-v4-flash-0731")


class BuildTransportKeyTest(unittest.TestCase):
    def test_key_falls_back_to_the_ambient_gateway_credential(self) -> None:
        transport = build_transport(
            _config("deepseek", "deepseek-v4-flash-0731"),
            env={"LLM_API_KEY": GATEWAY_KEY},
        )
        self.assertEqual(transport.api_key, GATEWAY_KEY)

    def test_missing_key_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            build_transport(
                _config("deepseek", "deepseek-v4-flash-0731"),
                env={},
            )


class ProviderTransportCallTest(unittest.TestCase):
    def _transport(self) -> ProviderTransport:
        return ProviderTransport(
            api_key=CONSTRUCTOR_KEY,
            base_url="https://tokendance.space/gateway/v1",
            model="deepseek-v4-flash-0731",
        )

    def test_call_forwards_the_route_kwargs_to_the_raw_client(self) -> None:
        transport = self._transport()
        with mock.patch(
            "stella.lit.llm_batch.chat_completion_raw",
            return_value={"choices": []},
        ) as raw:
            transport(
                api_key="",
                base_url="",
                model="deepseek-v4-flash-0731",
                messages=[{"role": "user", "content": "x"}],
                temperature=0.0,
                max_tokens=16000,
                timeout_seconds=1800,
                attempts=1,
                extra_body={
                    "tools": [{"type": "function"}],
                    "reasoning_effort": "max",
                },
                stream=True,
            )
        raw.assert_called_once_with(
            api_key=CONSTRUCTOR_KEY,
            base_url="https://tokendance.space/gateway/v1",
            model="deepseek-v4-flash-0731",
            messages=[{"role": "user", "content": "x"}],
            temperature=0.0,
            max_tokens=16000,
            timeout_seconds=1800,
            attempts=1,
            extra_body={"tools": [{"type": "function"}], "reasoning_effort": "max"},
            stream=True,
        )

    def test_call_rejects_missing_key_at_construction(self) -> None:
        with self.assertRaises(ValueError):
            ProviderTransport(
                api_key="",
                base_url="https://tokendance.space/gateway/v1",
                model="deepseek-v4-flash-0731",
            )


if __name__ == "__main__":
    unittest.main()
