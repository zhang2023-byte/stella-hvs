from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from stella.benchmark.campaign import sha256_file
from stella.benchmark.network_gate import evaluate_network_gate
from stella.schema_registry import schema_ref


def _roster_network_death() -> dict:
    return {
        "status": "failed",
        "failure": {
            "code": "extractor_terminal_failure",
            "proposal_failures": [
                {
                    "slot": 0,
                    "failure": {
                        "status": "transport_failure",
                        "transport_error": {"category": "network"},
                    },
                }
            ],
        },
    }


class BenchmarkNetworkGateTest(unittest.TestCase):
    def _run(self, root: Path, paper_result: dict, *, scope: str = "full_dev") -> Path:
        run = root / "run"
        paper = run / "papers" / "paper-1"
        paper.mkdir(parents=True)
        (run / "run_summary.json").write_text(
            json.dumps(
                {
                    "schema": schema_ref("benchmark.run_summary"),
                    "run_id": "run-1",
                    "scope": scope,
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
            self.assertEqual(result["mode"], "formal_run")

    def test_terminal_network_failure_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = self._run(
                Path(tmp),
                {"failure": {"code": "transport_failure", "transport_error": {"category": "network"}}},
            )
            result = evaluate_network_gate(run)
            self.assertFalse(result["passed"])
            self.assertEqual(result["terminal_network_failures"][0]["arxiv_id"], "paper-1")

    def test_roster_network_death_is_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = self._run(Path(tmp), _roster_network_death())
            result = evaluate_network_gate(run)
            self.assertFalse(result["passed"])
            self.assertEqual(result["terminal_network_failures"][0]["arxiv_id"], "paper-1")

    def test_roster_non_network_death_stays_non_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = _roster_network_death()
            payload["failure"]["proposal_failures"][0]["failure"]["transport_error"] = {
                "category": "invalid_request"
            }
            run = self._run(Path(tmp), payload)
            result = evaluate_network_gate(run)
            self.assertTrue(result["passed"])

    def test_full_test_formal_run_is_scannable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = self._run(Path(tmp), {"status": "complete"}, scope="full_test")
            result = evaluate_network_gate(run)
            self.assertTrue(result["passed"])
            self.assertEqual(result["scope"], "full_test")

    def test_targeted_dev_scope_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = self._run(Path(tmp), {"status": "complete"}, scope="targeted_dev")
            with self.assertRaisesRegex(ValueError, "completed full_dev or full_test"):
                evaluate_network_gate(run)


class NetworkGateDebugRunTest(unittest.TestCase):
    def _debug(self, root: Path, *, state: str = "clean", copied: dict[str, str] | None = None,
               finalize: bool = True) -> Path:
        run = root / "debug"
        paper = run / "papers" / "paper-1"
        paper.mkdir(parents=True)
        (paper / "paper_result.json").write_text(json.dumps({"status": "complete"}), encoding="utf-8")
        (run / "debug_config.json").write_text(
            json.dumps(
                {
                    "schema": schema_ref("benchmark.network_debug_config"),
                    "debug_run_id": "debug-1",
                    "source_run": {"run_id": "run-1", "scope": "full_dev"},
                    "papers": ["paper-1"],
                    "state": state,
                }
            ),
            encoding="utf-8",
        )
        if finalize:
            copied_files = copied if copied is not None else {
                "papers/paper-1/paper_result.json": sha256_file(
                    paper / "paper_result.json"
                )
            }
            (run / "debug_result.json").write_text(
                json.dumps(
                    {
                        "schema": schema_ref("benchmark.network_debug_result"),
                        "debug_run_id": "debug-1",
                        "papers": [{"arxiv_id": "paper-1", "copied_files": copied_files}],
                    }
                ),
                encoding="utf-8",
            )
        return run

    def test_finalized_clean_debug_run_passes_with_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = self._debug(Path(tmp))
            result = evaluate_network_gate(run)
            self.assertTrue(result["passed"])
            self.assertEqual(result["mode"], "network_debug")
            self.assertEqual(result["source_run_id"], "run-1")
            self.assertEqual(result["copy_integrity"]["checked_files"], 1)
            self.assertEqual(result["copy_integrity"]["errors"], [])

    def test_debug_copy_hash_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = self._debug(Path(tmp), copied={"papers/paper-1/paper_result.json": "0" * 64})
            result = evaluate_network_gate(run)
            self.assertFalse(result["passed"])
            self.assertEqual(result["copy_integrity"]["errors"][0]["error"], "sha256_mismatch")

    def test_unfinalized_debug_run_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = self._debug(Path(tmp), state="recovering", finalize=False)
            with self.assertRaisesRegex(ValueError, "finalized clean debug run"):
                evaluate_network_gate(run)

    def test_debug_terminal_network_failure_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = self._debug(Path(tmp))
            payload = json.loads(
                ((run / "papers" / "paper-1" / "paper_result.json")).read_text(encoding="utf-8")
            )
            payload["candidates"] = [
                {
                    "record_id": "candidate-001",
                    "failure": {
                        "code": "transport_failure",
                        "transport_error": {"category": "network"},
                    },
                }
            ]
            (run / "papers" / "paper-1" / "paper_result.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            result = evaluate_network_gate(run)
            self.assertFalse(result["passed"])
            self.assertEqual(result["terminal_network_failures"][0]["arxiv_id"], "paper-1")


if __name__ == "__main__":
    unittest.main()
