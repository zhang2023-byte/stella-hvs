from __future__ import annotations

import http.client
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from stella.benchmark.dev_console import (
    DevConsoleController,
    DevConsoleError,
    DevRunRequest,
    build_runner_command,
    create_server,
)
from stella.benchmark.run_trace import RunTrace
from stella.schema_registry import ACTIVE_BENCHMARK_CAMPAIGN


ROOT = Path(__file__).resolve().parents[1]


def request_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "method": "B",
        "run_id": "dev-console-test",
        "experiment_name": "Test experiment",
        "extractor_model": "extractor-model",
        "reviewer_model": "reviewer-model",
        "task_surface": "full",
        "parallel": 2,
    }
    payload.update(overrides)
    return payload


class DevRunRequestTest(unittest.TestCase):
    def test_request_accepts_supported_fields_and_deduplicates_lists(self) -> None:
        request = DevRunRequest.from_payload(
            request_payload(
                providers=["deepseek", "deepseek", "openai"],
                fallback_models=["fallback-a", "fallback-a"],
                max_tokens=4096,
            )
        )
        self.assertEqual(request.method, "B")
        self.assertEqual(request.experiment_name, "Test experiment")
        self.assertEqual(request.providers, ("deepseek", "openai"))
        self.assertEqual(request.fallback_models, ("fallback-a",))
        self.assertEqual(request.max_tokens, 4096)

    def test_request_rejects_unsafe_or_nonformal_values(self) -> None:
        for payload in (
            request_payload(method="A"),
            request_payload(run_id="../escape"),
            request_payload(reviewer_model="extractor-model"),
            request_payload(task_surface="summary"),
            request_payload(parallel=11),
            request_payload(experiment_name="\n"),
        ):
            with self.subTest(payload=payload), self.assertRaises(DevConsoleError):
                DevRunRequest.from_payload(payload)

    def test_method_b_command_is_fixed_to_active_dev_contract(self) -> None:
        request = DevRunRequest.from_payload(
            request_payload(
                providers=["deepseek"],
                fallback_models=["fallback-a"],
                provider_pin=False,
                batch_size=4,
            )
        )
        command = build_runner_command(ROOT, ROOT / "logs" / "console", request)
        self.assertEqual(command[0], __import__("sys").executable)
        self.assertIn("run_benchmark_extraction.py", command[1])
        self.assertEqual(command[command.index("--campaign") + 1], ACTIVE_BENCHMARK_CAMPAIGN)
        self.assertEqual(command[command.index("--split") + 1], "dev")
        self.assertIn("--trace-root", command)
        self.assertIn("--stream-responses", command)
        self.assertIn("--no-provider-pin", command)
        self.assertEqual(command[command.index("--provider") + 1], "deepseek")
        self.assertEqual(command[command.index("--fallback-model") + 1], "fallback-a")

    def test_method_c_command_excludes_method_b_transport_options(self) -> None:
        request = DevRunRequest.from_payload(request_payload(method="C"))
        command = build_runner_command(ROOT, ROOT / "logs" / "console", request)
        self.assertIn("run_agentic_extraction.py", command[1])
        self.assertNotIn("--batch-size", command)
        self.assertNotIn("--provider", command)


class DevConsoleHttpTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.controller = DevConsoleController(ROOT, logs_root=Path(self.temporary.name))
        self.server = create_server("127.0.0.1", 0, self.controller)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = int(self.server.server_address[1])

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.controller.close()
        self.temporary.cleanup()

    def fetch(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, object] | None = None,
        token: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers: dict[str, str] = {}
        body: str | None = None
        if payload is not None:
            body = json.dumps(payload)
            headers["Content-Type"] = "application/json"
        if token is not None:
            headers["X-Stella-Console-Token"] = token
        headers.update(extra_headers or {})
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        response_headers = {key.lower(): value for key, value in response.getheaders()}
        status = response.status
        connection.close()
        return status, response_headers, raw

    def test_static_shell_and_bootstrap_are_served_locally(self) -> None:
        status, headers, body = self.fetch("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["content-type"])
        self.assertIn("frame-ancestors 'none'", headers["content-security-policy"])
        self.assertEqual(headers["x-frame-options"], "DENY")
        self.assertEqual(headers["x-content-type-options"], "nosniff")
        self.assertIn(b'id="root"', body)
        self.assertIn(b"/ui/assets/", body)
        status, _, spa_body = self.fetch("GET", "/setup")
        self.assertEqual(status, 200)
        self.assertEqual(spa_body, body)
        status, _, body = self.fetch("GET", "/api/bootstrap")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["campaign_id"], ACTIVE_BENCHMARK_CAMPAIGN)
        self.assertEqual(payload["split"], "dev")
        self.assertEqual(len(payload["papers"]), 10)

    def test_untrusted_host_cannot_read_bootstrap_token(self) -> None:
        status, _, body = self.fetch(
            "GET",
            "/api/bootstrap",
            extra_headers={"Host": "attacker.example"},
        )
        self.assertEqual(status, 400)
        payload = json.loads(body)
        self.assertIn("Host", payload["error"])
        self.assertNotIn("session_token", payload)

    def test_mutation_rejects_untrusted_origin_even_with_valid_token(self) -> None:
        status, _, body = self.fetch(
            "POST",
            "/api/preflight",
            payload=request_payload(),
            token=self.controller.session_token,
            extra_headers={"Origin": "http://attacker.example"},
        )
        self.assertEqual(status, 400)
        self.assertIn("cross-origin", json.loads(body)["error"])

    def test_mutation_requires_session_token(self) -> None:
        status, _, body = self.fetch("POST", "/api/preflight", payload=request_payload())
        self.assertEqual(status, 400)
        self.assertIn("session token", json.loads(body)["error"])

    def test_experiment_group_preflight_route_uses_session_protection(self) -> None:
        result = {
            "ok": True,
            "group_id": "group-http",
            "max_parallel_experiments": 2,
            "group_checks": [],
            "experiments": [],
            "request": {"group_id": "group-http", "max_parallel_experiments": 2, "experiments": []},
        }
        with mock.patch.object(self.controller, "group_preflight", return_value=result) as preflight:
            status, _, body = self.fetch(
                "POST",
                "/api/experiment-groups/preflight",
                payload={"group_id": "group-http", "max_parallel_experiments": 2, "experiments": [request_payload()]},
                token=self.controller.session_token,
            )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["group_id"], "group-http")
        preflight.assert_called_once()

    def test_preflight_returns_checks_and_never_starts_a_process(self) -> None:
        status, _, body = self.fetch(
            "POST",
            "/api/preflight",
            payload=request_payload(),
            token=self.controller.session_token,
        )
        result = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(result["checks"])
        self.assertEqual(result["command"][result["command"].index("--split") + 1], "dev")
        self.assertEqual(self.controller._processes, {})

    def test_exact_trace_is_available_as_one_shot_sse(self) -> None:
        trace = RunTrace(
            Path(self.temporary.name),
            campaign_id=ACTIVE_BENCHMARK_CAMPAIGN,
            run_id="sse-test",
            method="C",
        )
        trace.emit("paper.started", paper_id="1234.56789", stage="context")
        status, headers, body = self.fetch(
            "GET",
            f"/api/runs/{ACTIVE_BENCHMARK_CAMPAIGN}/sse-test/events?once=1",
        )
        self.assertEqual(status, 200)
        self.assertIn("text/event-stream", headers["content-type"])
        self.assertIn(b"event: trace", body)
        self.assertIn(b"paper.started", body)

    def test_artifact_reader_rejects_non_allowlisted_paths(self) -> None:
        with self.assertRaisesRegex(DevConsoleError, "allowlisted"):
            self.controller.read_artifact(
                ACTIVE_BENCHMARK_CAMPAIGN,
                "some-run",
                "1234.56789",
                "../../run_config.json",
            )

    def test_non_loopback_bind_is_rejected(self) -> None:
        with self.assertRaisesRegex(DevConsoleError, "loopback"):
            create_server("0.0.0.0", 0, self.controller)


class DevConsoleLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.logs_root = Path(self.temporary.name)
        self.controller = DevConsoleController(ROOT, logs_root=self.logs_root)
        self.children: list[subprocess.Popen[bytes]] = []

    def tearDown(self) -> None:
        for process in self.children:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        self.controller.close()
        self.temporary.cleanup()

    def _wait_for_status(
        self,
        controller: DevConsoleController,
        run_id: str,
        expected: str,
    ) -> dict[str, object]:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = controller.run_status(ACTIVE_BENCHMARK_CAMPAIGN, run_id)
            if state["status"] == expected:
                return state
            time.sleep(0.05)
        self.fail(f"run {run_id} did not reach {expected}")

    def test_start_stop_and_resume_keep_one_locked_process(self) -> None:
        run_id = "console-lifecycle-test"
        request = DevRunRequest.from_payload(request_payload(run_id=run_id))
        command = [sys.executable, "-c", "import time; time.sleep(60)"]
        preflight = {"ok": True, "checks": [], "command": command, "request": request.public_dict()}
        with mock.patch.object(self.controller, "preflight", return_value=preflight):
            started = self.controller.start(request)
            self.children.append(self.controller._processes[run_id])
            self.assertEqual(started["status"], "running")
            self.assertTrue(self.controller._run_lock_held(run_id))
            with self.assertRaisesRegex(DevConsoleError, "active process"):
                self.controller.start(request)
            self.controller.stop(run_id)
            stopped = self._wait_for_status(self.controller, run_id, "stopped")
            self.assertTrue(stopped["resumable"])
            resumed = self.controller.resume(run_id)
            self.children.append(self.controller._processes[run_id])
            self.assertEqual(resumed["status"], "running")
            self.controller.stop(run_id)
            self._wait_for_status(self.controller, run_id, "stopped")

    def test_new_controller_reconnects_to_and_stops_existing_process_group(self) -> None:
        run_id = "console-reconnect-test"
        request = DevRunRequest.from_payload(request_payload(run_id=run_id))
        run_lock = self.controller._acquire_run_lock(run_id)
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            start_new_session=True,
            pass_fds=(run_lock.fileno(),),
        )
        self.children.append(process)
        run_lock.close()
        self.controller._write_state(
            run_id,
            {
                "campaign_id": ACTIVE_BENCHMARK_CAMPAIGN,
                "run_id": run_id,
                "status": "running",
                "pid": process.pid,
                "pgid": process.pid,
                "started_at": "2026-07-14T00:00:00+00:00",
                "request": request.public_dict(),
            },
        )
        reconnected = DevConsoleController(ROOT, logs_root=self.logs_root)
        status = reconnected.run_status(ACTIVE_BENCHMARK_CAMPAIGN, run_id)
        self.assertTrue(status["controllable"])
        reconnected.stop(run_id)
        process.wait(timeout=5)
        stopped = self._wait_for_status(reconnected, run_id, "stopped")
        self.assertFalse(stopped["controllable"])
        reconnected.close()

    def test_stale_running_state_is_reconciled_instead_of_remaining_running(self) -> None:
        run_id = "console-stale-state-test"
        self.controller._write_state(
            run_id,
            {
                "campaign_id": ACTIVE_BENCHMARK_CAMPAIGN,
                "run_id": run_id,
                "status": "running",
                "pid": 999_999_999,
                "pgid": 999_999_999,
                "started_at": "2026-07-14T00:00:00+00:00",
                "request": request_payload(run_id=run_id),
            },
        )
        status = self.controller.run_status(ACTIVE_BENCHMARK_CAMPAIGN, run_id)
        self.assertEqual(status["status"], "failed")
        self.assertFalse(status["controllable"])

    def test_preflight_builds_the_declared_context_pack(self) -> None:
        request = DevRunRequest.from_payload(request_payload(run_id="context-pack-test"))
        missing = "literature/1804.10179/catalog/declared-missing.ecsv"
        with mock.patch(
            "stella.benchmark.dev_console.build_hvs_candidates_template",
            return_value={"inputs": {"ecsv_paths": [missing]}},
        ):
            result = self.controller.preflight(request)
        check = next(item for item in result["checks"] if item["name"] == "paper context packs")
        self.assertFalse(check["ok"])
        self.assertIn("declared ECSV missing", check["detail"])


class DevConsoleFrontendContractTest(unittest.TestCase):
    def test_frontend_has_required_control_and_inspection_surfaces(self) -> None:
        source = ROOT / "benchmark" / "console" / "src"
        pages = "\n".join(path.read_text(encoding="utf-8") for path in sorted((source / "pages").glob("*.tsx")))
        components = "\n".join(path.read_text(encoding="utf-8") for path in sorted((source / "components").glob("*.tsx")))
        css = (source / "styles.css").read_text(encoding="utf-8")
        for marker in (
            "开始运行",
            "停止整个实验组",
            "从断点恢复",
            "清零这个 Run",
            "确认并开始评估",
            "兼容的单 Run",
        ):
            self.assertIn(marker, pages)
        self.assertIn("EventSource", pages)
        self.assertIn("不会展示或推测隐藏思考", components)
        self.assertIn("ReactFlow", components)
        self.assertIn("min-height: 52px", css)
        self.assertIn("prefers-reduced-motion", css)


if __name__ == "__main__":
    unittest.main()
