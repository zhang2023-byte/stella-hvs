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
        "task_surface": "core_prov",
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

    def test_dev_console_always_normalizes_response_streaming_off(self) -> None:
        self.assertFalse(DevRunRequest.from_payload(request_payload()).stream_responses)
        self.assertFalse(
            DevRunRequest.from_payload(
                request_payload(stream_responses=True)
            ).stream_responses
        )

    def test_request_rejects_unsafe_or_nonformal_values(self) -> None:
        for payload in (
            request_payload(method="A"),
            request_payload(method="C"),
            request_payload(run_id="../escape"),
            request_payload(reviewer_model="extractor-model"),
            request_payload(task_surface="summary"),
            request_payload(task_surface="full"),
            request_payload(scope="regression", task_surface="full", paper_ids=["1804.10179"]),
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
        self.assertNotIn("--stream-responses", command)
        self.assertIn("--no-provider-pin", command)
        self.assertEqual(command[command.index("--provider") + 1], "deepseek")
        self.assertEqual(command[command.index("--fallback-model") + 1], "fallback-a")

    def test_method_c_command_is_not_an_active_dev_console_entrypoint(self) -> None:
        request = DevRunRequest(
            method="C",
            run_id="legacy-c",
            extractor_model="extractor-model",
            reviewer_model="reviewer-model",
        )
        with self.assertRaisesRegex(DevConsoleError, "Method C is legacy"):
            build_runner_command(ROOT, ROOT / "logs" / "console", request)

    def test_regression_command_uses_selected_dev_papers_without_formal_split(self) -> None:
        papers = ("1804.10179", "1902.05061", "2401.02017")
        request = DevRunRequest.from_payload(
            request_payload(scope="regression", paper_ids=list(papers))
        )

        command = build_runner_command(ROOT, ROOT / "logs" / "console", request)

        self.assertNotIn("--campaign", command)
        self.assertNotIn("--split", command)
        self.assertEqual(
            [command[index + 1] for index, value in enumerate(command) if value == "--arxiv-id"],
            list(papers),
        )
        self.assertEqual(
            command[command.index("--trace-campaign-id") + 1],
            ACTIVE_BENCHMARK_CAMPAIGN,
        )
        self.assertIn("--runs-dir", command)

    def test_retry_command_names_only_confirmed_external_failure_papers(self) -> None:
        request = DevRunRequest.from_payload(request_payload())
        command = build_runner_command(
            ROOT,
            ROOT / "logs" / "console",
            request,
            retry_external_papers=("2401.02017", "1901.04559"),
        )
        self.assertEqual(command.count("--retry-external-paper"), 2)
        self.assertEqual(
            [
                command[index + 1]
                for index, value in enumerate(command)
                if value == "--retry-external-paper"
            ],
            ["2401.02017", "1901.04559"],
        )


class DevGroupScopeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.controller = DevConsoleController(
            ROOT, logs_root=Path(self.temporary.name)
        )

    def tearDown(self) -> None:
        self.controller.close()
        self.temporary.cleanup()

    def test_regression_scope_is_group_wide_and_dev_only(self) -> None:
        selected = ["1804.10179", "1902.05061", "2401.02017"]
        payload = {
            "group_id": "regression-group",
            "scope": "regression",
            "paper_ids": selected,
            "max_parallel_experiments": 2,
            "experiments": [
                request_payload(run_id="reg-b-1", method="B"),
                request_payload(run_id="reg-b-2", method="B"),
            ],
        }
        fake_preflight = {
            "ok": True,
            "checks": [],
            "command": ["runner"],
            "request": {},
        }
        with mock.patch.object(
            self.controller, "preflight", return_value=fake_preflight
        ):
            result = self.controller.group_preflight(payload)

        self.assertTrue(result["ok"])
        self.assertEqual(result["request"]["scope"], "regression")
        self.assertEqual(result["request"]["paper_ids"], selected)
        for experiment in result["request"]["experiments"]:
            self.assertEqual(experiment["scope"], "regression")
            self.assertEqual(experiment["paper_ids"], selected)

    def test_regression_rejects_non_dev_paper(self) -> None:
        payload = {
            "group_id": "bad-regression",
            "scope": "regression",
            "paper_ids": ["9999.99999"],
            "experiments": [request_payload(run_id="reg-b")],
        }
        with self.assertRaisesRegex(DevConsoleError, "active dev papers"):
            self.controller.group_preflight(payload)

    def test_formal_scope_cannot_drop_a_dev_paper(self) -> None:
        payload = {
            "group_id": "bad-formal",
            "scope": "formal_dev",
            "paper_ids": self.controller.dev_papers()[:-1],
            "experiments": [request_payload(run_id="formal-b")],
        }
        with self.assertRaisesRegex(DevConsoleError, "exact full 10-paper"):
            self.controller.group_preflight(payload)


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

    def test_trace_snapshot_returns_a_cursor_without_replaying_all_deltas(self) -> None:
        trace = RunTrace(
            Path(self.temporary.name),
            campaign_id=ACTIVE_BENCHMARK_CAMPAIGN,
            run_id="snapshot-test",
            method="C",
        )
        trace.emit("paper.started", paper_id="1234.56789", stage="context")
        for index in range(100):
            trace.emit("llm.response.delta", paper_id="1234.56789", data={"text": str(index)})
        trace.emit("llm.response.completed", paper_id="1234.56789")

        status, headers, body = self.fetch(
            "GET",
            f"/api/runs/{ACTIVE_BENCHMARK_CAMPAIGN}/snapshot-test/trace-snapshot",
        )
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers["content-type"])
        self.assertEqual(payload["last_seq"], 102)
        self.assertLessEqual(
            sum(event["type"] == "llm.response.delta" for event in payload["events"]),
            1,
        )
        self.assertIn("paper.started", [event["type"] for event in payload["events"]])

        status, _, sse_body = self.fetch(
            "GET",
            f"/api/runs/{ACTIVE_BENCHMARK_CAMPAIGN}/snapshot-test/events?once=1",
        )
        self.assertEqual(status, 200)
        self.assertLessEqual(sse_body.count(b"llm.response.delta"), 1)
        self.assertIn(b"paper.started", sse_body)

    def test_sse_reconnect_uses_the_newer_header_cursor(self) -> None:
        trace = RunTrace(
            Path(self.temporary.name),
            campaign_id=ACTIVE_BENCHMARK_CAMPAIGN,
            run_id="cursor-test",
            method="C",
        )
        trace.emit("paper.started", paper_id="1234.56789")
        trace.emit("context.packed", paper_id="1234.56789")
        trace.emit("paper.completed", paper_id="1234.56789")

        status, _, body = self.fetch(
            "GET",
            f"/api/runs/{ACTIVE_BENCHMARK_CAMPAIGN}/cursor-test/events?once=1&after=1",
            extra_headers={"Last-Event-ID": "2"},
        )
        self.assertEqual(status, 200)
        self.assertNotIn(b"id: 2\n", body)
        self.assertIn(b"id: 3\n", body)

    def test_artifact_reader_rejects_non_allowlisted_paths(self) -> None:
        with self.assertRaisesRegex(DevConsoleError, "allowlisted"):
            self.controller.read_artifact(
                ACTIVE_BENCHMARK_CAMPAIGN,
                "some-run",
                "1234.56789",
                "../../run_config.json",
            )

    def test_paper_detail_route_returns_monitor_payload(self) -> None:
        expected = {
            "diagnostic": {"paper_id": "1234.56789", "status": "validator_errors"},
            "report": {"status": "validator_errors"},
            "events": [],
        }
        with mock.patch.object(self.controller, "paper_detail", return_value=expected) as paper_detail:
            status, _, body = self.fetch(
                "GET",
                f"/api/runs/{ACTIVE_BENCHMARK_CAMPAIGN}/monitor-run/papers/1234.56789",
            )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), expected)
        paper_detail.assert_called_once_with(
            ACTIVE_BENCHMARK_CAMPAIGN,
            "monitor-run",
            "1234.56789",
        )

    def test_external_failure_retry_routes_require_explicit_confirmation(self) -> None:
        accepted = {"run_id": "monitor-run", "status": "running"}
        with mock.patch.object(
            self.controller, "retry_external_paper", return_value=accepted
        ) as retry_paper:
            status, _, body = self.fetch(
                "POST",
                f"/api/runs/{ACTIVE_BENCHMARK_CAMPAIGN}/monitor-run/papers/2401.02017/retry",
                payload={"confirm_paper_id": "2401.02017"},
                token=self.controller.session_token,
            )
        self.assertEqual(status, 202)
        self.assertEqual(json.loads(body), accepted)
        retry_paper.assert_called_once_with(
            ACTIVE_BENCHMARK_CAMPAIGN,
            "monitor-run",
            "2401.02017",
            {"confirm_paper_id": "2401.02017"},
        )

        with mock.patch.object(
            self.controller, "retry_external_failures", return_value=accepted
        ) as retry_all:
            status, _, _ = self.fetch(
                "POST",
                f"/api/runs/{ACTIVE_BENCHMARK_CAMPAIGN}/monitor-run/retry-external-failures",
                payload={"confirm_run_id": "monitor-run"},
                token=self.controller.session_token,
            )
        self.assertEqual(status, 202)
        retry_all.assert_called_once_with(
            ACTIVE_BENCHMARK_CAMPAIGN,
            "monitor-run",
            {"confirm_run_id": "monitor-run"},
        )

    def test_non_loopback_bind_is_rejected(self) -> None:
        with self.assertRaisesRegex(DevConsoleError, "loopback"):
            create_server("0.0.0.0", 0, self.controller)


class DevConsolePaperMonitorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name) / "workspace"
        self.logs_root = Path(self.temporary.name) / "logs"
        self.run_id = "paper-monitor-test"
        self.run_dir = (
            self.workspace
            / "benchmark"
            / "campaigns"
            / ACTIVE_BENCHMARK_CAMPAIGN
            / "runs"
            / self.run_id
        )
        self.run_dir.mkdir(parents=True)
        (self.run_dir / "run_config.json").write_text(
            json.dumps(
                {
                    "created_at": "2026-07-15T00:00:00+00:00",
                    "mode": "formal",
                    "campaign": {"campaign_id": ACTIVE_BENCHMARK_CAMPAIGN},
                    "split": "dev",
                    "expected_papers": ["paper-ok", "paper-failed", "paper-transport", "paper-running"],
                    "method": {
                        "producer": "benchmark-extraction",
                        "models": {"extractor": "model-a", "reviewer": "model-b"},
                        "parameters": {"task_surface": "full"},
                    },
                }
            ),
            encoding="utf-8",
        )
        for paper_id, report in {
            "paper-ok": {"status": "ok", "usage_totals": {"total_tokens": 10}},
            "paper-failed": {
                "status": "validator_errors",
                "validator_errors": ["candidates[0].identifier: required"],
                "stage_log": [{"round": 3, "errors": 1}],
                "usage_totals": {"total_tokens": 20},
            },
            "paper-transport": {
                "status": "transport_error",
                "error": "HTTP 503 from provider",
                "usage_totals": {"total_tokens": 5},
            },
        }.items():
            paper_dir = self.run_dir / paper_id
            paper_dir.mkdir()
            (paper_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
        trace = RunTrace(
            self.logs_root,
            campaign_id=ACTIVE_BENCHMARK_CAMPAIGN,
            run_id=self.run_id,
            method="B",
        )
        trace.emit("paper.started", paper_id="paper-running", stage="context", status="running")
        trace.emit("context.packed", paper_id="paper-running", stage="context", status="completed")
        trace.emit("llm.request.started", paper_id="paper-running", stage="batch-001", status="running")
        trace.emit(
            "llm.response.completed",
            paper_id="paper-running",
            stage="batch-001",
            status="completed",
            usage={"prompt_tokens": 30, "completion_tokens": 12, "total_tokens": 42},
        )
        self.controller = DevConsoleController(self.workspace, logs_root=self.logs_root)

    def tearDown(self) -> None:
        self.controller.close()
        self.temporary.cleanup()

    def test_run_summary_exposes_compact_paper_diagnostics(self) -> None:
        summary = self.controller.run_detail(ACTIVE_BENCHMARK_CAMPAIGN, self.run_id)
        diagnostics = summary["paper_diagnostics"]
        self.assertEqual(diagnostics["paper-ok"]["status"], "ok")
        self.assertEqual(diagnostics["paper-ok"]["stage"], "completed")
        self.assertEqual(diagnostics["paper-failed"]["error_type"], "validator_errors")
        self.assertEqual(diagnostics["paper-failed"]["stage"], "validation")
        self.assertEqual(
            diagnostics["paper-failed"]["error_message"],
            "candidates[0].identifier: required",
        )
        self.assertEqual(diagnostics["paper-failed"]["validator_error_count"], 1)
        self.assertEqual(diagnostics["paper-running"]["status"], "running")
        self.assertEqual(diagnostics["paper-running"]["stage"], "batch-001")
        self.assertFalse(diagnostics["paper-failed"]["retry_eligible"])
        self.assertTrue(diagnostics["paper-transport"]["retry_eligible"])
        self.assertEqual(summary["retryable_papers"], ["paper-transport"])
        self.assertFalse(summary["sealed"])
        self.assertEqual(summary["usage_totals"]["total_tokens"], 77)
        self.assertEqual(summary["downstream_usage_totals"]["total_tokens"], 42)

    def test_legacy_warning_count_is_preserved_without_revalidation(self) -> None:
        report_path = self.run_dir / "paper-ok" / "report.json"
        report_path.write_text(
            json.dumps(
                {
                    "status": "ok",
                    "validator_warnings_count": 7,
                    "usage_totals": {"total_tokens": 10},
                }
            ),
            encoding="utf-8",
        )

        summary = self.controller.run_detail(ACTIVE_BENCHMARK_CAMPAIGN, self.run_id)
        diagnostic = summary["paper_diagnostics"]["paper-ok"]

        self.assertEqual(diagnostic["warning_count"], 7)
        self.assertFalse(diagnostic["warning_details_available"])
        self.assertTrue(diagnostic["historical_warning_count_only"])

    def test_structured_transport_and_roster_usage_are_exposed_compactly(self) -> None:
        transport_path = self.run_dir / "paper-transport" / "report.json"
        transport_path.write_text(
            json.dumps(
                {
                    "status": "transport_error",
                    "error": "legacy wrapper text",
                    "transport_error": {
                        "category": "server",
                        "http_status": 503,
                        "manual_retry_eligible": True,
                        "stage": "roster",
                        "call_id": "paper-transport:roster:1",
                    },
                    "usage_totals": {"total_tokens": 5},
                }
            ),
            encoding="utf-8",
        )
        ok_path = self.run_dir / "paper-ok" / "report.json"
        ok_path.write_text(
            json.dumps(
                {
                    "status": "ok",
                    "usage_totals": {"total_tokens": 40},
                    "downstream_usage": {"total_tokens": 30},
                    "shared_roster_usage": {"total_tokens": 10},
                    "roster_bundle_id": "bundle-a",
                    "roster_cache_hit": False,
                }
            ),
            encoding="utf-8",
        )

        summary = self.controller.run_detail(ACTIVE_BENCHMARK_CAMPAIGN, self.run_id)
        diagnostic = summary["paper_diagnostics"]["paper-transport"]

        self.assertEqual(diagnostic["stage"], "roster")
        self.assertEqual(diagnostic["error_message"], "HTTP 503 · server")
        self.assertTrue(diagnostic["retry_eligible"])
        self.assertEqual(summary["downstream_usage_totals"]["total_tokens"], 72)
        self.assertEqual(summary["shared_roster_bundles"][0]["bundle_id"], "bundle-a")
        self.assertEqual(
            summary["shared_roster_bundles"][0]["usage_totals"]["total_tokens"],
            10,
        )

    def test_internal_shared_roster_cache_is_not_listed_as_a_run(self) -> None:
        (self.run_dir.parent / "_shared_rosters").mkdir()

        run_ids = {item["run_id"] for item in self.controller.list_runs()}

        self.assertIn(self.run_id, run_ids)
        self.assertNotIn("_shared_rosters", run_ids)

    def test_sealed_run_is_read_only_and_never_retryable(self) -> None:
        (self.run_dir / "run_manifest.json").write_text("{}", encoding="utf-8")
        summary = self.controller.run_detail(ACTIVE_BENCHMARK_CAMPAIGN, self.run_id)
        self.assertTrue(summary["sealed"])
        self.assertTrue(summary["read_only"])
        self.assertEqual(summary["retryable_papers"], [])
        self.assertFalse(
            summary["paper_diagnostics"]["paper-transport"]["retry_eligible"]
        )

    def test_sealed_run_reports_core_and_enrichment_delivery_separately(self) -> None:
        # Task 3 Step 4: the console exposes the two delivery envelopes as
        # separate figures, never one collapsed success rate.
        outcomes_core = {"valid": ["paper-ok", "paper-failed"], "invalid": [], "missing": []}
        outcomes_enrichment = {"valid": ["paper-ok"], "invalid": ["paper-failed"], "missing": []}
        (self.run_dir / "run_manifest.json").write_text(
            json.dumps(
                {
                    "core_delivery": {
                        "status": "complete",
                        "validation_mode": "full_core",
                        "papers": outcomes_core,
                        "artifacts": {},
                    },
                    "enrichment_delivery": {
                        "status": "partial",
                        "validation_mode": "full_enrichment",
                        "papers": outcomes_enrichment,
                        "artifacts": {},
                    },
                }
            ),
            encoding="utf-8",
        )

        summary = self.controller.run_detail(ACTIVE_BENCHMARK_CAMPAIGN, self.run_id)

        self.assertEqual(
            summary["deliveries"]["core"],
            {
                "status": "complete",
                "validation_mode": "full_core",
                "valid": 2,
                "invalid": 0,
                "missing": 0,
            },
        )
        self.assertEqual(
            summary["deliveries"]["enrichment"],
            {
                "status": "partial",
                "validation_mode": "full_enrichment",
                "valid": 1,
                "invalid": 1,
                "missing": 0,
            },
        )

    def test_unsealed_run_has_no_delivery_summary(self) -> None:
        summary = self.controller.run_detail(ACTIVE_BENCHMARK_CAMPAIGN, self.run_id)
        self.assertIsNone(summary["deliveries"])

    def test_unsealed_method_c_history_is_read_only_and_not_resumable(self) -> None:
        config_path = self.run_dir / "run_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["method"]["producer"] = "stella-agentic-extraction"
        config_path.write_text(json.dumps(config), encoding="utf-8")

        summary = self.controller.run_detail(ACTIVE_BENCHMARK_CAMPAIGN, self.run_id)

        self.assertEqual(summary["method"], "C")
        self.assertTrue(summary["read_only"])
        self.assertFalse(summary["resumable"])
        self.assertEqual(summary["retryable_papers"], [])

    def test_http_400_transport_report_is_treated_as_workflow_or_request_error(self) -> None:
        report_path = self.run_dir / "paper-transport" / "report.json"
        report_path.write_text(
            json.dumps(
                {
                    "status": "transport_error",
                    "error": "HTTPError: HTTP Error 400: Bad Request",
                }
            ),
            encoding="utf-8",
        )
        summary = self.controller.run_detail(ACTIVE_BENCHMARK_CAMPAIGN, self.run_id)
        diagnostic = summary["paper_diagnostics"]["paper-transport"]
        self.assertFalse(diagnostic["retry_eligible"])
        self.assertIn("API 请求或配置错误", diagnostic["retry_reason"])
        self.assertEqual(summary["retryable_papers"], [])

    def test_paper_detail_returns_report_and_only_structural_paper_events(self) -> None:
        detail = self.controller.paper_detail(
            ACTIVE_BENCHMARK_CAMPAIGN,
            self.run_id,
            "paper-running",
        )
        self.assertIsNone(detail["report"])
        self.assertEqual(detail["diagnostic"]["status"], "running")
        self.assertEqual(
            [event["type"] for event in detail["events"]],
            [
                "paper.started",
                "context.packed",
                "llm.request.started",
                "llm.response.completed",
            ],
        )


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

    def test_selective_retry_does_not_mark_whole_run_complete_when_other_papers_failed(self) -> None:
        run_id = "selective-retry-status-test"
        self.controller._write_state(
            run_id,
            {
                "campaign_id": ACTIVE_BENCHMARK_CAMPAIGN,
                "run_id": run_id,
                "status": "running",
                "retry_external_papers": ["2401.02017"],
            },
        )
        process = mock.Mock()
        process.wait.return_value = 0
        with mock.patch.object(
            self.controller, "_terminal_status_from_archive", return_value="failed"
        ):
            self.controller._monitor_process(run_id, process)
        self.assertEqual(self.controller._read_state(run_id)["status"], "failed")

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
        hooks = "\n".join(path.read_text(encoding="utf-8") for path in sorted((source / "hooks").glob("*.ts")))
        css = (source / "styles.css").read_text(encoding="utf-8")
        for marker in (
            "开始运行",
            "停止整个实验组",
            "从断点恢复",
            "论文运行监控",
            "失败环节",
            "清零这个 Run",
            "确认并开始评估",
            "未归组记录",
        ):
            self.assertIn(marker, pages)
        self.assertIn("EventSource", hooks)
        self.assertNotIn("useRunTraceStreams", pages)
        self.assertNotIn("ReactFlow", components)
        self.assertNotIn("模型输入", components)
        self.assertIn("页面每 3 秒读取一次紧凑状态", pages)
        self.assertIn("min-height: 52px", css)
        self.assertIn("prefers-reduced-motion", css)


if __name__ == "__main__":
    unittest.main()
