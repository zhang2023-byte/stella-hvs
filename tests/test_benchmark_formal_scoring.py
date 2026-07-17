"""Synthetic contract tests for the current formal scorecard."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from stella.benchmark.campaign import sha256_file
from stella.benchmark.run_contract import build_run_config, build_method_fingerprint
from stella.benchmark.scoring import score_formal_campaign_run, write_scorecard_once
from stella.schema_registry import ACTIVE_BENCHMARK_CAMPAIGN, schema_ref
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
    def fixture(self, root: Path, *, split: str = "dev", invalid_test_gold: bool = False, decoupled_enrichment_invalid: bool = False):
        campaign_path = root / "campaign.json"
        campaign = {
            "schema": {"name": "benchmark.campaign", "version": 1},
            "campaign_id": ACTIVE_BENCHMARK_CAMPAIGN,
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
            "provenance": {
                "components": {
                    "prompt": "prompt-recorded",
                    "skill": "skill-recorded",
                    "validator": "validator-recorded",
                    "context_packer": "context-recorded",
                    "task_surface": "surface-recorded",
                    "normalizer": "normalizer-recorded",
                    "scorer": "scorer-recorded",
                    "identity_matching": "identity-recorded",
                    "unit_table": "unit-recorded",
                    "rule_profile": "rule-recorded",
                }
            },
            "parameters": {
                "task_surface": "full",
                "task_surface_sha256": "surface-recorded",
                "rule_profile_id": "hvs_extractor",
                "rule_profile_sha256": "rule-recorded",
            },
        }
        self.current_components = dict(method["provenance"]["components"])
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
            if arxiv_id in valid or decoupled_enrichment_invalid:
                artifacts[arxiv_id] = {
                    "literature_hvs_candidates.json": {
                        "sha256": sha256_file(output),
                        "bytes": output.stat().st_size,
                    }
                }
        if decoupled_enrichment_invalid:
            # Task 3 Step 2: every paper's core is valid, but dev-b's
            # enrichment fails strict FULL validation. The scorer must
            # consume the core documents.
            core_outcomes = {"valid": list(expected), "invalid": [], "missing": []}
            enrichment_outcomes = {
                "valid": list(valid),
                "invalid": list(invalid),
                "missing": [],
            }
            core_delivery = {
                "status": "complete",
                "validation_mode": "full_core",
                "papers": core_outcomes,
                "artifacts": artifacts,
            }
            enrichment_delivery = {
                "status": "partial" if invalid else "complete",
                "validation_mode": "full_enrichment",
                "papers": enrichment_outcomes,
                "artifacts": artifacts,
            }
            papers_view = core_outcomes
        else:
            delivery = {
                "status": "complete" if not invalid else "partial",
                "validation_mode": "full_core",
                "papers": {"valid": valid, "invalid": invalid, "missing": []},
                "artifacts": artifacts,
            }
            core_delivery = delivery
            enrichment_delivery = {
                **delivery,
                "validation_mode": "full_enrichment",
            }
            papers_view = delivery["papers"]
        manifest = {
            "schema": schema_ref("benchmark.run_manifest"),
            "run_id": config["run_id"],
            "campaign": {"campaign_id": campaign["campaign_id"], "sha256": campaign_hash},
            "split": split,
            "method_fingerprint": build_method_fingerprint(method),
            "component_hashes": self.current_components,
            "run_config_sha256": sha256_file(run_dir / "run_config.json"),
            "papers": papers_view,
            "artifacts": artifacts,
            "core_delivery": core_delivery,
            "enrichment_delivery": enrichment_delivery,
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
                current_component_hashes=self.current_components,
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
            self.assertEqual(
                set(scorecard["provenance"]),
                {
                    "evaluation_label",
                    "scorer_sha256",
                    "identity_matching_sha256",
                    "unit_table_sha256",
                    "gold_snapshot",
                    "supersedes",
                },
            )
            self.assertEqual(scorecard["provenance"]["evaluation_label"], "run-dev")
            self.assertIsNone(scorecard["provenance"]["supersedes"])

    def test_core_valid_enrichment_invalid_is_scored_from_the_core_document(self) -> None:
        # Task 3 Step 2: enrichment findings are non-blocking for L1/L2. A
        # paper whose enrichment failed strict FULL validation still has its
        # core document scored, and it is not a diagnostic-only delivery.
        with tempfile.TemporaryDirectory() as tmp:
            campaign, gold_dir, gold_manifest, run_dir = self.fixture(
                Path(tmp), decoupled_enrichment_invalid=True
            )
            scorecard, details = score_formal_campaign_run(
                campaign_path=campaign,
                split="dev",
                run_dir=run_dir,
                gold_dir=gold_dir,
                gold_manifest_path=gold_manifest,
                bootstrap_iterations=10,
                current_component_hashes=self.current_components,
            )
            self.assertEqual(scorecard["delivery_counts"], {
                "expected": 2, "valid": 2, "invalid": 0, "missing": 0,
                "scored_as_unavailable": 0,
            })
            self.assertEqual(scorecard["papers_missing_ai_output"], [])
            per_paper = {
                paper["arxiv_id"]: paper for paper in scorecard["l1"]["per_paper"]
            }
            self.assertEqual(per_paper["dev-b"]["ai_status"], "complete")
            self.assertEqual(details["diagnostic_only"]["invalid_deliveries"], [])

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
                    current_component_hashes=self.current_components,
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
                    current_component_hashes=self.current_components,
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
                current_component_hashes=self.current_components,
            )
            self.assertIn("post_stratified_sensitivity", scorecard)
            self.assertEqual(scorecard["formal"]["test_release"]["sha256"], sha256_file(
                releases / "run-test.json"
            ))

    def test_scoring_rejects_component_drift_before_gold_or_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign, gold_dir, gold_manifest, run_dir = self.fixture(Path(tmp))
            current = dict(self.current_components)
            current["scorer"] = "scorer-current"
            gold_manifest.unlink()
            with self.assertRaisesRegex(ValueError, "provenance mismatch.*scorer"):
                score_formal_campaign_run(
                    campaign_path=campaign,
                    split="dev",
                    run_dir=run_dir,
                    gold_dir=gold_dir,
                    gold_manifest_path=gold_manifest,
                    bootstrap_iterations=10,
                    current_component_hashes=current,
                )

    def test_scorecard_write_is_append_only_by_evaluation_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scorecard = {
                "schema": schema_ref("benchmark.scorecard"),
                "run_label": "evaluation-r1",
                "provenance": {"evaluation_label": "evaluation-r1"},
            }
            path = write_scorecard_once(root, scorecard)
            self.assertTrue(path.is_file())
            with self.assertRaisesRegex(ValueError, "already exists.*new evaluation label"):
                write_scorecard_once(root, scorecard)


if __name__ == "__main__":
    unittest.main()
