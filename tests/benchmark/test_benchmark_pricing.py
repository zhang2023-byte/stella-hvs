from __future__ import annotations

import copy
from decimal import Decimal
import json
import tempfile
import unittest
from pathlib import Path

from stella.benchmark.pricing import (
    validate_pricing_coverage,
    build_pricing_snapshot,
    estimate_api_cost,
    estimate_api_cost_for_routes,
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
    def test_glm_53_flash_promo_snapshot_matches_supplied_tokendance_rates(self) -> None:
        path = (
            Path(__file__).resolve().parents[2]
            / "benchmark"
            / "pricing"
            / "tokendance"
            / "tokendance-2026-08-28-glm-5.3-flash-promo-v1.json"
        )
        snapshot = load_pricing_snapshot(path)
        route = snapshot["routes"][0]
        self.assertEqual(
            (route["provider"], route["model"]),
            ("bigmodel", "glm-5.3-flash"),
        )
        self.assertEqual(
            route["rates_cny_per_million_tokens"],
            {
                "uncached_input": "0.4",
                "cached_input": "0.115",
                "output": "1.4",
            },
        )
        self.assertEqual(
            snapshot["source"]["evidence_sha256"],
            "1d2072e7d5deacc48c911e101058de8c1d05a45af49ae9a17249f985fd97f123",
        )

    def test_live_snapshot_covers_current_default_routes(self) -> None:
        root = Path(__file__).resolve().parents[2]
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

    def test_live_deepseek_peakvalley_snapshot_matches_official_list(self) -> None:
        root = Path(__file__).resolve().parents[2]
        matches = sorted(
            (root / "benchmark" / "pricing").glob("*/*deepseek-peakvalley-v1.json")
        )
        self.assertEqual(len(matches), 1)
        snapshot = load_pricing_snapshot(matches[0])
        routes = {
            (route["provider"], route["model"]): route
            for route in snapshot["routes"]
        }
        self.assertEqual(
            routes[("deepseek", "deepseek-v4-flash-0731")][
                "rates_cny_per_million_tokens"
            ],
            {"uncached_input": "3", "cached_input": "0.1", "output": "9"},
        )
        self.assertEqual(
            routes[("deepseek", "deepseek-v4-pro-0813")][
                "rates_cny_per_million_tokens"
            ],
            {"uncached_input": "9", "cached_input": "0.3", "output": "27"},
        )
        schedules = {
            (s["provider"], s["model"]): s
            for s in snapshot["time_tiered_schedules"]
        }
        flash = schedules[("deepseek", "deepseek-v4-flash-0731")]
        self.assertEqual(
            flash["peak_windows"],
            [{"start": "09:00", "end": "12:00"}, {"start": "14:00", "end": "18:00"}],
        )
        bands = {
            tier["band"]: tier["rates_cny_per_million_tokens"]
            for tier in flash["tiers"]
        }
        self.assertEqual(
            bands["off_peak"],
            {"uncached_input": "1.5", "cached_input": "0.05", "output": "4.5"},
        )
        for key in bands["peak"]:
            self.assertEqual(
                Decimal(bands["off_peak"][key]) * 2, Decimal(bands["peak"][key])
            )
        validate_pricing_coverage(
            snapshot,
            {
                "roster": ("deepseek", "deepseek-v4-flash-0731"),
                "core_fields": ("deepseek", "deepseek-v4-flash-0731"),
            },
        )

    def test_deepseek_published_source_is_accepted_with_matching_url(self) -> None:
        snapshot = payload()
        snapshot["source"] = {
            "name": "DeepSeek",
            "url": "https://api-docs.deepseek.com/zh-cn/quick_start/pricing",
            "captured_at": "2026-08-18T12:00:00+08:00",
            "effective_at": None,
        }
        built = build_pricing_snapshot(snapshot)
        self.assertEqual(built["source"]["name"], "DeepSeek")
        wrong = payload()
        wrong["source"] = {
            "name": "DeepSeek",
            "url": "https://example.com/pricing",
            "captured_at": "2026-08-18T12:00:00+08:00",
            "effective_at": None,
        }
        with self.assertRaisesRegex(ValueError, "source URL"):
            build_pricing_snapshot(wrong)

    def test_time_tiered_schedule_anchors_peak_band_to_flat_route(self) -> None:
        schedule = {
            "provider": "bigmodel",
            "model": "glm-5.2",
            "source_route": {
                "model_slug": "glm-5.2",
                "provider_slug": "bigmodel",
                "price_id": "standard",
            },
            "timezone": "Asia/Shanghai",
            "peak_windows": [{"start": "09:00", "end": "12:00"}],
            "tiers": [
                {
                    "band": "peak",
                    "rates_cny_per_million_tokens": {
                        "uncached_input": "2",
                        "cached_input": "1",
                        "output": "4",
                    },
                },
                {
                    "band": "off_peak",
                    "rates_cny_per_million_tokens": {
                        "uncached_input": "1",
                        "cached_input": "0.5",
                        "output": "2",
                    },
                },
            ],
        }
        snapshot = payload()
        snapshot["time_tiered_schedules"] = [copy.deepcopy(schedule)]
        self.assertEqual(
            build_pricing_snapshot(snapshot)["time_tiered_schedules"][0][
                "timezone"
            ],
            "Asia/Shanghai",
        )
        mismatch = payload()
        peak_differs = copy.deepcopy(schedule)
        peak_differs["tiers"][0]["rates_cny_per_million_tokens"]["output"] = "5"
        mismatch["time_tiered_schedules"] = [peak_differs]
        with self.assertRaisesRegex(ValueError, "peak tier must equal"):
            build_pricing_snapshot(mismatch)
        unanchored = payload()
        no_flat = copy.deepcopy(schedule)
        no_flat["model"] = "glm-4.7"
        unanchored["time_tiered_schedules"] = [no_flat]
        with self.assertRaisesRegex(ValueError, "no flat route"):
            build_pricing_snapshot(unanchored)
        bad_window = payload()
        bad = copy.deepcopy(schedule)
        bad["peak_windows"] = [{"start": "25:00", "end": "26:00"}]
        bad_window["time_tiered_schedules"] = [bad]
        with self.assertRaisesRegex(ValueError, "peak window"):
            build_pricing_snapshot(bad_window)

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

    def test_prices_arbitrary_legacy_stage_names_with_the_same_formula(self) -> None:
        snapshot = build_pricing_snapshot(payload())
        usage = {
            "by_role": {
                "roster_review": {
                    "uncached_input_tokens": 500_000,
                    "cached_input_tokens": 500_000,
                    "completion_tokens": 250_000,
                    "telemetry_status": "complete",
                }
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pricing.json"
            path.write_text(json.dumps(snapshot), encoding="utf-8")
            result = estimate_api_cost_for_routes(
                snapshot=snapshot,
                snapshot_path=path,
                routes={"roster_review": ("bigmodel", "glm-5.2")},
                usage=usage,
            )
        self.assertEqual(result["total_cny"], "2.500000")
        self.assertEqual(
            result["by_role"]["roster_review"]["amount_cny"], "2.500000"
        )

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
