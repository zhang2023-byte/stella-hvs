from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from stella.benchmark.network_gate import evaluate_network_gate
from stella.schema_registry import schema_ref


class BenchmarkNetworkGateTest(unittest.TestCase):
    def _run(self, root: Path, paper_result: dict) -> Path:
        run = root / "run"
        paper = run / "papers" / "paper-1"
        paper.mkdir(parents=True)
        (run / "run_summary.json").write_text(
            json.dumps(
                {
                    "schema": schema_ref("benchmark.run_summary"),
                    "run_id": "run-1",
                    "scope": "full_dev",
                    "state": "completed",
                    "papers": {"paper-1": {}},
                }
            ),
            encoding="utf-8",
        )
        (paper / "paper_result.json").write_text(json.dumps(paper_result), encoding="utf-8")
        return run

    def test_recovered_network_attempt_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = self._run(
                Path(tmp),
                {"attempts": [{"outcome": "transport_error", "error_class": "network"}, {"outcome": "success"}]},
            )
            result = evaluate_network_gate(run)
            self.assertTrue(result["passed"])
            self.assertEqual(result["network_attempt_errors"], 1)

    def test_terminal_network_failure_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = self._run(
                Path(tmp),
                {"failure": {"code": "transport_failure", "transport_error": {"category": "network"}}},
            )
            result = evaluate_network_gate(run)
            self.assertFalse(result["passed"])
            self.assertEqual(result["terminal_network_failures"][0]["arxiv_id"], "paper-1")


if __name__ == "__main__":
    unittest.main()
