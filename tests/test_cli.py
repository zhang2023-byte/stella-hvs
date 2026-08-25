"""Tests for the unified ``python -m stella`` CLI."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
from pathlib import Path

from stella import cli

ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: str) -> tuple[int, dict]:
    """Invoke the CLI in-process and return (exit_code, parsed_json_payload)."""

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = cli.main(list(args))
    payload = json.loads(buffer.getvalue())
    return code, payload


class WorkflowIntrospectionTest(unittest.TestCase):
    def test_workflow_list_returns_three_products(self) -> None:
        code, payload = run_cli("workflow", "list", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(
            sorted(w["id"] for w in payload["data"]["workflows"]),
            ["benchmark", "gold_annotation", "literature_pipeline"],
        )

    def test_workflow_show_returns_spec_with_phases(self) -> None:
        code, payload = run_cli("workflow", "show", "literature_pipeline", "--json")
        self.assertEqual(code, 0)
        spec = payload["data"]
        self.assertEqual(spec["id"], "literature_pipeline")
        self.assertTrue(spec["phases"])
        self.assertIn("operations", spec["phases"][0])

    def test_workflow_show_unknown_id_is_a_structured_error(self) -> None:
        code, payload = run_cli("workflow", "show", "nope", "--json")
        self.assertNotEqual(code, 0)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"]["code"], "UNKNOWN_WORKFLOW")
        self.assertTrue(payload["error"]["next_action"])

    def test_operation_show_returns_catalog_entry(self) -> None:
        code, payload = run_cli("operation", "show", "literature.fetch", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["id"], "literature.fetch")
        self.assertIn("owner", payload["data"])

    def test_operation_show_unknown_id_is_a_structured_error(self) -> None:
        code, payload = run_cli("operation", "show", "nope.nothing", "--json")
        self.assertNotEqual(code, 0)
        self.assertEqual(payload["error"]["code"], "UNKNOWN_OPERATION")


class SchemaIntrospectionTest(unittest.TestCase):
    def test_schema_list_is_read_only_from_registry(self) -> None:
        code, payload = run_cli("schema", "list", "--json")
        self.assertEqual(code, 0)
        names = [item["name"] for item in payload["data"]["schemas"]]
        self.assertIn("literature_hvs_contributions", names)

    def test_schema_show_returns_entry(self) -> None:
        code, payload = run_cli(
            "schema", "show", "literature_hvs_contributions", "--json"
        )
        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["name"], "literature_hvs_contributions")

    def test_schema_show_unknown_name_is_a_structured_error(self) -> None:
        code, payload = run_cli("schema", "show", "not_a_schema", "--json")
        self.assertNotEqual(code, 0)
        self.assertEqual(payload["error"]["code"], "UNKNOWN_SCHEMA")


class WorkflowPlanTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.request_path = Path(self.tmp.name) / "request.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_request(self, payload: dict) -> None:
        self.request_path.write_text(
            json.dumps(payload), encoding="utf-8"
        )

    def test_plan_validates_input_and_reports_missing_authorities(self) -> None:
        self._write_request({"papers": ["2601.08888"]})
        code, payload = run_cli(
            "workflow",
            "plan",
            "literature_pipeline",
            "--input",
            str(self.request_path),
            "--json",
        )
        self.assertEqual(code, 0)
        data = payload["data"]
        self.assertEqual(data["status"], "planned")
        self.assertEqual(data["request"]["papers"], ["2601.08888"])
        self.assertTrue(data["phases"])
        self.assertIn("network", data["required_authorities"])
        self.assertIn("llm", data["required_authorities"])
        self.assertIn("network", data["missing_authorities"])

    def test_plan_rejects_invalid_input(self) -> None:
        self._write_request({"papers": []})
        code, payload = run_cli(
            "workflow",
            "plan",
            "literature_pipeline",
            "--input",
            str(self.request_path),
            "--json",
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(payload["error"]["code"], "INVALID_INPUT")

    def test_plan_missing_input_file_is_a_structured_error(self) -> None:
        code, payload = run_cli(
            "workflow",
            "plan",
            "literature_pipeline",
            "--input",
            str(Path(self.tmp.name) / "missing.json"),
            "--json",
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(payload["error"]["code"], "INVALID_INPUT")

    def test_benchmark_plan_defaults_to_dev10(self) -> None:
        self._write_request({})
        code, payload = run_cli(
            "workflow",
            "plan",
            "benchmark",
            "--input",
            str(self.request_path),
            "--json",
        )
        self.assertEqual(code, 0)
        self.assertEqual(payload["data"]["request"]["profile"], "dev10")


class WorkflowRunGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.request_path = Path(self.tmp.name) / "request.json"
        self.request_path.write_text(
            json.dumps({"papers": ["2601.08888"]}), encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, *extra: str) -> tuple[int, dict]:
        return run_cli(
            "workflow",
            "run",
            "literature_pipeline",
            "--input",
            str(self.request_path),
            *extra,
        )

    def test_run_refuses_without_execute(self) -> None:
        code, payload = self._run("--json")
        self.assertNotEqual(code, 0)
        self.assertEqual(payload["error"]["code"], "EXECUTE_REQUIRED")

    def test_execute_alone_does_not_grant_network_or_llm(self) -> None:
        code, payload = self._run("--execute", "--json")
        self.assertNotEqual(code, 0)
        self.assertEqual(payload["error"]["code"], "MISSING_AUTHORITY")
        self.assertIn("network", payload["error"]["missing_authority"])
        self.assertIn("llm", payload["error"]["missing_authority"])

    def test_execute_with_authorities_runs_real_operations(self) -> None:
        # Every gold operation resolves and does real maintained work; a
        # fully authorized run must execute rather than report a missing
        # implementation. Annotation stages without an archived PDF fail as
        # typed preconditions inside a temporary run root.
        with tempfile.TemporaryDirectory() as run_root, tempfile.TemporaryDirectory() as gold:
            self.request_path.write_text(
                json.dumps({"expert": "expert-a", "papers": ["2601.08888"]}),
                encoding="utf-8",
            )
            env_patch = {
                "STELLA_RUN_ROOT": run_root,
                "STELLA_GOLD_DIR": gold,
            }
            old_env = {key: os.environ.get(key) for key in env_patch}
            os.environ.update(env_patch)
            try:
                code, payload = run_cli(
                    "workflow",
                    "run",
                    "gold_annotation",
                    "--input",
                    str(self.request_path),
                    "--execute",
                    "--allow-gold-private",
                    "--json",
                )
            finally:
                for key, value in old_env.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "ok")
            self.assertNotEqual(
                payload["data"].get("status"), "OPERATION_NOT_IMPLEMENTED"
            )
            self.assertTrue(
                (Path(run_root) / "runs" / "gold_annotation").is_dir()
            )

    def test_benchmark_request_run_id_reaches_the_runtime(self) -> None:
        self.request_path.write_text(
            json.dumps(
                {
                    "run_id": "existing-benchmark-run",
                    "papers": ["2601.08888"],
                    "phases": ["prepare"],
                }
            ),
            encoding="utf-8",
        )
        summary = {
            "workflow_id": "benchmark",
            "run_id": "existing-benchmark-run",
            "status": "complete",
            "papers": [],
        }
        with patch(
            "stella.cli.workflow_runtime.run_workflow", return_value=summary
        ) as mocked:
            code, payload = run_cli(
                "workflow",
                "run",
                "benchmark",
                "--input",
                str(self.request_path),
                "--execute",
                "--json",
            )
        self.assertEqual(code, 0, payload)
        self.assertEqual(mocked.call_args.kwargs["run_id"], "existing-benchmark-run")


class HumanOutputTest(unittest.TestCase):
    def test_human_rendering_is_not_json(self) -> None:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = cli.main(["workflow", "list"])
        self.assertEqual(code, 0)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(buffer.getvalue())


class ModuleEntryPointTest(unittest.TestCase):
    def test_python_dash_m_stella_lists_workflows(self) -> None:
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
        result = subprocess.run(
            [sys.executable, "-m", "stella", "workflow", "list", "--json"],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(ROOT),
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ok")


if __name__ == "__main__":
    unittest.main()
