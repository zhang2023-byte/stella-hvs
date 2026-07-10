from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from stella.benchmark.campaign import DEV_IDS, build_campaign, papers_for_split, sha256_file

ROOT = Path(__file__).resolve().parents[1]


class CampaignTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sampling_path = ROOT / "benchmark" / "manifest" / "sampling_manifest.json"
        cls.sampling = json.loads(cls.sampling_path.read_text(encoding="utf-8"))
        cls.campaign = build_campaign(
            cls.sampling,
            sampling_manifest_sha256=sha256_file(cls.sampling_path),
            freeze_commit="deadbeef",
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
            freeze_commit="deadbeef",
        )
        self.assertEqual(self.campaign, again)
        self.assertFalse(self.campaign["split_policy"]["gold_or_model_outcomes_used"])

    def test_sampling_hash_uses_exact_file_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.json"
            path.write_bytes(b"{}\n")
            self.assertEqual(len(sha256_file(path)), 64)


if __name__ == "__main__":
    unittest.main()
