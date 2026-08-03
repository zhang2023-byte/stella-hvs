from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from stella.benchmark.pricing import (
    build_pricing_snapshot,
    estimate_api_cost,
    load_pricing_snapshot,
    validate_pricing_snapshot,
)


def payload() -> dict:
    return {
        "snapshot_id": "tokendance-2026-08-03-screenshots-v1",
        "source": {
            "name": "TokenDance",
            "url": "https://tokendance.space/models/glm-5.2",
            "captured_at": "2026-08-03T12:00:00+00:00",
            "effective_at": None,
        },
        "currency": "CNY",
        "routes": [
            {
                "provider": "bigmodel",
                "model": "glm-5.2",
                "source_route": {
                    "model_slug": "glm-5.2",
                    "provider_slug": "bigmodel",
                    "price_id": "standard",
                },
                "rates_cny_per_million_tokens": {
                    "uncached_input": "2",
                    "cached_input": "1",
                    "output": "4",
                },
                "cached_input_basis": "listed",
            },
            {
                "provider": "deepseek",
                "model": "deepseek-v4-pro",
                "source_route": {
                    "model_slug": "deepseek-v4-pro",
                    "provider_slug": "deepseek",
                    "price_id": "standard",
                },
                "rates_cny_per_million_tokens": {
                    "uncached_input": "1",
                    "cached_input": "1",
                    "output": "3",
                },
                "cached_input_basis": "same_as_input",
            },
        ],
    }


