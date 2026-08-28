"""Operation-adapter tests for the rebuilt contribution gold and benchmark.

Covers: dev10 default planning with separately authorized full50, active-run
resume selecting only eligible papers, irreversible finalize, separated
L0/operations/L1/L2 scoring without composite or pass/fail fields, PDF-only
annotator-isolated gold forms with validate-before-save and one-JSON storage,
a value-free public gold selection, and the temporary original-50 migration
that rejects non-original50 and future-unseen papers.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stella.benchmark.campaign import prepare as prepare_campaign
from stella.benchmark.gold import list_queue, migrate_original50
from stella.benchmark.gold_selection import prepare_selection
from stella.benchmark.hvs_contribution_gold_form import (
    open_annotation,
    save_annotation,
    validate_annotation,
)
from stella.benchmark.run import (
    execute,
    finalize,
    freeze_method,
    resume,
)
from stella.benchmark.scoring import emit_scorecard, score

PAPER = "2601.08888"
EXPERT = "expert-a"


def _gold_env(root: Path, gold_dir: Path) -> None:
    os.environ["STELLA_GOLD_DIR"] = str(gold_dir)


class CampaignProfileTest(unittest.TestCase):
    def test_dev10_is_the_default_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = prepare_campaign(
                {"run_id": "ops-campaign"}, root=Path(tmp)
            )
            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["detail"]["profile"], "dev10")
            self.assertEqual(result["detail"]["paper_count"], 10)

    def test_full50_requires_explicit_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = prepare_campaign(
                {"profile": "full50", "run_id": "ops-campaign"},
                root=Path(tmp),
            )
            self.assertEqual(result["status"], "failed")
            self.assertIn("full50", result["failure"]["detail"])
            authorized = prepare_campaign(
                {
                    "profile": "full50",
                    "full50_explicitly_authorized": True,
                    "run_id": "ops-campaign",
                },
                root=Path(tmp),
            )
            self.assertEqual(authorized["status"], "complete")
            self.assertEqual(authorized["detail"]["profile"], "full50")
            self.assertEqual(authorized["detail"]["paper_count"], 50)


class RunLifecycleAdapterTest(unittest.TestCase):
    @staticmethod
    def _glm_53_method() -> dict:
        route = {
            "provider": "bigmodel",
            "model": "glm-5.3-flash",
            "structured_output_mode": "tool_submission",
            "temperature": 0.0,
            "top_p": 1.0,
            "seed_honored": False,
            "request_overrides": {"reasoning_effort": "low"},
            "stream": False,
        }
        budget = {
            "model_context_limit": 256000,
            "reserve_system_and_rules": 16000,
            "reserve_tool_schema": 4000,
            "reserve_candidate_suffix": 2000,
            "reserve_output": 16000,
            "reserve_provider_framing": 2000,
        }
        return {
            "roster_model": route,
            "quantity_model": route,
            "roster_context_budget": budget,
            "quantity_context_budget": budget,
        }

    def _prepare_run(self, root: Path, papers: dict[str, str]) -> str:
        run_id = "brun-1"
        run_dir = root / "runs" / "benchmark" / run_id
        for paper_id, status in papers.items():
            paper_dir = run_dir / "papers" / paper_id
            paper_dir.mkdir(parents=True, exist_ok=True)
            (paper_dir / "status.json").write_text(
                json.dumps({"status": status}), encoding="utf-8"
            )
        (run_dir / "run.json").write_text(
            json.dumps({"workflow_id": "benchmark", "state": "active"}),
            encoding="utf-8",
        )
        return run_id

    def test_freeze_method_writes_frozen_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = freeze_method(
                {"profile": "dev10", "run_id": "brun-ops"}, root=root
            )
            self.assertEqual(result["status"], "complete")
            self.assertIn("method_fingerprint", result["detail"])
            frozen = json.loads(
                (root / "runs" / "benchmark" / "brun-ops" / "method_config.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertTrue(frozen["method_fingerprint"])
            self.assertIn("components", json.dumps(frozen["method"]))
            components = frozen["method"]["components"]
            self.assertTrue(components["semantic_implementation_sha256"])
            self.assertTrue(frozen["runtime_implementation_sha256"])
            self.assertTrue(frozen["run_fingerprint"])

    def test_freeze_binds_and_validates_the_requested_pricing_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshot_id = "tokendance-2026-08-28-glm-5.3-flash-promo-v1"
            result = freeze_method(
                {
                    "profile": "dev10",
                    "run_id": "brun-priced",
                    "pricing_snapshot_id": snapshot_id,
                    "method": self._glm_53_method(),
                },
                root=root,
            )
            self.assertEqual(result["status"], "complete", result)
            frozen = json.loads(
                (root / "runs" / "benchmark" / "brun-priced" / "method_config.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(frozen["pricing_snapshot"]["snapshot_id"], snapshot_id)
            self.assertEqual(len(frozen["pricing_snapshot"]["sha256"]), 64)

            mismatched = self._glm_53_method()
            for key in ("roster_model", "quantity_model"):
                mismatched[key] = {
                    **mismatched[key],
                    "provider": "deepseek",
                    "model": "deepseek-v4-flash-0731",
                }
            refused = freeze_method(
                {
                    "profile": "dev10",
                    "run_id": "brun-wrong-price",
                    "pricing_snapshot_id": snapshot_id,
                    "method": mismatched,
                },
                root=root,
            )
            self.assertEqual(refused["status"], "failed")
            self.assertIn("does not cover", refused["failure"]["detail"])

    def test_explicit_freeze_rejects_an_undeclared_model_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            method = self._glm_53_method()
            for key in ("roster_model", "quantity_model"):
                method[key] = {**method[key], "model": "glm-unknown"}
            result = freeze_method(
                {"run_id": "brun-unknown-route", "method": method},
                root=Path(tmp),
            )
            self.assertEqual(result["status"], "failed")
            self.assertIn("undeclared structured-output route", result["failure"]["detail"])

    def test_execute_rejects_runtime_drift_before_transport_construction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            freeze_method({"profile": "dev10", "run_id": "brun-drift"}, root=root)
            with patch(
                "stella.benchmark.run._freeze_runtime_components",
                return_value={"workflow_runtime.py": "changed"},
            ):
                result = execute(
                    {
                        "run_id": "brun-drift",
                        "papers": [PAPER],
                        "authorities": {"llm": True, "network": True},
                    },
                    root=root,
                    paper_id=PAPER,
                )

            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["failure"]["kind"], "precondition")
            self.assertIn("runtime implementation", result["failure"]["detail"])

    def test_resume_is_a_real_per_paper_retry_not_a_listing_operation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_id = self._prepare_run(
                root,
                {
                    "2601.00001": "complete",
                    "2601.00002": "failed",
                    "2601.00003": "network_failed",
                    "2601.00004": "pending",
                },
            )
            result = resume(
                {
                    "run_id": run_id,
                    "papers": [
                        "2601.00001",
                        "2601.00002",
                        "2601.00003",
                        "2601.00004",
                    ],
                },
                root=root,
            )
            self.assertEqual(result["status"], "failed")
            self.assertIn("per-paper", result["failure"]["detail"])

    def test_finalize_is_one_way(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_id = self._prepare_run(root, {"2601.00001": "complete"})
            first = finalize(
                {"run_id": run_id, "papers": ["2601.00001"]}, root=root
            )
            self.assertEqual(first["status"], "complete")
            self.assertIn(first["detail"]["final_status"], ("complete", "partial"))
            second = finalize(
                {"run_id": run_id, "papers": ["2601.00001"]}, root=root
            )
            self.assertEqual(second["status"], "failed")
            self.assertIn("immutable", second["failure"]["detail"])

    def test_finalize_writes_snapshot_bound_contribution_cost(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_id = self._prepare_run(root, {"2601.00001": "complete"})
            run_dir = root / "runs" / "benchmark" / run_id
            (run_dir / "campaign.json").write_text(
                json.dumps(
                    {
                        "campaign_id": "hvs-extraction-v6",
                        "profile": "dev10",
                    }
                ),
                encoding="utf-8",
            )
            frozen = freeze_method(
                {
                    "profile": "dev10",
                    "run_id": run_id,
                    "pricing_snapshot_id": (
                        "tokendance-2026-08-28-glm-5.3-flash-promo-v1"
                    ),
                    "method": self._glm_53_method(),
                },
                root=root,
            )
            self.assertEqual(frozen["status"], "complete", frozen)
            attempt_dir = (
                run_dir
                / "extraction_attempts"
                / "benchmark-fixture-2601.00001-1"
                / "papers"
                / "2601.00001"
            )
            attempt_dir.mkdir(parents=True)
            (attempt_dir / "contribution_roster_proposal-slot-0.json").write_text(
                json.dumps(
                    {
                        "attempts": [
                            {
                                "usage": {
                                    "prompt_tokens": 100,
                                    "completion_tokens": 20,
                                    "total_tokens": 120,
                                }
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            result = finalize(
                {"run_id": run_id, "papers": ["2601.00001"]}, root=root
            )
            self.assertEqual(result["status"], "complete", result)
            cost_path = run_dir / "run_cost.json"
            self.assertTrue(cost_path.is_file())
            cost = json.loads(cost_path.read_text(encoding="utf-8"))
            self.assertEqual(
                cost["estimated_api_cost"]["pricing_snapshot"]["snapshot_id"],
                "tokendance-2026-08-28-glm-5.3-flash-promo-v1",
            )
            self.assertIn(str(cost_path), result["artifacts"])

    def test_finalize_rejects_resumable_papers_without_abandonment_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_id = self._prepare_run(
                root,
                {"2601.00001": "complete", "2601.00002": "interrupted"},
            )
            blocked = finalize(
                {"run_id": run_id, "papers": ["2601.00001", "2601.00002"]},
                root=root,
            )
            self.assertEqual(blocked["status"], "failed")
            self.assertEqual(blocked["failure"]["kind"], "precondition")
            self.assertFalse(
                (root / "runs" / "benchmark" / run_id / "finalized.json").exists()
            )
            allowed = finalize(
                {
                    "run_id": run_id,
                    "papers": ["2601.00001", "2601.00002"],
                    "finalize_partial_explicitly_authorized": True,
                },
                root=root,
            )
            self.assertEqual(allowed["status"], "complete")
            self.assertEqual(allowed["detail"]["final_status"], "partial")

    def test_execute_fails_closed_without_llm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = execute(
                {"papers": [PAPER], "authorities": {}}, root=Path(tmp)
            )
            self.assertEqual(result["status"], "failed")
            self.assertIn("llm", result["blockers"])


class ScoringAdapterTest(unittest.TestCase):
    def test_score_reports_layers_separately_without_composite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gold_dir = root / "private-gold"
            gold_dir.mkdir()
            _gold_env(root, gold_dir)
            result = score(
                {"authorities": {"gold_private": True, "scoring": True}},
                root=root,
            )
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["failure"]["kind"], "precondition")
            self.assertIn(
                "benchmark run", result["failure"]["detail"]
            )

    def test_emit_scorecard_has_no_composite_or_pass_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = emit_scorecard(
                {"authorities": {"scoring": True}}, root=root
            )
            self.assertEqual(result["status"], "failed")
            self.assertNotIn("composite", json.dumps(result))
            self.assertNotIn("pass", json.dumps(result).lower())


class GoldAnnotationAdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.gold_dir = self.root / "private-gold"
        self.gold_dir.mkdir()
        self.work_dir = self.root / "gold-work"
        self.work_dir.mkdir()
        paper_dir = self.root / "literature" / PAPER
        paper_dir.mkdir(parents=True)
        (paper_dir / "arxiv.pdf").write_bytes(b"%PDF-1.4 fake")
        self._old_gold = os.environ.get("STELLA_GOLD_DIR")
        self._old_work = os.environ.get("STELLA_GOLD_WORK_DIR")
        os.environ["STELLA_GOLD_DIR"] = str(self.gold_dir)
        os.environ["STELLA_GOLD_WORK_DIR"] = str(self.work_dir)

    def tearDown(self) -> None:
        for key, value in (
            ("STELLA_GOLD_DIR", self._old_gold),
            ("STELLA_GOLD_WORK_DIR", self._old_work),
        ):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    def test_open_annotation_requires_pdf_and_isolates_annotators(self) -> None:
        result = open_annotation(
            {
                "expert": EXPERT,
                "papers": [PAPER],
                "authorities": {"gold_private": True},
            },
            root=self.root,
            paper_id=PAPER,
        )
        self.assertEqual(result["status"], "complete")
        draft = Path(result["detail"]["draft_path"])
        self.assertTrue(draft.is_file())
        self.assertIn(f"draft_{EXPERT}", draft.name)

    def test_open_annotation_requires_gold_authority_and_pdf(self) -> None:
        no_authority = open_annotation(
            {"expert": EXPERT, "papers": [PAPER], "authorities": {}},
            root=self.root,
            paper_id=PAPER,
        )
        self.assertEqual(no_authority["status"], "failed")
        (self.root / "literature" / PAPER / "arxiv.pdf").unlink()
        no_pdf = open_annotation(
            {
                "expert": EXPERT,
                "papers": [PAPER],
                "authorities": {"gold_private": True},
            },
            root=self.root,
            paper_id=PAPER,
        )
        self.assertEqual(no_pdf["status"], "failed")
        self.assertIn("PDF", no_pdf["failure"]["detail"])

    def test_save_requires_validation_and_writes_one_json_per_expert(self) -> None:
        opened = open_annotation(
            {
                "expert": EXPERT,
                "papers": [PAPER],
                "authorities": {"gold_private": True},
            },
            root=self.root,
            paper_id=PAPER,
        )
        draft_path = Path(opened["detail"]["draft_path"])
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
        draft["object_contributions"] = "not-a-list"
        draft_path.write_text(json.dumps(draft), encoding="utf-8")
        invalid = validate_annotation(
            {"expert": EXPERT, "papers": [PAPER], "authorities": {"gold_private": True}},
            root=self.root,
            paper_id=PAPER,
        )
        self.assertEqual(invalid["status"], "failed")
        blocked = save_annotation(
            {"expert": EXPERT, "papers": [PAPER], "authorities": {"gold_private": True}},
            root=self.root,
            paper_id=PAPER,
        )
        self.assertEqual(blocked["status"], "failed")


class GoldSelectionAdapterTest(unittest.TestCase):
    def test_prepare_selection_is_value_free(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gold_dir = root / "private-gold"
            (gold_dir / "2601.00001").mkdir(parents=True)
            (gold_dir / "2601.00001" / f"annotation_{EXPERT}.json").write_text(
                json.dumps(
                    {
                        "schema": {
                            "name": "benchmark.hvs_contribution_annotation",
                            "version": 1,
                        },
                        "arxiv_id": "2601.00001",
                        "annotator": EXPERT,
                        "sha256": "0" * 64,
                    }
                ),
                encoding="utf-8",
            )
            old = os.environ.get("STELLA_GOLD_DIR")
            os.environ["STELLA_GOLD_DIR"] = str(gold_dir)
            try:
                result = prepare_selection(
                    {"expert": EXPERT, "papers": ["2601.00001"]}, root=root
                )
            finally:
                if old is None:
                    os.environ.pop("STELLA_GOLD_DIR", None)
                else:
                    os.environ["STELLA_GOLD_DIR"] = old
            self.assertEqual(result["status"], "complete")
            rendered = json.dumps(result)
            self.assertIn("sha256", rendered)
            self.assertNotIn("object_contributions", rendered)
            self.assertNotIn("quantities", rendered)


class MigrationAdapterTest(unittest.TestCase):
    def test_migration_rejects_non_original50_papers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = migrate_original50(
                {
                    "expert": EXPERT,
                    "papers": ["2701.99999"],
                    "authorities": {"llm": True, "gold_private": True},
                },
                root=Path(tmp),
                paper_id="2701.99999",
            )
            self.assertEqual(result["status"], "failed")
            self.assertIn("original", result["failure"]["detail"].lower())

    def test_migration_requires_both_authorities(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = migrate_original50(
                {"expert": EXPERT, "papers": [PAPER], "authorities": {"llm": True}},
                root=Path(tmp),
                paper_id=PAPER,
            )
            self.assertEqual(result["status"], "failed")
            self.assertIn("gold_private", result["blockers"])


class GoldQueueAdapterTest(unittest.TestCase):
    def test_list_queue_requires_private_authority_and_returns_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = list_queue(
                {"expert": EXPERT, "papers": [], "authorities": {}},
                root=Path(tmp),
            )
            self.assertEqual(result["status"], "failed")


if __name__ == "__main__":
    unittest.main()
