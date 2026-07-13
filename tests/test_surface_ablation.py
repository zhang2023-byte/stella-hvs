from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from stella.benchmark.surface_ablation import (
    HEADLINE_KEYS,
    LoadedRun,
    PaperCounts,
    analyze_surface_ablation,
    decide,
    paired_bootstrap,
    validate_pair_metadata,
)
from stella.benchmark.campaign import sha256_file
from stella.benchmark.run_contract import build_method_fingerprint
from stella.schema_registry import schema_ref


PAPERS = [f"dev-{index:02d}" for index in range(10)]


def loaded_run(
    run_id: str,
    surface: str,
    counts: PaperCounts,
    *,
    method: str = "B",
    snapshot: str = "snapshot",
) -> LoadedRun:
    producer = {
        "B": "stella-benchmark-extraction",
        "C": "stella-agentic-extraction",
    }[method]
    config = {
        "mode": "formal",
        "campaign": {"campaign_id": "hvs-extraction-v2", "sha256": "campaign"},
        "split": "dev",
        "expected_papers": PAPERS,
        "code": {"commit": "same", "dirty": False},
        "method": {
            "producer": producer,
            "models": {"extractor": "e", "reviewer": "r"},
            "providers": {"extractor": ["p"], "reviewer": ["rp"]},
            "parameters": {
                "temperature": 0,
                "max_repair_rounds": 3,
                "reviewer_enabled": True,
                "task_surface": surface,
                "task_surface_sha256": f"hash-{surface}",
            },
        },
        "method_fingerprint": f"fingerprint-{surface}",
    }
    formal = {
        "campaign": config["campaign"],
        "split": "dev",
        "gold_snapshot_sha256": snapshot,
    }
    return LoadedRun(
        run_id=run_id,
        surface=surface,
        config=config,
        manifest={},
        scorecard={"formal": formal},
        counts={paper: counts for paper in PAPERS},
        context_hashes={paper: f"context-{paper}" for paper in PAPERS},
        resources={},
        scorecard_sha256="score",
        run_manifest_sha256="manifest",
    )


def headline(delta: float, ci: list[float]) -> dict[str, dict]:
    return {
        key: {
            "full": 0.5,
            "core": 0.5 + delta,
            "delta_core_minus_full": delta,
            "paired_bootstrap_ci95": ci,
        }
        for key in HEADLINE_KEYS
    }


