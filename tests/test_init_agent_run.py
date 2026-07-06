"""Method-A (skill-agent) run config scaffolding tests."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "init_agent_run.py"
SPEC = importlib.util.spec_from_file_location("init_agent_run", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
init_agent_run = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(init_agent_run)


def run_cli(argv: list[str]) -> int:
    with mock.patch.object(sys, "argv", ["init_agent_run.py", *argv]):
        with mock.patch("sys.stdout", new_callable=io.StringIO):
            return init_agent_run.main()


class InitAgentRunTest(unittest.TestCase):
    def test_writes_config_with_harness_and_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runs_dir = Path(tmp)
            exit_code = run_cli(
                [
                    "--run-id",
                    "gold8-a-01-cursor",
                    "--harness",
                    "cursor",
                    "--harness-version",
                    "2.3.1",
                    "--model",
                    "claude-sonnet-5-thinking",
                    "--arxiv-id",
                    "1807.00427",
                    "--arxiv-id",
                    "1804.10179",
                    "--arxiv-id",
                    "1807.00427",
                    "--runs-dir",
                    str(runs_dir),
                ]
            )
            self.assertEqual(exit_code, 0)
            config = json.loads(
                (runs_dir / "gold8-a-01-cursor" / "run_config.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(config["run_id"], "gold8-a-01-cursor")
            self.assertEqual(
                config["harness"], {"name": "cursor", "version": "2.3.1"}
            )
            self.assertEqual(config["model"], "claude-sonnet-5-thinking")
            self.assertEqual(config["papers"], ["1804.10179", "1807.00427"])
            self.assertTrue(config["pipeline"].startswith("stella-skill-agent-extraction/"))
            self.assertTrue(config["prompt_version"])

    def test_refuses_to_overwrite_existing_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runs_dir = Path(tmp)
            argv = [
                "--run-id",
                "gold8-a-01-cursor",
                "--harness",
                "cursor",
                "--harness-version",
                "2.3.1",
                "--model",
                "m",
                "--arxiv-id",
                "1807.00427",
                "--runs-dir",
                str(runs_dir),
            ]
            self.assertEqual(run_cli(argv), 0)
            with self.assertRaises(SystemExit) as ctx:
                run_cli(argv)
            self.assertIn("refusing to overwrite", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
