"""Synthetic contract tests for formal scorecard v0.3."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from stella.benchmark.campaign import sha256_file
from stella.benchmark.run_contract import build_run_config, build_method_fingerprint
from stella.benchmark.scoring import score_formal_campaign_run
from stella.schema_registry import schema_ref
from stella.benchmark.test_release import build_test_release, write_test_release


def dump(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def annotation(arxiv_id: str) -> dict:
    return {
        "schema": {"name": "benchmark.gold_annotation", "version": 1},
        "arxiv_id": arxiv_id,
        "status": "no_candidates",
        "candidates": [],
    }


class FormalScoringTest(unittest.TestCase):
    def fixture(self, root: Path, *, split: str = "dev", invalid_test_gold: bool = False):
        campaign_path = root / "campaign.json"
        campaign = {
            "schema": {"name": "benchmark.campaign", "version": 1},
            "campaign_id": "synthetic-v1",
            "papers": [
                {"arxiv_id": "dev-a", "split": "dev"},
                {"arxiv_id": "dev-b", "split": "dev"},
                {
                    "arxiv_id": "test-a",
                    "split": "test",
                    "analysis_weights": {"test_post_stratified_sensitivity": 9.6},
                },
            ],
        }
        dump(campaign_path, campaign)
        campaign_hash = sha256_file(campaign_path)
        gold_dir = root / "gold"
        json_files = []
        for arxiv_id in ("dev-a", "dev-b", "test-a"):
            path = gold_dir / arxiv_id / "annotation_expert.json"
            if arxiv_id == "test-a" and invalid_test_gold:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("not-json", encoding="utf-8")
            else:
                dump(path, annotation(arxiv_id))
            json_files.append(
                {
                    "arxiv_id": arxiv_id,
                    "file": path.relative_to(gold_dir).as_posix(),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "bytes": path.stat().st_size,
                }
            )
        gold_manifest = root / "gold_manifest.json"
        dump(
            gold_manifest,
            {"schema": {"name": "benchmark.gold_manifest", "version": 1}, "files": json_files},
        )
        expected = ["dev-a", "dev-b"] if split == "dev" else ["test-a"]
        method = {
            "pipeline": {"name": "synthetic", "version": "1"},
            "models": {"extractor": "m", "reviewer": None},
            "providers": {"extractor": []},
            "versions": {"prompt": "p", "skill": "s", "validator": "v", "context_packer": "c"},
        }
        config = build_run_config(
            run_id=f"run-{split}",
            method=method,
            expected_papers=expected,
            code={"commit": "abc", "dirty": False},
            campaign=campaign,
            campaign_sha256=campaign_hash,
            split=split,
        )
        run_dir = root / config["run_id"]
        dump(run_dir / "run_config.json", config)
        valid = [expected[0]]
        invalid = expected[1:] if split == "dev" else []
        artifacts = {}
        for arxiv_id in expected:
            output = run_dir / arxiv_id / "literature_hvs_candidates.json"
            dump(output, {"extraction": {"status": "complete"}, "candidates": []})
            if arxiv_id in valid:
                artifacts[arxiv_id] = {
                    "literature_hvs_candidates.json": {
                        "sha256": sha256_file(output),
                        "bytes": output.stat().st_size,
                    }
                }
        manifest = {
            "schema": {"name": "benchmark.run_manifest", "version": 1},
            "run_id": config["run_id"],
            "campaign": {"campaign_id": campaign["campaign_id"], "sha256": campaign_hash},
            "split": split,
            "method_fingerprint": build_method_fingerprint(method),
            "run_config_sha256": sha256_file(run_dir / "run_config.json"),
            "papers": {"valid": valid, "invalid": invalid, "missing": []},
            "artifacts": artifacts,
            "leakage_audit": {"status": "clean"},
        }
        dump(run_dir / "run_manifest.json", manifest)
        return campaign_path, gold_dir, gold_manifest, run_dir

    def test_dev_only_loads_dev_gold_and_invalid_delivery_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign, gold_dir, gold_manifest, run_dir = self.fixture(
                Path(tmp), invalid_test_gold=True
            )
            scorecard, details = score_formal_campaign_run(
                campaign_path=campaign,
                split="dev",
                run_dir=run_dir,
                gold_dir=gold_dir,
                gold_manifest_path=gold_manifest,
                bootstrap_iterations=10,
            )
            self.assertEqual(scorecard["schema"], schema_ref("benchmark.scorecard"))
            self.assertEqual(scorecard["delivery_counts"], {
                "expected": 2, "valid": 1, "invalid": 1, "missing": 0, "scored_as_unavailable": 1,
            })
            self.assertNotIn("weighted_micro", scorecard["l1"])
            self.assertNotIn("post_stratified_sensitivity", scorecard)
            self.assertEqual(scorecard["papers_missing_ai_output"], ["dev-b"])
            self.assertEqual(len(details["diagnostic_only"]["invalid_deliveries"]), 1)
            self.assertNotIn("diagnostic-only invalid delivery", json.dumps(scorecard))

    def test_gold_json_hash_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign, gold_dir, gold_manifest, run_dir = self.fixture(Path(tmp))
            (gold_dir / "dev-a" / "annotation_expert.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                score_formal_campaign_run(
                    campaign_path=campaign,
                    split="dev",
                    run_dir=run_dir,
                    gold_dir=gold_dir,
                    gold_manifest_path=gold_manifest,
                    bootstrap_iterations=10,
                )

    def test_test_split_requires_matching_release_and_emits_sensitivity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign, gold_dir, gold_manifest, run_dir = self.fixture(Path(tmp), split="test")
            with self.assertRaisesRegex(ValueError, "release manifest"):
                score_formal_campaign_run(
                    campaign_path=campaign,
                    split="test",
                    run_dir=run_dir,
                    gold_dir=gold_dir,
                    gold_manifest_path=gold_manifest,
                    releases_root=Path(tmp) / "releases",
                    bootstrap_iterations=10,
                )
            release = build_test_release(campaign_path=campaign, run_dir=run_dir)
            releases = Path(tmp) / "releases"
            write_test_release(release=release, releases_root=releases)
            scorecard, _ = score_formal_campaign_run(
                campaign_path=campaign,
                split="test",
                run_dir=run_dir,
                gold_dir=gold_dir,
                gold_manifest_path=gold_manifest,
                releases_root=releases,
                bootstrap_iterations=10,
            )
            self.assertIn("post_stratified_sensitivity", scorecard)
            self.assertEqual(scorecard["formal"]["test_release"]["sha256"], sha256_file(
                releases / "synthetic-v1" / "run-test.json"
            ))


if __name__ == "__main__":
    unittest.main()
