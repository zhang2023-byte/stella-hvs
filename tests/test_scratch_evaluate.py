"""Scratch development evaluation driver tests (D043)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from stella.benchmark.scratch.evaluate import evaluate_scratch_run
from test_scratch_projection import complete_fields, paper_result


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
                    }
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
        / "benchmark/scratch/hvs-extraction/runs"
        / RUN_ID
        / "papers"
        / ARXIV_ID
    )
    paper_out.mkdir(parents=True)
    result = paper_result(
        candidates=[{"record_id": "candidate-001", "status": "fields_complete"}],
        fields=complete_fields(),
    )
    (paper_out / "paper_result.json").write_text(
        json.dumps(result), encoding="utf-8"
    )
    gold_paper = gold_dir / ARXIV_ID
    gold_paper.mkdir(parents=True)
    (gold_paper / "annotation_expert.json").write_text(
        json.dumps(gold_document()), encoding="utf-8"
    )
    return workspace, gold_dir


class EvaluateScratchRunTest(unittest.TestCase):
    def test_end_to_end_scorecard_and_private_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, gold_dir = make_layout(tmp)
            record = evaluate_scratch_run(workspace, RUN_ID, gold_dir=gold_dir)
            scorecard_path = (
                workspace
                / "benchmark/scratch/hvs-extraction/runs"
                / RUN_ID
                / "evaluation"
                / "scorecard.json"
            )
            self.assertTrue(scorecard_path.is_file())
            scorecard = json.loads(scorecard_path.read_text(encoding="utf-8"))
            self.assertEqual(scorecard["gold_papers"], 1)
            self.assertEqual(scorecard["run_label"], RUN_ID)
            details_path = Path(record["details_path"])
            self.assertTrue(details_path.is_file())
            self.assertIn("scoring-details/scratch", details_path.as_posix())
            self.assertTrue(
                details_path.as_posix().startswith(Path(tmp).resolve().as_posix())
            )
            details = json.loads(details_path.read_text(encoding="utf-8"))
            row = details["papers"][0]["pairs"][0]["l2"][0]
            self.assertEqual(row["status"], "value_match")
            self.assertIn("D041", record["scoring_note"])

    def test_missing_gold_is_an_explicit_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, gold_dir = make_layout(tmp)
            with self.assertRaisesRegex(ValueError, "no gold annotation"):
                evaluate_scratch_run(
                    workspace, RUN_ID, gold_dir=gold_dir, arxiv_ids=["9999.99999"]
                )

    def test_gold_dir_must_be_external_to_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            inside = workspace / "benchmark" / "gold"
            inside.mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "outside the public workspace"):
                evaluate_scratch_run(workspace, RUN_ID, gold_dir=inside)


if __name__ == "__main__":
    unittest.main()