class SurfaceAblationTest(unittest.TestCase):
    def _write_run_fixture(
        self,
        root: Path,
        *,
        run_id: str,
        surface: str,
        campaign_ref: dict,
    ) -> None:
        run_dir = root / "runs" / run_id
        method = {
            "producer": "stella-benchmark-extraction",
            "models": {
                "extractor": "deepseek-v4-pro",
                "reviewer": "glm-5.2",
            },
            "providers": {
                "extractor": ["deepseek"],
                "reviewer": ["zhipu"],
            },
            "parameters": {
                "temperature": 0,
                "max_repair_rounds": 3,
                "batch_size": 8,
                "reviewer_enabled": True,
                "task_surface": surface,
                "task_surface_sha256": f"hash-{surface}",
            },
        }
        fingerprint = build_method_fingerprint(method)
        config = {
            "schema": schema_ref("benchmark.run_config"),
            "run_id": run_id,
            "mode": "formal",
            "campaign": campaign_ref,
            "split": "dev",
            "expected_papers": PAPERS,
            "code": {"commit": "same", "dirty": False},
            "method": method,
            "method_fingerprint": fingerprint,
            "state": "open",
            "created_at": "2026-07-13T00:00:00+00:00",
        }
        run_dir.mkdir(parents=True)
        config_path = run_dir / "run_config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        artifacts = {}
        for paper in PAPERS:
            paper_dir = run_dir / paper
            paper_dir.mkdir()
            context = paper_dir / "context_manifest.json"
            context.write_text('{"sha256":"same-input"}', encoding="utf-8")
            (paper_dir / "report.json").write_text(
                json.dumps(
                    {
                        "scaffold_attempts": 1,
                        "batch_calls": 1,
                        "repair_rounds": 0,
                        "usage_totals": {
                            "prompt_tokens": 10,
                            "completion_tokens": 5,
                            "reasoning_tokens": 2,
                            "total_tokens": 15,
                            "prompt_cache_hit_tokens": 4,
                        },
                    }
                ),
                encoding="utf-8",
            )
            attempts = paper_dir / "attempts"
            attempts.mkdir()
            for name in ("extract.response.json", "review.response.json"):
                (attempts / name).write_text("{}", encoding="utf-8")
            artifacts[paper] = {
                "context_manifest.json": {"sha256": sha256_file(context)}
            }
        manifest = {
            "schema": schema_ref("benchmark.run_manifest"),
            "run_id": run_id,
            "campaign": campaign_ref,
            "split": "dev",
            "method_fingerprint": fingerprint,
            "run_config_sha256": sha256_file(config_path),
            "papers": {"valid": PAPERS, "invalid": [], "missing": []},
            "artifacts": artifacts,
            "leakage_audit": {"status": "clean"},
        }
        manifest_path = run_dir / "run_manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        formal = {
            "campaign": campaign_ref,
            "split": "dev",
            "run_id": run_id,
            "gold_snapshot_sha256": "same-snapshot",
            "run_manifest_sha256": sha256_file(manifest_path),
            "method_fingerprint": fingerprint,
            "test_release": None,
        }
        scorecard = {
            "schema": schema_ref("benchmark.scorecard"),
            "run_label": run_id,
            "formal": formal,
            "delivery_counts": {"valid": 10, "invalid": 0, "missing": 0},
            "l1": {
                "per_paper": [
                    {"arxiv_id": paper, "tp": 1, "fp": 0, "fn": 0}
                    for paper in PAPERS
                ]
            },
        }
        score_path = root / "scoring" / run_id / "scorecard.json"
        score_path.parent.mkdir(parents=True)
        score_path.write_text(json.dumps(scorecard), encoding="utf-8")
        details = {
            "schema": schema_ref("benchmark.scoring_details"),
            "run_label": run_id,
            "formal": formal,
            "papers": [
                {
                    "arxiv_id": paper,
                    "gold_status": "candidates_found",
                    "pairs": [{"l2": [{"status": "value_match"}]}],
                    "unmatched_gold": [],
                }
                for paper in PAPERS
            ],
        }
        detail_path = root / "details" / run_id / "details.json"
        detail_path.parent.mkdir(parents=True)
        detail_path.write_text(json.dumps(details), encoding="utf-8")

    def test_end_to_end_loader_emits_aggregate_only_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign = {
                "schema": schema_ref("benchmark.campaign"),
                "campaign_id": "hvs-extraction-v2",
                "papers": [
                    {"arxiv_id": paper, "split": "dev"} for paper in PAPERS
                ],
            }
            campaign_path = root / "campaign.json"
            campaign_path.write_text(json.dumps(campaign), encoding="utf-8")
            campaign_ref = {
                "campaign_id": "hvs-extraction-v2",
                "sha256": sha256_file(campaign_path),
            }
            self._write_run_fixture(
                root, run_id="full-r1", surface="full", campaign_ref=campaign_ref
            )
            self._write_run_fixture(
                root,
                run_id="core-r1",
                surface="core_prov",
                campaign_ref=campaign_ref,
            )
            summary = analyze_surface_ablation(
                workspace=root,
                campaign_path=campaign_path,
                method="B",
                full_run_ids=["full-r1"],
                core_run_ids=["core-r1"],
                runs_dir=root / "runs",
                scoring_dir=root / "scoring",
                details_dir=root / "details",
                iterations=20,
            )
            self.assertEqual(
                summary["schema"], schema_ref("benchmark.extraction_surface_ablation")
            )
            self.assertEqual(summary["cohort"]["paper_count"], 10)
            self.assertEqual(summary["resources"]["full"]["api_calls"], 20)
            serialized = json.dumps(summary)
            for forbidden in ("gold_id", "ai_id", '"value"', '"quote"', '"l2"'):
                self.assertNotIn(forbidden, serialized)

    def test_bootstrap_is_reproducible(self) -> None:
        pair = (
            loaded_run("full", "full", PaperCounts(tp=1, fp=1, fn=1, strict=1, compared=2, gold_quantities=3)),
            loaded_run("core", "core_prov", PaperCounts(tp=1, strict=2, compared=2, gold_quantities=3)),
        )
        first = paired_bootstrap([pair], PAPERS, iterations=100, seed=20260706)
        second = paired_bootstrap([pair], PAPERS, iterations=100, seed=20260706)
        self.assertEqual(first, second)
        self.assertGreater(first["l1_micro_f1"]["paired_bootstrap_ci95"][0], 0)

    def test_decision_covers_core_full_and_inconclusive(self) -> None:
        self.assertEqual(
            decide(headline(0.1, [0.05, 0.2]), full_unavailable=1, core_unavailable=1)["status"],
            "core_wins",
        )
        self.assertEqual(
            decide(headline(-0.1, [-0.2, -0.05]), full_unavailable=1, core_unavailable=1)["status"],
            "full_wins",
        )
        result = decide(headline(0.0, [-0.1, 0.1]), full_unavailable=1, core_unavailable=1)
        self.assertEqual(result["status"], "inconclusive")
        self.assertFalse(result["core_first_triggered"])

    def test_pair_validation_rejects_model_context_cohort_and_snapshot_drift(self) -> None:
        full = loaded_run("full", "full", PaperCounts(), method="C")
        core = loaded_run("core", "core_prov", PaperCounts(), method="C")
        validate_pair_metadata(full, core, "C")

        core.config["method"]["models"]["extractor"] = "different"
        with self.assertRaisesRegex(ValueError, "beyond task surface"):
            validate_pair_metadata(full, core, "C")
        core = loaded_run("core", "core_prov", PaperCounts(), method="C")
        core.config["method"]["models"]["reviewer"] = "different"
        with self.assertRaisesRegex(ValueError, "beyond task surface"):
            validate_pair_metadata(full, core, "C")
        core = loaded_run("core", "core_prov", PaperCounts(), method="C")
        core.config["method"]["parameters"]["reviewer_enabled"] = False
        with self.assertRaisesRegex(ValueError, "reviewer-backed"):
            validate_pair_metadata(full, core, "C")
        core = loaded_run("core", "core_prov", PaperCounts(), method="C")
        core.context_hashes[PAPERS[0]] = "different"
        with self.assertRaisesRegex(ValueError, "context-manifest"):
            validate_pair_metadata(full, core, "C")
        core = loaded_run("core", "core_prov", PaperCounts(), method="C")
        core.config["code"]["commit"] = "different"
        with self.assertRaisesRegex(ValueError, "code"):
            validate_pair_metadata(full, core, "C")
        core = loaded_run("core", "core_prov", PaperCounts(), method="C", snapshot="different")
        with self.assertRaisesRegex(ValueError, "gold_snapshot"):
            validate_pair_metadata(full, core, "C")

    def test_unequal_replicate_counts_are_rejected_before_io(self) -> None:
        with self.assertRaisesRegex(ValueError, "counts"):
            analyze_surface_ablation(
                workspace=None,  # type: ignore[arg-type]
                campaign_path=None,  # type: ignore[arg-type]
                method="B",
                full_run_ids=["f1", "f2"],
                core_run_ids=["c1"],
                runs_dir=None,  # type: ignore[arg-type]
                scoring_dir=None,  # type: ignore[arg-type]
                details_dir=None,  # type: ignore[arg-type]
            )

    def test_run_ids_reject_path_traversal_before_io(self) -> None:
        with self.assertRaisesRegex(ValueError, "run id"):
            analyze_surface_ablation(
                workspace=None,  # type: ignore[arg-type]
                campaign_path=None,  # type: ignore[arg-type]
                method="B",
                full_run_ids=["../full"],
                core_run_ids=["core"],
                runs_dir=None,  # type: ignore[arg-type]
                scoring_dir=None,  # type: ignore[arg-type]
                details_dir=None,  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
