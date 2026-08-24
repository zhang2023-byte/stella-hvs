from __future__ import annotations

import json
import unittest
from pathlib import Path

from stella.benchmark.legacy_cost import (
    LEGACY_DEV10_RUNS,
    build_legacy_dev10_cost_inventory,
)


ROOT = Path(__file__).resolve().parents[2]
PRICING = (
    ROOT
    / "benchmark"
    / "pricing"
    / "tokendance"
    / "tokendance-2026-08-03-screenshots-v1.json"
)
PUBLISHED = (
    ROOT
    / "benchmark"
    / "costs"
    / "tokendance-2026-08-03-screenshots-v1"
    / "legacy_dev10.json"
)


class BenchmarkLegacyCostTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inventory = json.loads(PUBLISHED.read_text(encoding="utf-8"))

    @staticmethod
    def _missing_run_inputs() -> list[Path]:
        return [
            ROOT
            / "benchmark"
            / "campaigns"
            / campaign
            / "runs"
            / run_id
            / "run_config.json"
            for campaign, run_ids in LEGACY_DEV10_RUNS.items()
            for run_id in run_ids
            if not (
                ROOT
                / "benchmark"
                / "campaigns"
                / campaign
                / "runs"
                / run_id
                / "run_config.json"
            ).is_file()
        ]

    def test_scope_is_exactly_the_audited_21_completed_dev10_runs(self) -> None:
        expected = {
            (campaign, run_id)
            for campaign, run_ids in LEGACY_DEV10_RUNS.items()
            for run_id in run_ids
        }
        actual = {
            (campaign["campaign"], run["run_id"])
            for campaign in self.inventory["campaigns"]
            for run in campaign["runs"]
        }
        self.assertEqual(actual, expected)
        self.assertEqual(self.inventory["summary"]["run_count"], 21)
        self.assertEqual(
            [item["summary"]["run_count"] for item in self.inventory["campaigns"]],
            [7, 4, 3, 2, 5],
        )
        self.assertTrue(
            all(run["paper_count"] == 10 for campaign in self.inventory["campaigns"] for run in campaign["runs"])
        )

    def test_recalculated_totals_and_stages_match_the_frozen_snapshot(self) -> None:
        summary = self.inventory["summary"]
        self.assertEqual(summary["usage"]["total_tokens"], 168_363_279)
        self.assertEqual(summary["usage"]["api_calls"], 4_132)
        self.assertEqual(
            summary["estimated_api_cost"]["known_subtotal_cny"],
            "304.552747",
        )
        self.assertEqual(
            summary["estimated_api_cost"]["by_stage_cny"],
            {
                "roster": "62.032459",
                "roster_review": "30.295702",
                "core_fields": "79.164294",
                "final_review": "133.060291",
            },
        )

    def test_special_scratch_run_is_explicitly_marked_as_reconstructed(self) -> None:
        runs = {
            run["run_id"]: run
            for campaign in self.inventory["campaigns"]
            for run in campaign["runs"]
        }
        self.assertEqual(
            runs["scratch-final-full-dev10"]["provenance_status"],
            "reconstructed_from_paper_artifacts",
        )
        self.assertEqual(
            runs["scratch-final-full-dev10"]["estimated_api_cost"][
                "known_subtotal_cny"
            ],
            "9.516967",
        )
        self.assertNotIn("scratch-exp-a-ds-jso-think-s1", runs)

    def test_generation_is_deterministic_and_self_hashed(self) -> None:
        missing = self._missing_run_inputs()
        if missing:
            self.skipTest(
                "legacy cost regeneration requires ignored run archives; "
                f"first missing input: {missing[0].relative_to(ROOT)}"
            )
        rebuilt = build_legacy_dev10_cost_inventory(ROOT, PRICING)
        self.assertEqual(rebuilt, self.inventory)
        self.assertEqual(len(rebuilt["content_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
