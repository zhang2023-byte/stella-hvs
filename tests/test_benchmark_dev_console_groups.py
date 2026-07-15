from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from stella.benchmark.dev_console import DevConsoleController, DevConsoleError
from stella.benchmark.dev_console_evaluation import DevEvaluationService
from stella.benchmark.dev_console_groups import ExperimentGroupStore
from stella.schema_registry import ACTIVE_BENCHMARK_CAMPAIGN


def run_request(run_id: str, method: str = "B") -> dict:
    return {
        "method": method,
        "run_id": run_id,
        "experiment_name": f"Experiment {run_id}",
        "extractor_model": "extractor-model",
        "reviewer_model": "reviewer-model",
        "task_surface": "full",
        "parallel": 1,
        "max_repair_rounds": 3,
        "timeout_seconds": 1800,
        "batch_size": 8,
        "max_tokens": None,
        "provider_pin": True,
        "providers": [],
        "fallback_models": [],
        "stream_responses": False,
    }


class ExperimentGroupStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.statuses: dict[str, str] = {}
        self.launches: list[tuple[str, bool]] = []
        self.stops: list[str] = []

        def launch(request: dict, resume: bool) -> dict:
            run_id = request["run_id"]
            self.launches.append((run_id, resume))
            self.statuses[run_id] = "running"
            return {"status": "running", "started_at": "2026-07-14T00:00:00+00:00"}

        self.store = ExperimentGroupStore(
            self.root,
            campaign_id=ACTIVE_BENCHMARK_CAMPAIGN,
            launch=launch,
            stop=lambda run_id: self.stops.append(run_id) or {"status": "stop_requested"},
            status=lambda run_id: {"status": self.statuses[run_id]},
            scheduler=False,
        )

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    def test_parallel_limit_queues_remaining_experiments(self) -> None:
        group = self.store.create(
            group_id="group-a",
            max_parallel_experiments=2,
            requests=[run_request("run-a"), run_request("run-b", "C"), run_request("run-c")],
        )
        self.assertEqual(self.launches, [("run-a", False), ("run-b", False)])
        self.assertEqual([item["status"] for item in group["experiments"]], ["running", "running", "queued"])
        self.statuses["run-a"] = "completed"
        group = self.store.tick("group-a")
        self.assertEqual(self.launches[-1], ("run-c", False))
        self.assertEqual([item["status"] for item in group["experiments"]], ["completed", "running", "running"])

    def test_stop_pauses_queue_and_resume_uses_paper_checkpoint_mode(self) -> None:
        self.store.create(
            group_id="group-stop",
            max_parallel_experiments=1,
            requests=[run_request("run-a"), run_request("run-b")],
        )
        stopped = self.store.stop("group-stop")
        self.assertTrue(stopped["paused"])
        self.assertEqual(self.stops, ["run-a"])
        self.statuses["run-a"] = "stopped"
        self.store.tick("group-stop")
        resumed = self.store.resume("group-stop")
        self.assertFalse(resumed["paused"])
        self.assertIn(("run-a", True), self.launches)
        self.assertNotIn(("run-b", False), self.launches[1:])

    def test_restart_reconciles_active_run_without_launching_duplicate(self) -> None:
        self.store.create(
            group_id="group-restart",
            max_parallel_experiments=1,
            requests=[run_request("run-a"), run_request("run-b")],
        )
        self.assertEqual(self.launches, [("run-a", False)])
        reopened = ExperimentGroupStore(
            self.root,
            campaign_id=ACTIVE_BENCHMARK_CAMPAIGN,
            launch=lambda request, resume: self.launches.append((request["run_id"], resume)) or {"status": "running"},
            stop=lambda _: {},
            status=lambda run_id: {"status": self.statuses[run_id]},
            scheduler=False,
        )
        try:
            reopened.tick("group-restart")
            self.assertEqual(self.launches, [("run-a", False)])
            self.statuses["run-a"] = "completed"
            reopened.tick("group-restart")
            self.assertEqual(self.launches[-1], ("run-b", False))
        finally:
            reopened.close()

    def test_one_launch_failure_does_not_block_other_experiment(self) -> None:
        def launch(request: dict, _: bool) -> dict:
            if request["run_id"] == "bad-run":
                raise RuntimeError("provider setup failed")
            return {"status": "running"}

        store = ExperimentGroupStore(
            self.root / "isolated",
            campaign_id=ACTIVE_BENCHMARK_CAMPAIGN,
            launch=launch,
            stop=lambda _: {},
            status=lambda _: {"status": "running"},
            scheduler=False,
        )
        try:
            group = store.create(group_id="group-failure", max_parallel_experiments=2, requests=[run_request("bad-run"), run_request("good-run")])
        finally:
            store.close()
        self.assertEqual([item["status"] for item in group["experiments"]], ["failed", "running"])

    def test_failed_group_cannot_use_broad_resume(self) -> None:
        self.store.create(
            group_id="group-review",
            max_parallel_experiments=1,
            requests=[run_request("run-failed")],
        )
        self.statuses["run-failed"] = "failed"
        group = self.store.tick("group-review")
        self.assertEqual(group["status"], "needs_review")
        with self.assertRaisesRegex(ValueError, "external-failure"):
            self.store.resume("group-review")

    def test_direct_external_retry_rejoins_owning_group(self) -> None:
        self.store.create(
            group_id="group-retry",
            max_parallel_experiments=1,
            requests=[run_request("run-external")],
        )
        self.statuses["run-external"] = "failed"
        self.store.tick("group-retry")
        self.store.mark_external_retry(
            "run-external",
            {"status": "running", "started_at": "2026-07-15T00:00:00+00:00"},
        )
        self.statuses["run-external"] = "running"
        group = self.store.read("group-retry")
        self.assertEqual(group["status"], "running")
        self.assertEqual(group["experiments"][0]["status"], "running")
        self.assertEqual(group["experiments"][0]["queue_mode"], "resume")


class DevConsoleResetTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace_tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.workspace_tmp.name)
        self.logs = self.workspace / "logs"
        self.controller = DevConsoleController(self.workspace, logs_root=self.logs)

    def tearDown(self) -> None:
        self.controller.close()
        self.workspace_tmp.cleanup()

    def run_dir(self, run_id: str) -> Path:
        return self.workspace / "benchmark" / "campaigns" / ACTIVE_BENCHMARK_CAMPAIGN / "runs" / run_id

    def test_reset_removes_only_declared_run_and_trace_directories(self) -> None:
        run_id = "reset-me"
        run_dir = self.run_dir(run_id)
        run_dir.mkdir(parents=True)
        (run_dir / "partial.json").write_text("{}")
        trace_dir = self.logs / ACTIVE_BENCHMARK_CAMPAIGN / run_id
        trace_dir.mkdir(parents=True)
        (trace_dir / "events.jsonl").write_text("")
        sibling = self.run_dir("keep-me")
        sibling.mkdir(parents=True)
        result = self.controller.reset_run(run_id, {"confirm_run_id": run_id})
        self.assertEqual(result["status"], "reset")
        self.assertFalse(run_dir.exists())
        self.assertFalse(trace_dir.exists())
        self.assertTrue(sibling.exists())

    def test_reset_requires_exact_confirmation_and_rejects_sealed_run(self) -> None:
        run_id = "sealed-run"
        run_dir = self.run_dir(run_id)
        run_dir.mkdir(parents=True)
        with self.assertRaisesRegex(DevConsoleError, "exactly match"):
            self.controller.reset_run(run_id, {"confirm_run_id": "other"})
        (run_dir / "run_manifest.json").write_text("{}")
        with self.assertRaisesRegex(DevConsoleError, "sealed"):
            self.controller.reset_run(run_id, {"confirm_run_id": run_id})

    def test_reset_rejects_an_active_run(self) -> None:
        run_id = "active-run"
        self.run_dir(run_id).mkdir(parents=True)
        with mock.patch.object(self.controller, "_active_process_group", return_value=1234):
            with self.assertRaisesRegex(DevConsoleError, "stop the active run"):
                self.controller.reset_run(run_id, {"confirm_run_id": run_id})


