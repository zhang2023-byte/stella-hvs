"""Report builder tests: a pure view over synthetic scorer outputs.

All fixtures are synthetic (contamination rule). The report must render
inside a temporary directory only — writing into the workspace is refused
because the pages embed gold values.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_benchmark_report.py"
SPEC = importlib.util.spec_from_file_location("build_benchmark_report", SCRIPT)
report = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(report)


def synthetic_scorecard(label: str) -> dict:
    return {
        "schema_version": "stella.benchmark_scorecard.v0.2",
        "run_label": label,
        "run_source": {"mode": "unit", "pipeline": "test-pipe", "model": "test-model"},
        "gold_papers": 1,
        "l1": {
            "per_paper": [
                {
                    "arxiv_id": "1111.00001",
                    "gold_status": "candidates_found",
                    "ai_status": "complete",
                    "gold_candidates": 2,
                    "ai_candidates": 2,
                    "tp": 1,
                    "fp": 1,
                    "fn": 1,
                    "sampling_weight": 1.0,
                    "match_methods": {"gaia_id": 1},
                    "precision": 0.5,
                    "recall": 0.5,
                    "f1": 0.5,
                }
            ],
            "micro": {"tp": 1, "fp": 1, "fn": 1, "precision": 0.5, "recall": 0.5, "f1": 0.5},
            "bootstrap": {"micro_f1_ci95": [0.2, 0.8]},
            "negative_papers": {"count": 0},
        },
        "l2": {
            "micro": {
                "gold_quantities": 3,
                "compared": 1,
                "ai_only": 1,
                "coverage": 1 / 3,
                "agreement_over_compared_strict": 1.0,
                "agreement_over_compared_lenient": 1.0,
                "delivery_end_to_end_strict": 1 / 3,
                "delivery_end_to_end_lenient": 1 / 3,
                "fill_precision_strict": 0.5,
                "fill_precision_lenient": 0.5,
            },
            "bootstrap": {
                "delivery_end_to_end_strict_ci95": [0.1, 0.6],
                "agreement_over_compared_strict_ci95": [0.5, 1.0],
                "fill_precision_strict_ci95": [0.2, 0.9],
            },
        },
    }


def synthetic_details() -> dict:
    return {
        "schema_version": "stella.benchmark_scoring_details.v0.2",
        "papers": [
            {
                "arxiv_id": "1111.00001",
                "gold_status": "candidates_found",
                "ai_status": "complete",
                "pairs": [
                    {
                        "gold_id": "HVS-SYNTH-A",
                        "ai_id": "x:cand-001",
                        "method": "gaia_id",
                        "detail": "42",
                        "gold_origin_type": "introduced_by_this_paper",
                        "ai_origin_type": "introduced_by_this_paper",
                        "l2": [
                            {
                                "field": "observed_phase_space.radial_velocity",
                                "status": "value_match",
                                "gold": "234 km/s",
                                "ai": "234 km/s",
                            },
                            {
                                "field": "observed_phase_space.distance",
                                "status": "ai_only",
                                "gold": "",
                                "ai": "9.9 kpc",
                            },
                        ],
                    }
                ],
                "unmatched_gold": [
                    {
                        "gold_id": "HVS-SYNTH-B",
                        "l2": [
                            {
                                "field": "observed_phase_space.radial_velocity",
                                "status": "gold_only",
                                "gold": "512 km/s",
                                "ai": "",
                                "gold_note": "paper also quotes 520 km/s",
                                "gold_note_present": True,
                            }
                        ],
                    }
                ],
                "unmatched_ai": ["x:cand-999"],
                "gold_warnings": [],
            }
        ],
    }


class ReportRenderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.scoring_dir = base / "scoring"
        self.details_dir = base / "scoring-details"
        for label in ("method-a", "method-b"):
            (self.scoring_dir / label).mkdir(parents=True)
            (self.scoring_dir / label / "scorecard.json").write_text(
                json.dumps(synthetic_scorecard(label)), encoding="utf-8"
            )
            (self.details_dir / label).mkdir(parents=True)
            (self.details_dir / label / "details.json").write_text(
                json.dumps(synthetic_details()), encoding="utf-8"
            )

    def test_renders_index_and_paper_pages(self) -> None:
        runs = report.load_runs(
            ["method-a", "method-b"], self.scoring_dir, self.details_dir
        )
        output = Path(self.tmp.name) / "report" / "index.html"
        written = report.write_site(output, runs, ["1111.00001"])
        self.assertEqual(len(written), 2)
        index_html = output.read_text(encoding="utf-8")
        self.assertIn("method-a", index_html)
        self.assertIn("method-b", index_html)
        self.assertIn("33.3%", index_html)  # delivery end-to-end
        paper_html = (output.parent / "papers" / "1111.00001.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("HVS-SYNTH-A", paper_html)
        self.assertIn("234 km/s", paper_html)
        self.assertIn("missed by AI", paper_html)
        self.assertIn("gold note: paper also quotes 520 km/s", paper_html)
        self.assertIn("AI only", paper_html)

    def test_refuses_to_write_inside_workspace(self) -> None:
        argv = [
            "build_benchmark_report.py",
            "--details-dir",
            str(self.details_dir),
            "--scoring-dir",
            str(self.scoring_dir),
            "--output",
            str(ROOT / "benchmark" / "index.html"),
        ]
        with mock.patch.object(sys, "argv", argv):
            with self.assertRaises(SystemExit) as ctx:
                report.main()
        self.assertIn("refusing", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
