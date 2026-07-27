from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from stella.benchmark.campaign import DEV_IDS, build_campaign, papers_for_split, sha256_file
from stella.benchmark.gold_manifest import validate_append_only_gold_manifest
from stella.benchmark.paths import campaign_paths
from stella.schema_registry import ACTIVE_BENCHMARK_CAMPAIGN

ROOT = Path(__file__).resolve().parents[1]


class CampaignTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sampling_path = campaign_paths(ROOT).sampling_manifest
        cls.sampling = json.loads(cls.sampling_path.read_text(encoding="utf-8"))
        cls.campaign = build_campaign(
            cls.sampling,
            sampling_manifest_sha256=sha256_file(cls.sampling_path),
            code_commit="d" * 40,
        )

    def test_exact_balanced_dev_and_complement_test(self) -> None:
        self.assertEqual(set(papers_for_split(self.campaign, "dev")), set(DEV_IDS))
        self.assertEqual(len(papers_for_split(self.campaign, "test")), 40)
        self.assertFalse(
            set(papers_for_split(self.campaign, "dev"))
            & set(papers_for_split(self.campaign, "test"))
        )
        dev = [paper for paper in self.campaign["papers"] if paper["split"] == "dev"]
        self.assertEqual(sum(p["stratum"].endswith("positive") for p in dev), 5)
        self.assertEqual(sum(p["complexity_bin"].endswith("low") for p in dev), 5)

    def test_hidden_annotated_papers_stay_test(self) -> None:
        test_ids = set(papers_for_split(self.campaign, "test"))
        self.assertIn("1804.09677", test_ids)
        self.assertIn("2504.14836", test_ids)

    def test_test_post_stratified_weights(self) -> None:
        actual = {
            cell: info["test_post_stratified_weight"]
            for cell, info in self.campaign["cells"].items()
        }
        self.assertEqual(
            actual,
            {
                "candidates_proxy_positive/table_complexity_low": 1.714286,
                "candidates_proxy_positive/table_complexity_high": 1.818182,
                "candidates_proxy_negative/table_complexity_low": 11.4,
                "candidates_proxy_negative/table_complexity_high": 9.6,
            },
        )
        self.assertEqual(self.campaign["analysis_policy"]["evaluation_frame_size"], 197)

    def test_build_is_deterministic_and_does_not_need_gold(self) -> None:
        again = build_campaign(
            self.sampling,
            sampling_manifest_sha256=sha256_file(self.sampling_path),
            code_commit="d" * 40,
        )
        self.assertEqual(self.campaign, again)
        self.assertFalse(self.campaign["split_policy"]["gold_or_model_outcomes_used"])

    def test_rejects_ambiguous_short_code_commit(self) -> None:
        with self.assertRaisesRegex(ValueError, "40-character"):
            build_campaign(
                self.sampling,
                sampling_manifest_sha256=sha256_file(self.sampling_path),
                code_commit="deadbeef",
            )

    def test_sampling_hash_uses_exact_file_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.json"
            path.write_bytes(b"{}\n")
            self.assertEqual(len(sha256_file(path)), 64)

    def test_v5_reuses_v4_papers_order_split_and_extends_gold_append_only(self) -> None:
        v4_paths = campaign_paths(ROOT, "hvs-extraction-v4")
        v5_paths = campaign_paths(ROOT, ACTIVE_BENCHMARK_CAMPAIGN)
        v4_sampling = json.loads(v4_paths.sampling_manifest.read_text(encoding="utf-8"))
        v5_sampling = json.loads(v5_paths.sampling_manifest.read_text(encoding="utf-8"))
        v4_campaign = json.loads(v4_paths.campaign_manifest.read_text(encoding="utf-8"))
        v5_campaign = json.loads(v5_paths.campaign_manifest.read_text(encoding="utf-8"))
        v4_gold = json.loads(v4_paths.gold_manifest.read_text(encoding="utf-8"))
        v5_gold = json.loads(v5_paths.gold_manifest.read_text(encoding="utf-8"))

        self.assertEqual(v5_sampling, v4_sampling)
        self.assertEqual(v5_campaign["splits"], {"dev": 10, "test": 40})
        self.assertEqual(
            [(paper["arxiv_id"], paper["split"]) for paper in v5_campaign["papers"]],
            [(paper["arxiv_id"], paper["split"]) for paper in v4_campaign["papers"]],
        )
        self.assertEqual(v5_campaign["campaign_id"], "hvs-extraction-v5")
        validate_append_only_gold_manifest(v4_gold, v5_gold)
        self.assertGreaterEqual(v5_gold["paper_count"], v4_gold["paper_count"])
        self.assertFalse(v5_campaign["test_ready"])

    def test_scratch_experiments_are_registered_as_unscoreable_read_only_history(self) -> None:
        root = ROOT / "benchmark/campaigns/hvs-extraction-scratch-legacy"
        manifest = json.loads(
            (root / "manifest/legacy_campaign_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        inventory = json.loads(
            (root / "archive_inventory.json").read_text(encoding="utf-8")
        )

        self.assertEqual(manifest["lifecycle"], "read_only")
        self.assertEqual(manifest["score_eligibility"], "none")
        self.assertEqual(manifest["run_count"], 25)
        self.assertEqual(len(manifest["run_ids"]), 25)
        self.assertEqual(inventory["campaign_id"], manifest["campaign_id"])
        self.assertEqual(inventory["summary"], {"files": 1142, "bytes": 29972870})
        self.assertEqual(len(inventory["files"]), 1142)
        self.assertTrue(
            all(
                item["source"].startswith("benchmark/scratch/hvs-extraction/")
                and item["destination"].startswith(
                    "benchmark/campaigns/hvs-extraction-scratch-legacy/"
                )
                and len(item["sha256"]) == 64
                and item["bytes"] >= 0
                for item in inventory["files"]
            )
        )


if __name__ == "__main__":
    unittest.main()