class FakeGroups:
    def __init__(self, root: Path, group: dict) -> None:
        self.root = root
        self.group = group
        self.events: list[dict] = []

    def evaluation_root(self, group_id: str) -> Path:
        return self.root / group_id / "evaluation"

    def read(self, _: str) -> dict:
        return self.group

    def emit(self, group_id: str, event_type: str, **values: object) -> dict:
        event = {"group_id": group_id, "type": event_type, **values}
        self.events.append(event)
        return event


class DevEvaluationServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace_tmp = tempfile.TemporaryDirectory()
        self.private_tmp = tempfile.TemporaryDirectory()
        self.logs_tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.workspace_tmp.name)
        self.gold = Path(self.private_tmp.name) / "gold"
        self.gold.mkdir()
        self.run_id = "eval-run"
        campaign = self.workspace / "benchmark" / "campaigns" / ACTIVE_BENCHMARK_CAMPAIGN
        (campaign / "manifest").mkdir(parents=True)
        (campaign / "manifest" / "gold_manifest.json").write_text("{}")
        self.run_dir = campaign / "runs" / self.run_id
        self.run_dir.mkdir(parents=True)
        (self.run_dir / "run_config.json").write_text("{}")
        self.groups = FakeGroups(
            Path(self.logs_tmp.name),
            {"experiments": [{"run_id": self.run_id, "status": "completed", "request": run_request(self.run_id)}]},
        )

    def tearDown(self) -> None:
        self.workspace_tmp.cleanup()
        self.private_tmp.cleanup()
        self.logs_tmp.cleanup()

    def test_preflight_requires_external_private_store_without_exposing_content(self) -> None:
        service = DevEvaluationService(self.workspace, groups=self.groups, campaign_id=ACTIVE_BENCHMARK_CAMPAIGN)
        with mock.patch.dict(os.environ, {"STELLA_GOLD_DIR": str(self.gold)}, clear=False):
            result = service.preflight("group-eval", {"run_ids": [self.run_id]})
        self.assertTrue(result["ok"])
        self.assertNotIn("details", result)
        self.assertNotIn("annotations", result)

    def test_incomplete_run_requires_explicit_unavailable_acknowledgement(self) -> None:
        self.groups.group["experiments"][0]["status"] = "failed"
        service = DevEvaluationService(self.workspace, groups=self.groups, campaign_id=ACTIVE_BENCHMARK_CAMPAIGN)
        with mock.patch.dict(os.environ, {"STELLA_GOLD_DIR": str(self.gold)}, clear=False):
            blocked = service.preflight("group-eval", {"run_ids": [self.run_id]})
            allowed = service.preflight(
                "group-eval",
                {"run_ids": [self.run_id], "allow_unavailable": True},
            )
        self.assertFalse(blocked["ok"])
        self.assertTrue(allowed["ok"])

    def test_interrupted_evaluation_is_reconciled_after_restart(self) -> None:
        service = DevEvaluationService(self.workspace, groups=self.groups, campaign_id=ACTIVE_BENCHMARK_CAMPAIGN)
        service._write_state(
            "group-restarted",
            {
                "evaluation_id": "eval-old",
                "status": "running",
                "run_ids": [self.run_id],
                "runs": {self.run_id: {"status": "running", "stage": "score"}},
            },
        )
        state = service.get("group-restarted")
        self.assertEqual(state["status"], "failed")
        self.assertIn("restart", state["error"])
        self.assertEqual(state["runs"][self.run_id]["status"], "failed")

    def test_audit_seal_score_pipeline_writes_only_local_aggregate_card(self) -> None:
        scorecard = {
            "schema": {"name": "benchmark.scorecard", "version": 2},
            "run_label": self.run_id,
            "l1": {"micro": {"f1": 0.5}, "per_paper": []},
            "l2": {"micro": {"coverage": 0.5}},
        }
        commands: list[list[str]] = []

        def run_command(args: list[str], **_: object) -> subprocess.CompletedProcess:
            commands.append(args)
            script = Path(args[1]).name
            if script == "audit_extraction_run.py":
                report = Path(args[args.index("--report") + 1])
                report.write_text(json.dumps({"status": "clean", "hits": []}))
            elif script == "seal_benchmark_run.py":
                (self.run_dir / "run_manifest.json").write_text(json.dumps({"leakage_audit": {"status": "clean"}}))
            elif script == "score_benchmark_run.py":
                scoring = Path(args[args.index("--scoring-dir") + 1]) / self.run_id
                scoring.mkdir(parents=True)
                (scoring / "scorecard.json").write_text(json.dumps(scorecard))
            return subprocess.CompletedProcess(args, 0, "", "")

        service = DevEvaluationService(
            self.workspace,
            groups=self.groups,
            campaign_id=ACTIVE_BENCHMARK_CAMPAIGN,
            run_command=run_command,
        )
        with mock.patch.dict(os.environ, {"STELLA_GOLD_DIR": str(self.gold)}, clear=False):
            service.start("group-eval", {"run_ids": [self.run_id]})
            deadline = time.monotonic() + 3
            while service.get("group-eval")["status"] in {"queued", "running"} and time.monotonic() < deadline:
                time.sleep(0.01)
        self.assertEqual(service.get("group-eval")["status"], "completed")
        self.assertEqual(service.scorecards("group-eval"), [scorecard])
        state_text = json.dumps(service.get("group-eval"))
        self.assertNotIn("details", state_text)
        self.assertFalse((self.workspace / "report" / "index.html").exists())
        score_command = next(args for args in commands if Path(args[1]).name == "score_benchmark_run.py")
        self.assertNotIn("--campaign", score_command)
        self.assertEqual(Path(score_command[score_command.index("--run-dir") + 1]).resolve(), self.run_dir.resolve())
        self.assertEqual(
            Path(score_command[score_command.index("--scoring-dir") + 1]).resolve(),
            (self.groups.evaluation_root("group-eval") / "scorecards").resolve(),
        )
        self.assertTrue(
            Path(score_command[score_command.index("--details-dir") + 1]).resolve().is_relative_to(
                (self.gold.parent / "scoring-details" / "dev-console").resolve()
            )
        )

    def test_contaminated_audit_reports_only_files_and_counts(self) -> None:
        marker = "PRIVATE-CANARY-DO-NOT-RETURN"

        def run_command(args: list[str], **_: object) -> subprocess.CompletedProcess:
            report = Path(args[args.index("--report") + 1])
            report.write_text(json.dumps({"status": "contaminated", "hits": [{"file": "run/output.json", "marker": marker}]}))
            return subprocess.CompletedProcess(args, 1, "", "")

        service = DevEvaluationService(self.workspace, groups=self.groups, campaign_id=ACTIVE_BENCHMARK_CAMPAIGN, run_command=run_command)
        with mock.patch.dict(os.environ, {"STELLA_GOLD_DIR": str(self.gold)}, clear=False):
            service.start("group-contaminated", {"run_ids": [self.run_id]})
            deadline = time.monotonic() + 3
            while service.get("group-contaminated")["status"] in {"queued", "running"} and time.monotonic() < deadline:
                time.sleep(0.01)
        state = service.get("group-contaminated")
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["runs"][self.run_id]["contaminated_files"], ["run/output.json"])
        self.assertEqual(state["runs"][self.run_id]["hit_count"], 1)
        self.assertNotIn(marker, json.dumps(state))


if __name__ == "__main__":
    unittest.main()
