"""Tests for the benchmark experiment report and literature baseline scoring."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from stella.benchmark import baseline as baseline_mod
from stella.benchmark import report as report_mod
from stella.benchmark.baseline import score_literature_baseline, write_baseline_outputs
from stella.benchmark.report import (
    aggregate,
    build_report_data,
    normalize_scorecard,
    render_html,
)


def _scorecard_v7(run_id: str, fingerprint: str, *, coverage: float = 0.9) -> dict:
    return {
        "schema": {"name": "benchmark.scorecard", "version": 7},
        "run_label": f"{run_id}--gold-dev-primary-v1",
        "run_source": {"mode": "formal_campaign", "run_id": run_id},
        "gold_papers": 10,
        "l0": {
            "roster_delivery": {"expected": 10, "complete": 10, "delivery_rate": 1.0},
            "core_field_delivery": {
                "expected": 10,
                "complete": 9,
                "partial": 1,
                "full_delivery_rate": 0.9,
                "usable_delivery_rate": 1.0,
            },
            "format_validation": {"first_pass_rate": 0.98},
        },
        "operations": {
            "usage": {"total": {"total_tokens": 2500000, "api_calls": 70}},
            "estimated_api_cost": {"total_cny": "1.25"},
        },
        "l1": {
            "micro": {"precision": 0.98, "recall": 1.0, "f1": 0.99},
            "bootstrap": {"micro_f1_ci95": [0.9, 1.0]},
        },
        "l2": {
            "row_counts": {"gold_only": 5, "ai_only": 1},
            "micro": {
                "coverage": coverage,
                "agreement_over_compared_strict": 0.99,
                "delivery_end_to_end_strict": coverage - 0.01,
            },
            "bootstrap": {"delivery_end_to_end_strict_ci95": [0.8, 1.0]},
        },
        "formal": {
            "campaign": {"campaign_id": "hvs-extraction-v6", "sha256": "x"},
            "split": "dev",
            "run_id": run_id,
            "gold_selection": {"selection_id": "dev-primary-v1"},
            "method_fingerprint": fingerprint,
        },
    }


def _scorecard_v5(run_id: str, fingerprint: str, *, coverage: float = 0.7) -> dict:
    return {
        "schema": {"name": "benchmark.scorecard", "version": 5},
        "run_label": run_id,
        "run_source": {"mode": "formal_campaign", "run_id": run_id},
        "gold_papers": 10,
        "delivery_counts": {"expected": 10, "valid": 9, "invalid": 1, "missing": 0},
        "l1": {"micro": {"precision": 1.0, "recall": 0.96, "f1": 0.978}},
        "l2": {
            "row_counts": {"gold_only": 40, "ai_only": 2},
            "micro": {
                "coverage": coverage,
                "agreement_over_compared_strict": 1.0,
                "delivery_end_to_end_strict": coverage,
            },
        },
        "formal": {
            "campaign": {"campaign_id": "hvs-extraction-v5", "sha256": "y"},
            "split": "dev",
            "run_id": run_id,
            "method_fingerprint": fingerprint,
        },
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _run_archive(
    workspace: Path,
    campaign: str,
    run_id: str,
    fingerprint: str,
    *,
    elapsed: float = 600.0,
    tokens: int = 2000000,
    with_failure: bool = False,
    with_manifest: bool = False,
) -> None:
    run_dir = workspace / "benchmark" / "campaigns" / campaign / "runs" / run_id
    if with_manifest:
        _write_json(
            run_dir / "run_manifest.json",
            {
                "run_id": run_id,
                "papers": ["1902.05061", "2209.03560"],
                "l1_roster_delivery": {
                    "complete": ["2209.03560"],
                    "failed": ["1902.05061"],
                    "missing": [],
                },
                "l2_core_field_delivery": {
                    "complete": [],
                    "partial": ["2209.03560"],
                    "failed": ["1902.05061"],
                    "missing": [],
                    "candidate_counts": {
                        "total": 1,
                        "fields_complete": 0,
                        "field_extraction_failed": 1,
                    },
                },
            },
        )
    summary = {
        "run_id": run_id,
        "totals": {
            "tokens": tokens,
            "api_calls": 60,
            "elapsed_seconds": elapsed,
        },
        "papers": {
            "1902.05061": {
                "status": "partial" if with_failure else "complete",
                "roster_status": "candidates_found",
                "failure_code": None,
                "candidates": {
                    "candidate-001": "field_extraction_failed" if with_failure else "fields_complete"
                },
                "stage_calls": {"roster": 1, "core_fields": 2},
                "total_tokens": 12345,
                "wall_seconds": 67.8,
            }
        },
    }
    _write_json(run_dir / "run_summary.json", summary)
    paper_result = {
        "status": "partial" if with_failure else "complete",
        "roster_status": "candidates_found",
        "failure": None,
        "roster": {"status": "roster_complete", "failure": None},
        "candidates": [
            {
                "record_id": "candidate-001",
                "status": "field_extraction_failed" if with_failure else "fields_complete",
                "failure": (
                    {
                        "code": "submission_format_failure",
                        "initial_errors": ["- missing_submission_call: no tool call"],
                        "correction_errors": [],
                    }
                    if with_failure
                    else None
                ),
            }
        ],
    }
    _write_json(run_dir / "papers" / "1902.05061" / "paper_result.json", paper_result)
    config = {
        "run_id": run_id,
        "method_fingerprint": fingerprint,
        "method": {
            "roster_model": {
                "model": "deepseek-v4-flash-0731",
                "structured_output_mode": "tool_submission",
                "request_overrides": {
                    "thinking": {"type": "enabled"},
                    "reasoning_effort": "max",
                },
            },
            "core_field_model": {
                "model": "deepseek-v4-flash-0731",
                "structured_output_mode": "tool_submission",
                "request_overrides": {"reasoning_effort": "low"},
            },
        },
        "code": {"revision": "abc1234def"},
    }
    _write_json(run_dir / "run_config.json", config)


class NormalizeScorecardTest(unittest.TestCase):
    def test_v7_metrics(self) -> None:
        metrics = normalize_scorecard(_scorecard_v7("run-a", "fp1", coverage=0.91))
        self.assertEqual(metrics["l1_f1"], 0.99)
        self.assertEqual(metrics["l2_coverage"], 0.91)
        self.assertEqual(metrics["roster_delivery"], 1.0)
        self.assertEqual(metrics["core_full_delivery"], 0.9)
        self.assertEqual(metrics["core_usable_delivery"], 1.0)
        self.assertEqual(metrics["format_first_pass"], 0.98)
        self.assertEqual(metrics["tokens"], 2500000)
        self.assertEqual(metrics["api_calls"], 70)
        self.assertAlmostEqual(metrics["cost_cny"], 1.25)
        self.assertEqual(metrics["gold_only"], 5)
        self.assertEqual(metrics["l1_f1_ci95"], [0.9, 1.0])

    def test_v5_metrics(self) -> None:
        metrics = normalize_scorecard(_scorecard_v5("run-b", "fp2", coverage=0.66))
        self.assertEqual(metrics["l1_f1"], 0.978)
        self.assertEqual(metrics["l2_coverage"], 0.66)
        self.assertEqual(metrics["roster_delivery"], 0.9)
        self.assertIsNone(metrics["core_full_delivery"])
        self.assertIsNone(metrics["format_first_pass"])
        self.assertIsNone(metrics["tokens"])
        self.assertIsNone(metrics["cost_cny"])


class AggregateTest(unittest.TestCase):
    def test_mean_and_sample_std(self) -> None:
        result = aggregate([0.8, 0.9, 1.0])
        self.assertAlmostEqual(result["mean"], 0.9)
        self.assertAlmostEqual(result["std"], 0.1)
        self.assertEqual(result["n"], 3)
        self.assertEqual(result["min"], 0.8)
        self.assertEqual(result["max"], 1.0)

    def test_single_value_has_zero_std(self) -> None:
        result = aggregate([0.5])
        self.assertEqual(result["std"], 0.0)
        self.assertEqual(result["n"], 1)

    def test_none_values_are_skipped(self) -> None:
        result = aggregate([None, 0.5, None])
        self.assertEqual(result["n"], 1)
        self.assertEqual(result["mean"], 0.5)
        empty = aggregate([None, None])
        self.assertIsNone(empty["mean"])
        self.assertEqual(empty["n"], 0)


class BuildReportDataTest(unittest.TestCase):
    def _workspace(self, root: Path) -> Path:
        workspace = root / "workspace"
        for index in range(3):
            run_id = f"v6-run-r{index}-20260805"
            _write_json(
                workspace
                / "benchmark"
                / "campaigns"
                / "hvs-extraction-v6"
                / "scoring"
                / f"{run_id}--gold-dev-primary-v1"
                / "scorecard.json",
                _scorecard_v7(run_id, "fp-main", coverage=0.9 + index * 0.01),
            )
            _run_archive(
                workspace,
                "hvs-extraction-v6",
                run_id,
                "fp-main",
                elapsed=600.0 + index * 60.0,
                with_failure=(index == 1),
            )
        single_id = "v5-run-single-20260731"
        _write_json(
            workspace
            / "benchmark"
            / "campaigns"
            / "hvs-extraction-v5"
            / "scoring"
            / single_id
            / "scorecard.json",
            _scorecard_v5(single_id, "fp-single", coverage=0.66),
        )
        _run_archive(
            workspace, "hvs-extraction-v5", single_id, "fp-single", with_manifest=True
        )
        _write_json(
            workspace
            / "benchmark"
            / "costs"
            / "tokendance-test-snapshot"
            / "legacy_dev10.json",
            {
                "campaigns": [
                    {
                        "campaign": "hvs-extraction-v5",
                        "runs": [
                            {
                                "run_id": single_id,
                                "estimated_api_cost": {"total_cny": "6.758056"},
                            }
                        ],
                    }
                ]
            },
        )
        return workspace

    def test_grouping_and_aggregation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self._workspace(Path(tmp))
            baseline_dir = Path(tmp) / "scoring-details"
            _write_json(
                baseline_dir / "literature-baseline-dev--gold-dev-primary-v1" / "scorecard.json",
                {
                    "run_label": "literature-baseline-dev--gold-dev-primary-v1",
                    "run_source": {"mode": "legacy_literature"},
                    "gold_papers": 10,
                    "l1": {"micro": {"precision": 0.98, "recall": 1.0, "f1": 0.9895}},
                    "l2": {
                        "row_counts": {"gold_only": 60},
                        "micro": {"coverage": 0.6, "delivery_end_to_end_strict": 0.59},
                    },
                },
            )
            data = build_report_data(
                workspace,
                ["hvs-extraction-v5", "hvs-extraction-v6"],
                [baseline_dir],
            )
        self.assertEqual(len(data["experiments"]), 1)
        main = data["experiments"][0]
        self.assertEqual(main["n_runs"], 3)
        self.assertEqual(main["family"], "flash")
        self.assertIn("V4 Flash", main["label"])
        coverage = main["metrics"]["l2_coverage"]
        self.assertAlmostEqual(coverage["mean"], 0.91, places=6)
        self.assertAlmostEqual(coverage["std"], 0.01, places=6)
        wall = main["metrics"]["wall_minutes"]
        self.assertAlmostEqual(wall["mean"], 11.0, places=6)
        failed_run = main["runs"][1]
        errors = failed_run["papers"][0]["errors"]
        self.assertEqual(errors[0]["code"], "submission_format_failure")
        self.assertEqual(errors[0]["scope"], "candidate-001")
        self.assertTrue(errors[0]["messages"])
        self.assertEqual(len(data["singles"]), 1)
        self.assertEqual(data["singles"][0]["n_runs"], 1)
        self.assertAlmostEqual(
            data["singles"][0]["runs"][0]["metrics"]["cost_cny"], 6.758056
        )
        single_metrics = data["singles"][0]["runs"][0]["metrics"]
        self.assertAlmostEqual(single_metrics["core_full_delivery"], 0.0)
        self.assertAlmostEqual(single_metrics["core_usable_delivery"], 0.5)
        self.assertIsNotNone(data["baseline"])
        self.assertAlmostEqual(data["baseline"]["flat"]["l1_f1"], 0.9895)

    def test_render_html_embeds_escaped_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self._workspace(Path(tmp))
            data = build_report_data(workspace, ["hvs-extraction-v6"], [])
        page = render_html(data, "2026-08-06 00:00 UTC")
        self.assertIn("const DATA = {", page)
        self.assertIn("质量指标", page)
        self.assertIn("论文交付率", page)
        payload = page.split("const DATA = ", 1)[1].split(";\nconst FAMILY", 1)[0]
        self.assertNotIn("</script>", payload.lower())
        self.assertNotIn("</", payload)


class LiteratureBaselineTest(unittest.TestCase):
    def _campaign(self, root: Path) -> Path:
        campaign = {
            "schema": {"name": "benchmark.campaign", "version": 1},
            "campaign_id": "hvs-extraction-v6",
            "papers": [
                {"arxiv_id": "1902.05061", "split": "dev"},
                {"arxiv_id": "2209.03560", "split": "dev"},
                {"arxiv_id": "2602.16925", "split": "test"},
            ],
        }
        path = root / "campaign_manifest.json"
        path.write_text(json.dumps(campaign), encoding="utf-8")
        return path

    def _gold_snapshot(self) -> tuple[dict, dict]:
        annotations = {
            "1902.05061": {"status": "no_candidates", "candidates": []},
            "2209.03560": {"status": "no_candidates", "candidates": []},
        }
        snapshot = {
            "selection_id": "dev-primary-v1",
            "manifest_sha256": "sel",
            "selected_records_sha256": "rec",
            "gold_manifest_sha256": "gm",
            "annotators": {key: "expert-a" for key in annotations},
        }
        return annotations, snapshot

    def test_baseline_scoring_uses_literature_documents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_path = self._campaign(root)
            literature = root / "literature"
            doc = {"extraction": {"status": "no_candidates"}, "candidates": []}
            _write_json(literature / "1902.05061" / "literature_hvs_candidates.json", doc)
            _write_json(literature / "2209.03560" / "literature_hvs_candidates.json", doc)
            annotations, snapshot = self._gold_snapshot()
            with mock.patch.object(
                baseline_mod,
                "load_formal_gold_snapshot",
                return_value=(annotations, snapshot),
            ):
                scorecard, details = score_literature_baseline(
                    campaign_path=campaign_path,
                    split="dev",
                    literature_dir=literature,
                    gold_dir=root / "gold",
                    gold_manifest_path=root / "gold_manifest.json",
                    gold_selection_path=root / "selection.json",
                    run_label="literature-baseline-test",
                )
        self.assertEqual(scorecard["gold_papers"], 2)
        self.assertEqual(scorecard["run_source"]["mode"], "legacy_literature")
        self.assertEqual(scorecard["formal"]["baseline"], "literature_baseline")
        self.assertEqual(
            scorecard["formal"]["gold_selection"]["selection_id"], "dev-primary-v1"
        )
        self.assertEqual(scorecard["provenance"]["evaluation_label"], "literature-baseline-test")
        self.assertEqual(scorecard["l1"]["negative_papers"]["count"], 2)
        self.assertEqual(details["formal"], scorecard["formal"])
        for paper in details["papers"]:
            self.assertEqual(paper["gold_annotator"], "expert-a")

    def test_write_baseline_outputs_and_leak_guard(self) -> None:
        details = {
            "papers": [
                {
                    "pairs": [
                        {
                            "gold_id": "SECRET-GOLD-NAME",
                            "l2": [{"gold": "123.45", "gold_note": "note"}],
                        }
                    ],
                    "unmatched_gold": [],
                }
            ]
        }
        clean = {"run_label": "ok-label", "l1": {}}
        dirty = {"run_label": "dirty-label", "note": "mentions SECRET-GOLD-NAME"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scorecard_path, details_path = write_baseline_outputs(
                root / "ok", clean, details
            )
            self.assertTrue(scorecard_path.is_file())
            self.assertTrue(details_path.is_file())
            with self.assertRaises(ValueError):
                write_baseline_outputs(root / "dirty", dirty, details)


class ReportScriptParserTest(unittest.TestCase):
    def test_parsers(self) -> None:
        import importlib.util
        import sys

        for name in ("build_benchmark_report", "score_literature_baseline"):
            path = Path(__file__).resolve().parents[2] / "scripts" / f"{name}.py"
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            parser = module.build_parser()
            self.assertIsNotNone(parser)


if __name__ == "__main__":
    unittest.main()
