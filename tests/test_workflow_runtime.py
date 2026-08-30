"""Tests for the initial run state and event models of the runtime."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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
    def test_benchmark_uses_frozen_request_concurrency_not_environment(self) -> None:
        from stella.workflow_runtime import _initial_concurrency

        with patch.dict(os.environ, {"STELLA_RUN_CONCURRENCY": "2"}):
            self.assertEqual(
                _initial_concurrency(
                    "benchmark",
                    {"execution_policy": {"paper_workers": 10}},
                ),
                10,
            )

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

    def test_interrupted_worker_keeps_run_resumable(self) -> None:
        from stella.workflow_runtime import _summarize_statuses

        self.assertEqual(_summarize_statuses(["complete", "interrupted"]), "interrupted")


class WorkerIsolationTest(unittest.TestCase):
    def test_explicit_worker_timeout_becomes_structured_interruption(self) -> None:
        from stella.workflow_runtime import _spawn_paper_worker

        with tempfile.TemporaryDirectory() as tmp, patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["python"], timeout=1),
        ):
            result = _spawn_paper_worker(
                root=Path(tmp),
                workflow_id="benchmark",
                run_id="run-timeout",
                operations=[SimpleNamespace(id="benchmark.execute")],
                paper_id="2601.00001",
                payload={},
                result_path=Path(tmp) / "worker-result.json",
                env_extra={"STELLA_WORKER_TIMEOUT": "1"},
            )

        self.assertEqual(result["status"], "interrupted")
        self.assertEqual(result["operations"][0]["result"]["status"], "interrupted")
        self.assertEqual(result["failure"]["kind"], "timeout")

    def test_attempt_ids_are_atomically_reserved(self) -> None:
        from stella.workflow_runtime import _reserve_attempt_id

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            first = _reserve_attempt_id(directory, "2601.00001", "benchmark.execute")
            second = _reserve_attempt_id(directory, "2601.00001", "benchmark.execute")

        self.assertEqual(first, "benchmark.execute-1")
        self.assertEqual(second, "benchmark.execute-2")

    def test_single_worker_slot_emits_events_at_real_lifecycle_boundaries(self) -> None:
        from stella.workflow_runtime import _run_papers_bounded

        papers = ["2601.00001", "2601.00002"]
        operation = SimpleNamespace(id="test.operation")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_run(
                root=root,
                workflow_id=WORKFLOW_ID,
                request=LiteraturePipelineRequest(
                    papers=papers,
                    authorities=Authorities(execute=True),
                ),
                run_id="run-events",
            )
            outcomes = [
                {
                    "paper_id": paper,
                    "status": "complete",
                    "operations": [
                        {
                            "operation_id": operation.id,
                            "result": {"status": "complete"},
                        }
                    ],
                }
                for paper in papers
            ]
            with patch(
                "stella.workflow_runtime._spawn_paper_worker",
                side_effect=outcomes,
            ):
                _run_papers_bounded(
                    root=root,
                    workflow_id=WORKFLOW_ID,
                    run_id="run-events",
                    operations=[operation],
                    payload={},
                    papers=papers,
                    env_extra={},
                    concurrency=1,
                )
            events_path = (
                root / "runs" / WORKFLOW_ID / "run-events" / "events.jsonl"
            )
            events = [
                json.loads(line)
                for line in events_path.read_text(encoding="utf-8").splitlines()
            ]
            lifecycle = [
                (event["event"], event.get("paper_id"))
                for event in events
                if event["event"].startswith("paper_worker_")
            ]

        self.assertEqual(
            lifecycle,
            [
                ("paper_worker_queued", papers[0]),
                ("paper_worker_queued", papers[1]),
                ("paper_worker_started", papers[0]),
                ("paper_worker_finished", papers[0]),
                ("paper_worker_started", papers[1]),
                ("paper_worker_finished", papers[1]),
            ],
        )


if __name__ == "__main__":
    unittest.main()
