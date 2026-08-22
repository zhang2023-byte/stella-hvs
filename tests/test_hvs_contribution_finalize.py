"""Contribution paper-result finalization tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.hvs_contribution_fixtures import (
    ARXIV_ID,
    RUN_ID,
    make_workspace,
)
from stella.hvs_contribution_extraction.finalize import (
    MEASUREMENTS_COMPLETE,
    MEASUREMENT_EXTRACTION_FAILED,
    PAPER_COMPLETE,
    PAPER_FAILED,
    PAPER_PARTIAL,
    assemble_contribution_paper_result,
)


def paper_dir_for(workspace: Path) -> Path:
    return workspace / "local_runs" / "contributions" / RUN_ID / "papers" / ARXIV_ID


class ContributionFinalizeTest(unittest.TestCase):
    def test_missing_measurement_artifact_keeps_contribution_with_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            result = assemble_contribution_paper_result(
                workspace, RUN_ID, ARXIV_ID, run_dir=workspace / "local_runs" / "contributions" / RUN_ID
            )
            self.assertEqual(result["status"], PAPER_PARTIAL)
            self.assertEqual(result["roster_status"], "contributions_found")
            entries = result["object_measurements"]
            self.assertEqual(len(entries), 10)
            entry = entries[0]
            self.assertEqual(entry["status"], MEASUREMENT_EXTRACTION_FAILED)
            self.assertEqual(entry["measurements"], [])
            self.assertEqual(entry["failure"]["code"], "missing_object_artifact")
            # Roster contributions stay complete in the assembled artifact
            # (six direct contributions plus four expanded range members).
            self.assertEqual(len(result["roster"]["object_contributions"]), 10)
            persisted = json.loads(
                (paper_dir_for(workspace) / "paper_result.json").read_text(encoding="utf-8")
            )
            self.assertEqual(persisted["status"], PAPER_PARTIAL)

    def test_successful_measurements_complete_the_paper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            paper_dir = paper_dir_for(workspace)
            objects_dir = paper_dir / "object_measurements"
            objects_dir.mkdir(parents=True)
            for index in range(1, 11):
                record = {
                    "record_id": f"obj-{index:03d}",
                    "status": MEASUREMENTS_COMPLETE,
                    "measurements": [],
                    "failure": None,
                    "attempts": [],
                    "usages": [],
                    "repair_history": [],
                    "provenance": None,
                }
                (objects_dir / f"obj-{index:03d}.json").write_text(
                    json.dumps(record), encoding="utf-8"
                )
            result = assemble_contribution_paper_result(
                workspace, RUN_ID, ARXIV_ID, run_dir=workspace / "local_runs" / "contributions" / RUN_ID
            )
            self.assertEqual(result["status"], PAPER_COMPLETE)
            self.assertTrue(
                all(entry["status"] == MEASUREMENTS_COMPLETE for entry in result["object_measurements"])
            )

    def test_failed_roster_produces_no_trusted_contributions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            roster_path = paper_dir_for(workspace) / "contribution_roster_final.json"
            roster = json.loads(roster_path.read_text(encoding="utf-8"))
            roster["status"] = "roster_failed"
            roster["failure"] = {"code": "extractor_terminal_failure", "detail": "x"}
            roster_path.write_text(json.dumps(roster), encoding="utf-8")
            result = assemble_contribution_paper_result(
                workspace, RUN_ID, ARXIV_ID, run_dir=workspace / "local_runs" / "contributions" / RUN_ID
            )
            self.assertEqual(result["status"], PAPER_FAILED)
            self.assertIsNone(result["roster_status"])
            self.assertEqual(result["object_measurements"], [])
            self.assertEqual(result["failure"]["code"], "extractor_terminal_failure")

    def test_missing_roster_artifact_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            roster_path = paper_dir_for(workspace) / "contribution_roster_final.json"
            roster_path.unlink()
            result = assemble_contribution_paper_result(
                workspace, RUN_ID, ARXIV_ID, run_dir=workspace / "local_runs" / "contributions" / RUN_ID
            )
            self.assertEqual(result["status"], PAPER_FAILED)
            self.assertEqual(result["failure"]["code"], "missing_roster_artifact")


if __name__ == "__main__":
    unittest.main()