class BenchmarkPricingTest(unittest.TestCase):
    def test_live_snapshot_covers_current_default_routes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        snapshot = load_pricing_snapshot(
            root
            / "benchmark"
            / "pricing"
            / "tokendance"
            / "tokendance-2026-08-03-screenshots-v1.json"
        )
        routes = {
            (route["provider"], route["model"]): route
            for route in snapshot["routes"]
        }

        self.assertEqual(len(routes), 8)
        self.assertIn(("bigmodel", "glm-5.2"), routes)
        self.assertIn(("deepseek", "deepseek-v4-pro"), routes)
        self.assertEqual(
            routes[("bigmodel", "glm-5.2")][
                "rates_cny_per_million_tokens"
            ],
            {
                "uncached_input": "6.4",
                "cached_input": "1.6",
                "output": "22.4",
            },
        )
        self.assertEqual(
            routes[("deepseek", "deepseek-v4-pro")][
                "rates_cny_per_million_tokens"
            ],
            {
                "uncached_input": "3",
                "cached_input": "0.025",
                "output": "6",
            },
        )
        self.assertTrue(
            all(route["cached_input_basis"] == "listed" for route in routes.values())
        )
        self.assertEqual(
            [(route["provider"], route["model"]) for route in snapshot["deferred_routes"]],
            [("minimax", "minimax-m3")],
        )

    def test_deferred_tiered_route_is_validated_but_never_counts_as_coverage(self) -> None:
        deferred = payload()
        deferred["deferred_routes"] = [
            {
                "provider": "minimax",
                "model": "minimax-m3",
                "source_route": {
                    "model_slug": "minimax-m3",
                    "provider_slug": "特工宇宙",
                    "price_id": "OpenAI Completions",
                },
                "reason": "per_request_prompt_threshold",
                "context_limit_tokens": 1_000_000,
                "tiers": [
                    {
                        "prompt_tokens_min": 0,
                        "prompt_tokens_max": 512_000,
                        "rates_cny_per_million_tokens": {
                            "uncached_input": "2.1",
                            "cached_input": "0.42",
                            "output": "8.4",
                        },
                    },
                    {
                        "prompt_tokens_min": 512_001,
                        "prompt_tokens_max": 1_000_000,
                        "rates_cny_per_million_tokens": {
                            "uncached_input": "4.2",
                            "cached_input": "0.84",
                            "output": "16.8",
                        },
                    },
                ],
            }
        ]
        snapshot = build_pricing_snapshot(deferred)
        config = {
            "method": {
                "roster_model": {"provider": "minimax", "model": "minimax-m3"},
                "core_field_model": {
                    "provider": "deepseek",
                    "model": "deepseek-v4-pro",
                },
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pricing.json"
            path.write_text(json.dumps(snapshot), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not cover.*minimax/minimax-m3"):
                estimate_api_cost(
                    snapshot=snapshot,
                    snapshot_path=path,
                    run_config=config,
                    usage={"by_role": {}},
                )

        broken = copy.deepcopy(deferred)
        broken["deferred_routes"][0]["tiers"][1]["prompt_tokens_min"] = 512_002
        with self.assertRaisesRegex(ValueError, "contiguous"):
            build_pricing_snapshot(broken)

    def test_rejects_invalid_rates_routes_and_currency(self) -> None:
        cases = []
        wrong_currency = payload()
        wrong_currency["currency"] = "USD"
        cases.append(wrong_currency)
        float_rate = payload()
        float_rate["routes"][0]["rates_cny_per_million_tokens"]["output"] = 4.0
        cases.append(float_rate)
        range_rate = payload()
        range_rate["routes"][0]["rates_cny_per_million_tokens"]["output"] = "2~4"
        cases.append(range_rate)
        negative_rate = payload()
        negative_rate["routes"][0]["rates_cny_per_million_tokens"]["output"] = "-1"
        cases.append(negative_rate)
        duplicate = payload()
        duplicate["routes"].append(copy.deepcopy(duplicate["routes"][0]))
        cases.append(duplicate)
        incomplete_source_route = payload()
        del incomplete_source_route["routes"][0]["source_route"]["price_id"]
        cases.append(incomplete_source_route)
        for broken in cases:
            with self.subTest(broken=broken):
                with self.assertRaises(ValueError):
                    build_pricing_snapshot(broken)

    def test_tampered_snapshot_content_hash_fails_closed(self) -> None:
        snapshot = build_pricing_snapshot(payload())
        snapshot["routes"][0]["rates_cny_per_million_tokens"]["output"] = "99"
        with self.assertRaisesRegex(ValueError, "content hash mismatch"):
            validate_pricing_snapshot(snapshot)

    def test_estimates_cached_uncached_and_output_by_role(self) -> None:
        snapshot = build_pricing_snapshot(payload())
        run_config = {
            "method": {
                "roster_model": {"provider": "bigmodel", "model": "glm-5.2"},
                "core_field_model": {
                    "provider": "deepseek",
                    "model": "deepseek-v4-pro",
                },
            }
        }
        usage = {
            "by_role": {
                "roster": {
                    "uncached_input_tokens": 500_000,
                    "cached_input_tokens": 500_000,
                    "completion_tokens": 250_000,
                    "telemetry_status": "complete",
                },
                "core_fields": {
                    "uncached_input_tokens": 1_000_000,
                    "cached_input_tokens": 0,
                    "completion_tokens": 1_000_000,
                    "telemetry_status": "complete",
                },
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pricing.json"
            path.write_text(json.dumps(snapshot), encoding="utf-8")
            result = estimate_api_cost(
                snapshot=snapshot,
                snapshot_path=path,
                run_config=run_config,
                usage=usage,
            )
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["by_role"]["roster"]["amount_cny"], "2.500000")
        self.assertEqual(result["by_role"]["core_fields"]["amount_cny"], "4.000000")
        self.assertEqual(result["total_cny"], "6.500000")

    def test_missing_route_fails_and_missing_usage_is_not_zero(self) -> None:
        snapshot = build_pricing_snapshot(payload())
        config = {
            "method": {
                "roster_model": {"provider": "other", "model": "unknown"},
                "core_field_model": {
                    "provider": "deepseek",
                    "model": "deepseek-v4-pro",
                },
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pricing.json"
            path.write_text(json.dumps(snapshot), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not cover"):
                estimate_api_cost(
                    snapshot=snapshot,
                    snapshot_path=path,
                    run_config=config,
                    usage={"by_role": {}},
                )

    def test_partial_and_unavailable_usage_never_report_zero_as_complete_cost(self) -> None:
        snapshot = build_pricing_snapshot(payload())
        config = {
            "method": {
                "roster_model": {"provider": "bigmodel", "model": "glm-5.2"},
                "core_field_model": {
                    "provider": "deepseek",
                    "model": "deepseek-v4-pro",
                },
            }
        }
        usage = {
            "by_role": {
                "roster": {
                    "uncached_input_tokens": 10,
                    "cached_input_tokens": 0,
                    "completion_tokens": 0,
                    "telemetry_status": "partial",
                },
                "core_fields": {
                    "uncached_input_tokens": 0,
                    "cached_input_tokens": 0,
                    "completion_tokens": 0,
                    "telemetry_status": "unavailable",
                },
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pricing.json"
            path.write_text(json.dumps(snapshot), encoding="utf-8")
            result = estimate_api_cost(
                snapshot=snapshot,
                snapshot_path=path,
                run_config=config,
                usage=usage,
            )
        self.assertEqual(result["status"], "partial")
        self.assertIsNone(result["total_cny"])
        self.assertIsNone(result["by_role"]["roster"]["amount_cny"])
        self.assertIsNone(result["by_role"]["core_fields"]["amount_cny"])


if __name__ == "__main__":
    unittest.main()
