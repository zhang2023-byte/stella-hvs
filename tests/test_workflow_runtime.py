"""Tests for the initial run state and event models of the runtime."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from stella.workflow_runtime import (
    RunEvent,
    append_event,
    create_run,
    load_run,
)
from stella.workflows import Authorities, LiteraturePipelineRequest

WORKFLOW_ID = "literature_pipeline"


def _request() -> LiteraturePipelineRequest:
    return LiteraturePipelineRequest(
        papers=["2601.08888"],
        authorities=Authorities(execute=True, network=True, llm=True),
    )


class CreateRunTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.run = create_run(
            root=self.root,
            workflow_id=WORKFLOW_ID,
            request=_request(),
            run_id="run-0001",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_run_directory_layout_is_created(self) -> None:
        run_dir = self.root / "runs" / WORKFLOW_ID / "run-0001"
        self.assertTrue((run_dir / "run.json").is_file())
        self.assertTrue((run_dir / "events.jsonl").is_file())
        self.assertTrue((run_dir / "papers").is_dir())

    def test_run_json_freezes_normalized_request(self) -> None:
        loaded = load_run(self.root, WORKFLOW_ID, "run-0001")
        self.assertEqual(loaded["workflow_id"], WORKFLOW_ID)
        self.assertEqual(loaded["request"]["papers"], ["2601.08888"])
        self.assertEqual(loaded["request"]["authorities"]["llm"], True)
        self.assertIn("created_at", loaded)

    def test_run_created_event_is_recorded(self) -> None:
        events = self._events()
        self.assertEqual(events[0]["event"], "run_created")
        self.assertEqual(events[0]["workflow_id"], WORKFLOW_ID)

    def test_appended_events_stay_in_order(self) -> None:
        append_event(
            self.root,
            WORKFLOW_ID,
            "run-0001",
            RunEvent(event="attempt_started", paper_id="2601.08888"),
        )
        events = self._events()
        self.assertEqual(
            [event["event"] for event in events],
            ["run_created", "attempt_started"],
        )

    def test_run_json_cannot_be_silently_replaced(self) -> None:
        from stella.workflow_runtime import save_run_state

        loaded = load_run(self.root, WORKFLOW_ID, "run-0001")
        loaded["request"]["papers"].append("9999.9999")
        with self.assertRaises(ValueError):
            save_run_state(self.root, WORKFLOW_ID, "run-0001", loaded)

    def _events(self) -> list[dict]:
        path = self.root / "runs" / WORKFLOW_ID / "run-0001" / "events.jsonl"
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


class RunGateOrderingTest(unittest.TestCase):
    """Authority failures happen before any run directory exists."""

    def test_missing_authority_fails_before_run_directory_created(self) -> None:
        import tempfile

        from stella.workflows import Authorities, LiteraturePipelineRequest
        from stella.workflows import StellaError
        from stella.workflow_runtime import run_workflow

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = LiteraturePipelineRequest(
                papers=["2601.08888"],
                authorities=Authorities(execute=True),
            )
            with self.assertRaises(StellaError) as ctx:
                run_workflow(
                    root=root,
                    workflow_id="literature_pipeline",
                    request=request,
                )
            self.assertEqual(ctx.exception.code, "MISSING_AUTHORITY")
            self.assertFalse((root / "runs").exists())

    def test_empty_paper_statuses_never_synthesize_complete(self) -> None:
        from stella.workflow_runtime import _summarize_statuses

        self.assertEqual(_summarize_statuses([]), "failed")

    def test_partial_operation_keeps_the_worker_chain_partial(self) -> None:
        from stella.workflow_runtime import _merge_chain_status

        status = _merge_chain_status("complete", "partial")
        self.assertEqual(status, "partial")
        self.assertEqual(_merge_chain_status(status, "complete"), "partial")
        self.assertEqual(_merge_chain_status(status, "failed"), "failed")


if __name__ == "__main__":
    unittest.main()
