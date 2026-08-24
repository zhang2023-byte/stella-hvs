"""One fresh subprocess owns each paper's ordered operation chain.

For a multi-operation, two-paper workflow run: exactly one worker PID per
paper executes that paper's whole chain in declared phase order, receives
only its own paper, a paper-local failure skips its downstream operations,
the other paper still completes, and the outer run persists its terminal
state. No real network, provider, or private-gold access occurs.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from stella import workflow_runtime
from stella.workflows import Authorities, LiteraturePipelineRequest
from tests.integration.netguard import guard
from tests.hvs_contribution_fixtures import (
    ARXIV_ID,
    MEASUREMENT_ARXIV_ID,
    MEASUREMENT_ROSTER_SUBMISSION,
    MEASUREMENT_SUBMISSION,
    frozen_contribution_config,
    make_measurement_workspace,
)

ROOT = Path(__file__).resolve().parents[2]
CHAIN_PHASES = ["archive", "contributions"]


def _success_responses() -> list[dict]:
    return [
        {
            "tool_name": "submit_contribution_roster",
            "arguments": MEASUREMENT_ROSTER_SUBMISSION,
        },
        {
            "tool_name": "submit_object_quantities",
            "arguments": MEASUREMENT_SUBMISSION,
        },
    ]


class WorkerIsolationTest(unittest.TestCase):
    def setUp(self) -> None:
        guard(self)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _merge_measurement_workspace(self.root)
        transcripts = self.root / "worker" / "transcripts"
        transcripts.mkdir(parents=True)
        config_path = self.root / "worker" / "method_config.json"
        config_path.write_text(
            json.dumps(
                frozen_contribution_config().model_dump(mode="json", by_alias=True)
            ),
            encoding="utf-8",
        )
        (transcripts / f"{MEASUREMENT_ARXIV_ID}.json").write_text(
            json.dumps({"responses": _success_responses()}), encoding="utf-8"
        )
        # ARXIV_ID gets no transcript: it never reaches extraction here
        # because its archive operation fails on missing assets.
        self.env = {
            "STELLA_WORKER_METHOD_CONFIG": str(config_path),
            "STELLA_WORKER_TRANSCRIPT": str(transcripts),
        }

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _request(self, papers: list[str]) -> LiteraturePipelineRequest:
        return LiteraturePipelineRequest(
            papers=papers,
            phases=CHAIN_PHASES,
            authorities=Authorities(execute=True, llm=True, network=True),
        )

    def _run(self, papers: list[str], run_id: str) -> dict:
        return workflow_runtime.run_workflow(
            root=self.root,
            workflow_id="literature_pipeline",
            request=self._request(papers),
            run_id=run_id,
            env_extra=self.env,
        )

    def _attempts(self, run_id: str, paper_id: str) -> list[str]:
        base = (
            self.root
            / "runs"
            / "literature_pipeline"
            / run_id
            / "papers"
            / paper_id
            / "attempts"
        )
        return sorted(path.name for path in base.glob("*")) if base.is_dir() else []

    def _telemetry(self, run_id: str, paper_id: str, attempt: str) -> dict:
        path = (
            self.root
            / "runs"
            / "literature_pipeline"
            / run_id
            / "papers"
            / paper_id
            / "attempts"
            / attempt
            / "telemetry.json"
        )
        return json.loads(path.read_text(encoding="utf-8"))

    def test_one_worker_pid_owns_each_papers_ordered_chain(self) -> None:
        summary = self._run([MEASUREMENT_ARXIV_ID], "iso-one")
        self.assertEqual(summary["status"], "complete")
        attempts = self._attempts("iso-one", MEASUREMENT_ARXIV_ID)
        self.assertEqual(
            attempts,
            [
                "literature.archive_assets-1",
                "literature.extract_contributions-1",
            ],
        )
        pids = {
            self._telemetry("iso-one", MEASUREMENT_ARXIV_ID, attempt)["worker_pid"]
            for attempt in attempts
        }
        self.assertEqual(
            len(pids),
            1,
            "one paper must be owned by exactly one fresh worker process",
        )
        worker_pid = next(iter(pids))
        self.assertNotEqual(worker_pid, os.getpid())
        for attempt in attempts:
            telemetry = self._telemetry(
                "iso-one", MEASUREMENT_ARXIV_ID, attempt
            )
            self.assertEqual(telemetry["papers"], [MEASUREMENT_ARXIV_ID])

    def test_paper_failure_skips_downstream_and_other_paper_completes(self) -> None:
        # ARXIV_ID has no archived assets: its archive operation fails, so its
        # contribution extraction must never start; the measurement paper
        # still completes with its own worker.
        summary = self._run([MEASUREMENT_ARXIV_ID, ARXIV_ID], "iso-two")
        self.assertEqual(summary["status"], "partial")
        failing_attempts = self._attempts("iso-two", ARXIV_ID)
        self.assertEqual(
            failing_attempts,
            ["literature.archive_assets-1"],
            "a failed paper operation must skip its downstream operations",
        )
        self.assertEqual(
            self._attempts("iso-two", MEASUREMENT_ARXIV_ID),
            [
                "literature.archive_assets-1",
                "literature.extract_contributions-1",
            ],
        )
        failing_pid = self._telemetry(
            "iso-two", ARXIV_ID, "literature.archive_assets-1"
        )["worker_pid"]
        success_pid = self._telemetry(
            "iso-two", MEASUREMENT_ARXIV_ID, "literature.archive_assets-1"
        )["worker_pid"]
        self.assertNotEqual(failing_pid, success_pid)

    def test_outer_run_state_is_persisted_not_in_memory_only(self) -> None:
        self._run([MEASUREMENT_ARXIV_ID], "iso-persist")
        run_json = json.loads(
            (
                self.root
                / "runs"
                / "literature_pipeline"
                / "iso-persist"
                / "run.json"
            ).read_text(encoding="utf-8")
        )
        self.assertIn(run_json.get("state"), ("complete", "partial", "failed"))
        self.assertTrue(
            (
                self.root / "runs" / "literature_pipeline" / "iso-persist" / "summary.json"
            ).is_file()
        )


def _merge_measurement_workspace(root: Path) -> None:
    import shutil

    staged = Path(
        tempfile.mkdtemp(prefix="stella-worker-iso-")
    )
    make_measurement_workspace(staged)
    shutil.copytree(staged / "contracts", root / "contracts", dirs_exist_ok=True)
    shutil.copytree(staged / "literature", root / "literature", dirs_exist_ok=True)
    shutil.rmtree(staged)


if __name__ == "__main__":
    unittest.main()
