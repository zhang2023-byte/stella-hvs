"""finalize_and_archive paper assembly tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from stella.hvs_extraction.finalize import (
    FIELD_EXTRACTION_FAILED,
    PAPER_COMPLETE,
    PAPER_FAILED,
    PAPER_PARTIAL,
    assemble_paper_result,
)


ARXIV_ID = "2406.99996"
RUN_ID = "run-finalize-test"


def paper_dir(workspace: Path) -> Path:
    path = (
        workspace
        / "benchmark/campaigns/hvs-extraction-v6/runs"
        / RUN_ID
        / "papers"
        / ARXIV_ID
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


def roster_final(status: str = "roster_complete", candidates: list[dict] | None = None) -> dict:
    return {
        "schema": {"name": "hvs_extraction.roster_final", "version": 1},
        "paper": {"arxiv_id": ARXIV_ID},
        "run_id": RUN_ID,
        "status": status,
        "roster_status": "candidates_found" if candidates else "no_candidates",
        "failure": {"code": "insufficient_valid_proposals"} if status == "roster_failed" else None,
        "candidates": candidates or [],
        "reviewed_exclusions": [],
        "proposals": {"slots": [], "label_mapping": None},
        "provenance": {"extractor": {"model": "deepseek-v4-pro"}},
    }


def candidate_stub(index: int) -> dict:
    return {
        "record_id": f"candidate-{index:03d}",
        "display_name": f"HVS-{index}",
        "identifiers": [],
        "qualification": {"reason": "r", "source_refs": []},
    }


def candidate_artifact(record_id: str, status: str = "fields_complete") -> dict:
    return {
        "schema": {"name": "hvs_extraction.candidate_fields", "version": 1},
        "paper": {"arxiv_id": ARXIV_ID},
        "run_id": RUN_ID,
        "record_id": record_id,
        "status": status,
        "fields": {"core": {}} if status == "fields_complete" else None,
        "bibliography": None,
        "failure": None
        if status == "fields_complete"
        else {"code": "submission_format_failure", "attempts": []},
        "attempts": [],
        "usages": [],
        "provenance": {"model": "deepseek-v4-pro"},
    }


def setup(workspace: Path, roster: dict, candidate_records: list[dict]) -> None:
    directory = paper_dir(workspace)
    (directory / "roster_final.json").write_text(
        json.dumps(roster), encoding="utf-8"
    )
    candidates_dir = directory / "candidates"
    candidates_dir.mkdir(exist_ok=True)
    for record in candidate_records:
        (candidates_dir / f"{record['record_id']}.json").write_text(
            json.dumps(record), encoding="utf-8"
        )


class FinalizeTest(unittest.TestCase):
    def test_complete_with_all_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            candidates = [candidate_stub(1), candidate_stub(2)]
            setup(
                workspace,
                roster_final(candidates=candidates),
                [candidate_artifact("candidate-001"), candidate_artifact("candidate-002")],
            )
            result = assemble_paper_result(
                workspace, RUN_ID, ARXIV_ID
            )
            self.assertEqual(result["status"], PAPER_COMPLETE)
            self.assertEqual(
                [entry["record_id"] for entry in result["candidates"]],
                ["candidate-001", "candidate-002"],
            )
            self.assertEqual(result["roster"]["candidates"], candidates)
            self.assertIsNone(result["failure"])

    def test_partial_keeps_failed_candidate_in_roster_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            candidates = [candidate_stub(1), candidate_stub(2), candidate_stub(3)]
            setup(
                workspace,
                roster_final(candidates=candidates),
                [
                    candidate_artifact("candidate-001"),
                    candidate_artifact("candidate-002", status="field_extraction_failed"),
                    # candidate-003 artifact missing: crash before persistence.
                ],
            )
            result = assemble_paper_result(
                workspace, RUN_ID, ARXIV_ID
            )
            self.assertEqual(result["status"], PAPER_PARTIAL)
            statuses = [entry["status"] for entry in result["candidates"]]
            self.assertEqual(
                statuses,
                ["fields_complete", "field_extraction_failed", "field_extraction_failed"],
            )
            third = result["candidates"][2]
            self.assertEqual(third["failure"]["code"], "missing_candidate_artifact")
            self.assertIsNone(third["fields"])
            # The failed candidate is not dropped and no record is synthesized.
            self.assertEqual(third["record_id"], "candidate-003")

    def test_empty_roster_is_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            setup(workspace, roster_final(candidates=[]), [])
            result = assemble_paper_result(
                workspace, RUN_ID, ARXIV_ID
            )
            self.assertEqual(result["status"], PAPER_COMPLETE)
            self.assertEqual(result["candidates"], [])

    def test_all_candidates_failed_is_partial_not_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            candidates = [candidate_stub(1)]
            setup(
                workspace,
                roster_final(candidates=candidates),
                [candidate_artifact("candidate-001", status="field_extraction_failed")],
            )
            result = assemble_paper_result(
                workspace, RUN_ID, ARXIV_ID
            )
            self.assertEqual(result["status"], PAPER_PARTIAL)
            self.assertEqual(result["roster"]["candidates"], candidates)

    def test_roster_failure_is_paper_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            setup(workspace, roster_final(status="roster_failed"), [])
            result = assemble_paper_result(
                workspace, RUN_ID, ARXIV_ID
            )
            self.assertEqual(result["status"], PAPER_FAILED)
            self.assertEqual(
                result["failure"]["code"], "insufficient_valid_proposals"
            )
            self.assertEqual(result["candidates"], [])

    def test_missing_roster_artifact_is_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            paper_dir(workspace)
            result = assemble_paper_result(
                workspace, RUN_ID, ARXIV_ID
            )
            self.assertEqual(result["status"], PAPER_FAILED)
            self.assertEqual(result["failure"]["code"], "missing_roster_artifact")


if __name__ == "__main__":
    unittest.main()
