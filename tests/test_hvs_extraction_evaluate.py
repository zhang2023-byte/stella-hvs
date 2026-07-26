"""HVS extraction development evaluation driver tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from stella.hvs_extraction.evaluate import (
    _delivery_metrics,
    _operational_metrics,
    evaluate_hvs_extraction_run,
    render_terminal_report,
)
from stella.hvs_extraction.core_document import build_core_document
from tests.hvs_extraction_fixtures import complete_fields, paper_result


ARXIV_ID = "2406.99994"
RUN_ID = "run-eval-test"


def gold_document() -> dict:
    return {
        "schema": {"name": "benchmark.gold_annotation", "version": 1},
        "arxiv_id": ARXIV_ID,
        "status": "candidates_found",
        "candidates": [
            {
                "paper_candidate_id": "HVS-1",
                "gaia_source_id": "Gaia DR3 123456789",
                "aliases": [],
                "origin_type": "introduced_by_this_paper",
                "quantities": [
                    {
                        "field": "observed_phase_space.radial_velocity",
                        "value": "805",
                        "unit": "km/s",
                        "evidence": [{"location": "Table 1"}],
                    },
                    {
                        "field": "bound_assessment.bound_probability",
                        "value": "0.5",
                        "unit": "",
                        "limit_kind": "upper",
                        "evidence": [{"location": "Table 1 caption"}],
                    },
                ],
                "evidence": [{"location": "Sec 4"}],
            }
        ],
    }


def make_layout(tmp: str) -> tuple[Path, Path]:
    workspace = Path(tmp) / "workspace"
    gold_dir = Path(tmp) / "private-gold"
    paper_out = (
        workspace
        / "benchmark/campaigns/hvs-extraction-v5/runs"
        / RUN_ID
        / "papers"
        / ARXIV_ID
    )
    paper_out.mkdir(parents=True)
    result = paper_result(
        candidates=[{"record_id": "candidate-001", "status": "fields_complete"}],
        fields=complete_fields(),
    )
    result.update(
        {
            "schema": {
                "name": "hvs_extraction.paper_result",
                "version": 1,
            },
            "generated_at": "2026-07-26T00:00:00+00:00",
            "paper": {"arxiv_id": ARXIV_ID},
            "run_id": RUN_ID,
        }
    )
    (paper_out / "paper_result.json").write_text(
        json.dumps(result), encoding="utf-8"
    )
    core = build_core_document(
        result,
        campaign_id="hvs-extraction-v5",
        method_fingerprint="1" * 64,
    )
    (paper_out / "literature_hvs_candidates.json").write_text(
        json.dumps(core), encoding="utf-8"
    )
    run_dir = paper_out.parents[1]
    run_config = {
        "schema": {
            "name": "benchmark.run_config",
            "version": 4,
        },
        "created_at": "2026-07-26T00:00:00+00:00",
        "run_id": RUN_ID,
        "campaign": {
            "campaign_id": "hvs-extraction-v5",
            "manifest_path": "manifest.json",
            "manifest_sha256": "0" * 64,
        },
        "scope": "targeted_dev",
        "manifest": {"path": "manifest.json", "sha256": "0" * 64},
        "papers": [ARXIV_ID],
        "execution": {
            "paper_workers": 1,
            "candidate_workers": 1,
            "field_request_policy": {
                "max_physical_provider_requests": 3,
            },
        },
        "method": {},
        "method_fingerprint": "1" * 64,
        "code": {"revision": "test", "clean_for_dev": True},
        "run_fingerprint": "2" * 64,
    }
    (run_dir / "run_config.json").write_text(
        json.dumps(run_config), encoding="utf-8"
    )
    run_summary = {
        "schema": {
            "name": "benchmark.run_summary",
            "version": 1,
        },
        "generated_at": "2026-07-26T00:01:00+00:00",
        "run_id": RUN_ID,
        "run_fingerprint": "2" * 64,
        "scope": "targeted_dev",
        "state": "completed",
        "papers": {
            ARXIV_ID: {
                "status": "complete",
                "roster_status": "candidates_found",
                "failure_code": None,
                "candidates": {"candidate-001": "fields_complete"},
                "stage_calls": {
                    "roster": 1,
                    "core_fields": 1,
                },
                "total_tokens": 20,
                "wall_seconds": 1.5,
            }
        },
        "totals": {
            "complete": 1,
            "partial": 0,
            "failed": 0,
            "missing": 0,
            "expected": 1,
            "delivered": 1,
            "delivery_rate": 1.0,
            "api_calls": 2,
            "tokens": 20,
            "elapsed_seconds": 1.5,
        },
    }
    (run_dir / "run_summary.json").write_text(
        json.dumps(run_summary), encoding="utf-8"
    )
    gold_paper = gold_dir / ARXIV_ID
    gold_paper.mkdir(parents=True)
    (gold_paper / "annotation_expert.json").write_text(
        json.dumps(gold_document()), encoding="utf-8"
    )
    return workspace, gold_dir


class EvaluateHvsExtractionRunTest(unittest.TestCase):
    def test_repairs_from_failed_papers_are_aggregated(self) -> None:
        operations = _operational_metrics(
            {
                "totals": {
                    "api_calls": 3,
                    "tokens": 120,
                    "elapsed_seconds": 4.5,
                }
            },
            {
                ARXIV_ID: {
                    "failure": {
                        "proposal_failures": [
                            {
                                "failure": {
                                    "repair_history": [
                                        {"type": "format_correction"}
                                    ],
                                    "attempts": [{"salvage": True}],
                                }
                            }
                        ]
                    },
                    "candidates": [
                        {
                            "repair_history": [
                                {"type": "evidence_correction"}
                            ],
                            "attempts": [{}],
                        }
                    ],
                }
            },
        )
        self.assertEqual(operations["format_corrections"], 1)
        self.assertEqual(operations["evidence_corrections"], 1)
        self.assertEqual(operations["tail_truncation_salvages"], 1)
        self.assertEqual(operations["physical_api_attempts"], 3)

    def test_failed_negative_is_still_reported_as_delivery_failure(self) -> None:
        delivery = _delivery_metrics(
            {"papers": [ARXIV_ID]},
            {
                "papers": {ARXIV_ID: {"status": "failed"}},
                "totals": {
                    "complete": 0,
                    "partial": 0,
                    "failed": 1,
                    "missing": 0,
                    "expected": 1,
                    "delivered": 0,
                    "delivery_rate": 0.0,
                },
            },
            {
                "l1": {
                    "per_paper": [
                        {
                            "arxiv_id": ARXIV_ID,
                            "gold_status": "no_candidates",
                            "gold_candidates": 0,
                            "ai_candidates": 0,
                            "tp": 0,
                            "fp": 0,
                            "fn": 0,
                        }
                    ]
                }
            },
        )
        self.assertEqual(delivery["failed"], 1)
        self.assertEqual(delivery["per_paper"][0]["delivery_status"], "failed")
        self.assertEqual(delivery["per_paper"][0]["ai_candidates"], 0)

    def test_end_to_end_scorecard_and_private_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, gold_dir = make_layout(tmp)
            record = evaluate_hvs_extraction_run(workspace, RUN_ID, gold_dir=gold_dir)
            scorecard_path = (
                workspace
                / "benchmark/campaigns/hvs-extraction-v5/runs"
                / RUN_ID
                / "evaluation"
                / "scorecard.json"
            )
            self.assertTrue(scorecard_path.is_file())
            scorecard = json.loads(scorecard_path.read_text(encoding="utf-8"))
            self.assertEqual(
                scorecard["schema"],
                {"name": "benchmark.scorecard", "version": 5},
            )
            self.assertEqual(scorecard["gold_papers"], 1)
            self.assertEqual(scorecard["run_label"], RUN_ID)
            self.assertEqual(
                record["schema"],
                {
                    "name": "hvs_extraction.evaluation",
                    "version": 1,
                },
            )
            self.assertEqual(record["delivery"]["complete"], 1)
            self.assertEqual(record["delivery"]["failed"], 0)
            self.assertIn("precision", record["l1"])
            self.assertIn("strict_agreement", record["l2"])
            self.assertIn(
                "bound_assessment.bound_probability",
                record["per_field_coverage"],
            )
            self.assertEqual(record["operations"]["physical_api_attempts"], 2)
            self.assertNotIn("pass", record)
            self.assertNotIn("composite", record)
            rendered = render_terminal_report(record)
            self.assertIn("Delivery", rendered)
            self.assertIn("L1", rendered)
            self.assertIn("L2", rendered)
            self.assertIn("Per-field coverage", rendered)
            self.assertIn("No composite score", rendered)
            details_path = Path(record["private_details_path"])
            self.assertTrue(details_path.is_file())
            self.assertIn("scoring-details/extraction", details_path.as_posix())
            self.assertTrue(
                details_path.as_posix().startswith(Path(tmp).resolve().as_posix())
            )
            details = json.loads(details_path.read_text(encoding="utf-8"))
            row = next(
                row
                for row in details["papers"][0]["pairs"][0]["l2"]
                if row["field"] == "observed_phase_space.radial_velocity"
            )
            self.assertEqual(row["status"], "value_match")
            self.assertIn("do not enter V5 numeric", record["uncertainty_note"])

    def test_missing_gold_is_an_explicit_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, gold_dir = make_layout(tmp)
            (
                gold_dir / ARXIV_ID / "annotation_expert.json"
            ).unlink()
            with self.assertRaisesRegex(ValueError, "no gold annotation"):
                evaluate_hvs_extraction_run(workspace, RUN_ID, gold_dir=gold_dir)

    def test_config_summary_paper_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, gold_dir = make_layout(tmp)
            summary_path = (
                workspace
                / "benchmark/campaigns/hvs-extraction-v5/runs"
                / RUN_ID
                / "run_summary.json"
            )
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            summary["papers"]["9999.99999"] = summary["papers"].pop(ARXIV_ID)
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "paper collections differ"):
                evaluate_hvs_extraction_run(workspace, RUN_ID, gold_dir=gold_dir)

    def test_test_smoke_is_never_scoreable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, gold_dir = make_layout(tmp)
            config_path = (
                workspace
                / "benchmark/campaigns/hvs-extraction-v5/runs"
                / RUN_ID
                / "run_config.json"
            )
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["scope"] = "test_smoke"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "never scoreable"):
                evaluate_hvs_extraction_run(workspace, RUN_ID, gold_dir=gold_dir)

    def test_noncurrent_run_config_is_not_scoreable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, gold_dir = make_layout(tmp)
            config_path = (
                workspace
                / "benchmark/campaigns/hvs-extraction-v5/runs"
                / RUN_ID
                / "run_config.json"
            )
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["schema"]["version"] = 3
            config_path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not current"):
                evaluate_hvs_extraction_run(
                    workspace, RUN_ID, gold_dir=gold_dir
                )

    def test_gold_dir_must_be_external_to_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            inside = workspace / "benchmark" / "gold"
            inside.mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "outside the public workspace"):
                evaluate_hvs_extraction_run(workspace, RUN_ID, gold_dir=inside)


if __name__ == "__main__":
    unittest.main()
