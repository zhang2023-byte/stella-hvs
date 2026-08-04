from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from stella.benchmark.pricing import build_pricing_snapshot
from stella.benchmark.run_cost import (
    build_run_cost_artifact,
    validate_run_cost_artifact,
    write_run_cost_once,
)
from stella.schema_registry import schema_ref


class BenchmarkRunCostTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.run_dir = self.root / "run"
        self.run_dir.mkdir()
        config = {
            "schema": schema_ref("benchmark.run_config"),
            "run_id": "fixture-run",
            "campaign": "hvs-extraction-v6",
            "scope": "full_dev",
            "method": {
                "roster_model": {"provider": "bigmodel", "model": "glm-5.2"},
                "core_field_model": {
                    "provider": "deepseek",
                    "model": "deepseek-v4-pro",
                },
            },
        }
        usage = {
            "by_role": {
                "roster": {
                    "uncached_input_tokens": 1_000_000,
                    "cached_input_tokens": 0,
                    "completion_tokens": 0,
                    "telemetry_status": "complete",
                },
                "core_fields": {
                    "uncached_input_tokens": 0,
                    "cached_input_tokens": 0,
                    "completion_tokens": 1_000_000,
                    "telemetry_status": "complete",
                },
            },
            "total": {"total_tokens": 2_000_000},
        }
        summary = {
            "schema": schema_ref("benchmark.run_summary"),
            "generated_at": "2026-08-04T00:00:00+00:00",
            "run_id": "fixture-run",
            "state": "completed",
            "usage": usage,
        }
        self._write("run_config.json", config)
        self._write("run_summary.json", summary)
        self._write("run_manifest.json", {"run_id": "fixture-run"})
        snapshot = build_pricing_snapshot(
            {
                "snapshot_id": "fixture-pricing",
                "source": {
                    "name": "TokenDance",
                    "url": "https://tokendance.space/models/fixture",
                    "captured_at": "2026-08-03T00:00:00+00:00",
                    "effective_at": None,
                },
                "currency": "CNY",
                "routes": [
                    self._route("bigmodel", "glm-5.2", "2", "1", "4"),
                    self._route(
                        "deepseek", "deepseek-v4-pro", "1", "1", "3"
                    ),
                ],
            }
        )
        self.pricing_path = self.root / "pricing.json"
        self.pricing_path.write_text(json.dumps(snapshot), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write(self, name: str, value: object) -> None:
        (self.run_dir / name).write_text(json.dumps(value), encoding="utf-8")

    @staticmethod
    def _route(
        provider: str, model: str, uncached: str, cached: str, output: str
    ) -> dict:
        return {
            "provider": provider,
            "model": model,
            "source_route": {
                "model_slug": model,
                "provider_slug": provider,
                "price_id": "fixture",
            },
            "rates_cny_per_million_tokens": {
                "uncached_input": uncached,
                "cached_input": cached,
                "output": output,
            },
            "cached_input_basis": "listed",
        }

    def test_builds_snapshot_bound_cost_with_source_hashes(self) -> None:
        artifact = build_run_cost_artifact(self.run_dir, self.pricing_path)
        self.assertEqual(artifact["estimated_api_cost"]["total_cny"], "5.000000")
        self.assertEqual(
            artifact["estimated_api_cost"]["pricing_snapshot"]["snapshot_id"],
            "fixture-pricing",
        )
        self.assertEqual(len(artifact["source"]["run_summary_sha256"]), 64)
        validate_run_cost_artifact(artifact)

    def test_write_is_immutable_and_tamper_is_rejected(self) -> None:
        output = write_run_cost_once(self.run_dir, self.pricing_path)
        self.assertTrue(output.is_file())
        with self.assertRaisesRegex(ValueError, "already exists"):
            write_run_cost_once(self.run_dir, self.pricing_path)
        artifact = json.loads(output.read_text(encoding="utf-8"))
        artifact["estimated_api_cost"]["known_subtotal_cny"] = "0.000000"
        with self.assertRaisesRegex(ValueError, "content hash mismatch"):
            validate_run_cost_artifact(artifact)

    def test_completed_run_requires_manifest_but_interrupted_does_not(self) -> None:
        (self.run_dir / "run_manifest.json").unlink()
        with self.assertRaisesRegex(ValueError, "requires run_manifest"):
            build_run_cost_artifact(self.run_dir, self.pricing_path)
        summary = json.loads((self.run_dir / "run_summary.json").read_text())
        summary["state"] = "interrupted"
        self._write("run_summary.json", summary)
        artifact = build_run_cost_artifact(self.run_dir, self.pricing_path)
        self.assertIsNone(artifact["source"]["run_manifest_sha256"])


if __name__ == "__main__":
    unittest.main()
