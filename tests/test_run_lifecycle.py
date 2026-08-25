"""Run-lifecycle invariants: frozen runs, resumability, one-way finalize."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from stella.workflow_runtime import (
    RunEvent,
    append_event,
    attempt_allowed,
    create_run,
    finalize_run,
    load_run,
    paper_status,
    record_paper_result,
    resume_eligible_papers,
)
from stella.workflows import Authorities, LiteraturePipelineRequest

WF = "literature_pipeline"


def _request(papers: list[str]) -> LiteraturePipelineRequest:
    return LiteraturePipelineRequest(
        papers=papers,
        authorities=Authorities(execute=True, llm=True),
    )


class RunLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        create_run(
            root=self.root,
            workflow_id=WF,
            request=_request(["2601.00001", "2601.00002"]),
            run_id="run-1",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_frozen_request_survives_reload(self) -> None:
        state = load_run(self.root, WF, "run-1")
        self.assertEqual(state["request"]["papers"], ["2601.00001", "2601.00002"])
        self.assertEqual(state["state"], "active")

    def test_successful_paper_cannot_be_retried(self) -> None:
        record_paper_result(self.root, WF, "run-1", "2601.00001", "complete")
        self.assertFalse(attempt_allowed(self.root, WF, "run-1", "2601.00001"))
        self.assertTrue(attempt_allowed(self.root, WF, "run-1", "2601.00002"))

    def test_pending_status_stays_resumable_pending(self) -> None:
        record_paper_result(self.root, WF, "run-1", "2601.00002", "pending")
        self.assertEqual(
            paper_status(self.root, WF, "run-1", "2601.00002"), "pending"
        )

    def test_only_unfinished_or_network_failed_papers_resume(self) -> None:
        for paper, status in (
            ("2601.00001", "complete"),
            ("2601.00002", "failed"),
            ("2601.00003", "network_failed"),
            ("2601.00005", "partial"),
        ):
            record_paper_result(self.root, WF, "run-1", paper, status)
        eligible = resume_eligible_papers(
            self.root, WF, "run-1", ["2601.00001", "2601.00002", "2601.00003", "2601.00004", "2601.00005"]
        )
        self.assertEqual(eligible, ["2601.00003", "2601.00004"])

    def test_finalized_run_rejects_all_new_attempts(self) -> None:
        record_paper_result(self.root, WF, "run-1", "2601.00001", "complete")
        final = finalize_run(self.root, WF, "run-1")
        self.assertEqual(final, "partial")
        self.assertFalse(attempt_allowed(self.root, WF, "run-1", "2601.00001"))
        self.assertFalse(attempt_allowed(self.root, WF, "run-1", "2601.00002"))
        with self.assertRaises(ValueError):
            finalize_run(self.root, WF, "run-1")

    def test_events_and_attempts_are_append_only(self) -> None:
        record_paper_result(
            self.root, WF, "run-1", "2601.00001", "complete", attempt="op-1"
        )
        record_paper_result(
            self.root, WF, "run-1", "2601.00001", "complete", attempt="op-2"
        )
        papers_dir = self.root / "runs" / WF / "run-1" / "papers" / "2601.00001"
        self.assertTrue((papers_dir / "attempts" / "op-1" / "result.json").is_file())
        self.assertTrue((papers_dir / "attempts" / "op-2" / "result.json").is_file())
        append_event(
            self.root,
            WF,
            "run-1",
            RunEvent(event="attempt_finished", paper_id="2601.00001"),
        )
        events = (
            (self.root / "runs" / WF / "run-1" / "events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        self.assertEqual(len(events), 2)


if __name__ == "__main__":
    unittest.main()
