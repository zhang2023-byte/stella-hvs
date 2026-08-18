"""Network debug run lifecycle tests (offline fake transports)."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from stella.benchmark.network_gate import evaluate_network_gate
from stella.hvs_extraction.method_config import (
    default_hvs_extraction_method_config,
)
from stella.hvs_extraction.network_debug import (
    debug_run_dir,
    derive_debug_state,
    finalize_network_debug_run,
    init_network_debug_run,
    retry_network_nodes,
)
from stella.hvs_extraction.run import create_run_config, run_papers
from stella.lit.llm_batch import LLMTransportError
from tests.test_hvs_extraction_run import (
    ARXIV_ID,
    ROOT,
    RecordingTransport,
    ROSTER_SUBMISSION,
    field_submission,
    make_workspace,
    roster_handler,
)

DEBUG_ID = "netdebug-e2e-1"
SOURCE_ID = "run-netdebug-source"
PRICING_SNAPSHOT = "tokendance-2026-08-03-screenshots-v1.json"


def network_transport_error() -> LLMTransportError:
    return LLMTransportError(
        "connection timed out after 5007 ms",
        category="network",
        http_status=None,
        automatic_retryable=True,
        manual_retry_eligible=True,
    )


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


class NetworkDebugEndToEndTest(unittest.TestCase):
    def make_workspace_with_pricing(self, tmp: str) -> Path:
        workspace = make_workspace(tmp)
        pricing_dir = workspace / "benchmark" / "pricing" / "tokendance"
        pricing_dir.mkdir(parents=True)
        shutil.copy2(
            ROOT / "benchmark" / "pricing" / "tokendance" / PRICING_SNAPSHOT,
            pricing_dir / PRICING_SNAPSHOT,
        )
        return workspace

    def make_source_run(self, workspace: Path, handler) -> None:
        config = default_hvs_extraction_method_config(workspace)
        create_run_config(
            workspace,
            SOURCE_ID,
            [ARXIV_ID],
            config=config,
            scope="full_dev",
            code={"commit": "test", "dirty": False},
        )
        run_papers(
            workspace,
            SOURCE_ID,
            config=config,
            transport=RecordingTransport(handler),
            sleep=lambda _: None,
            pricing_snapshot_path=(
                workspace
                / "benchmark"
                / "pricing"
                / "tokendance"
                / PRICING_SNAPSHOT
            ),
        )

    def failing_field_handler(self):
        def handler(kwargs: dict) -> dict:
            name = kwargs["extra_body"]["tools"][0]["function"]["name"]
            if name == "submit_candidate_fields":
                raise network_transport_error()
            return roster_handler(ROSTER_SUBMISSION, field_submission())(kwargs)

        return handler

    def test_candidate_network_failure_full_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.make_workspace_with_pricing(tmp)
            self.make_source_run(workspace, self.failing_field_handler())
            source_run_dir = (
                workspace
                / "benchmark"
                / "campaigns"
                / "hvs-extraction-v6"
                / "runs"
                / SOURCE_ID
            )
            source_digest = tree_digest(source_run_dir)
            source_paper_result = json.loads(
                (
                    source_run_dir / "papers" / ARXIV_ID / "paper_result.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(source_paper_result["status"], "partial")
            self.assertEqual(
                source_paper_result["candidates"][0]["failure"]["code"],
                "transport_failure",
            )

            state = init_network_debug_run(
                workspace,
                source_run_id=SOURCE_ID,
                debug_run_id=DEBUG_ID,
            )
            self.assertEqual(
                state["papers"][0]["retry_nodes"], ["candidate:candidate-001"]
            )
            self.assertFalse(state["transport_clean"])
            self.assertEqual(tree_digest(source_run_dir), source_digest)

            debug_dir = debug_run_dir(workspace, DEBUG_ID)
            config = json.loads(
                (debug_dir / "debug_config.json").read_text(encoding="utf-8")
            )
            self.assertEqual(config["state"], "initialized")
            self.assertEqual(
                config["method_fingerprint"],
                json.loads(
                    (source_run_dir / "run_config.json").read_text(encoding="utf-8")
                )["method_fingerprint"],
            )
            self.assertEqual(config["papers"], [ARXIV_ID])
            events = [
                json.loads(line)
                for line in (debug_dir / "debug_events.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["command"], "init")

            roster_before = (
                debug_dir / "papers" / ARXIV_ID / "roster_proposal-slot-0.json"
            ).read_bytes()
            retry_transport = RecordingTransport(
                roster_handler(ROSTER_SUBMISSION, field_submission())
            )
            summary = retry_network_nodes(
                workspace,
                DEBUG_ID,
                transport=retry_transport,
                api_key="k",
                base_url="u",
                nodes=[f"{ARXIV_ID}:candidate-001"],
                sleep=lambda _: None,
            )
            self.assertTrue(summary["transport_clean"])
            self.assertEqual(len(retry_transport.calls), 1)
            self.assertEqual(
                (
                    debug_dir / "papers" / ARXIV_ID / "roster_proposal-slot-0.json"
                ).read_bytes(),
                roster_before,
            )
            candidate = json.loads(
                (
                    debug_dir
                    / "papers"
                    / ARXIV_ID
                    / "candidates"
                    / "candidate-001.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(len(candidate["attempts"]), 4)
            self.assertEqual(
                [attempt["outcome"] for attempt in candidate["attempts"]],
                ["transport_error"] * 3 + ["response_received"],
            )
            self.assertEqual(len(candidate["usages"]), 1)
            paper_result = json.loads(
                (debug_dir / "papers" / ARXIV_ID / "paper_result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(paper_result["status"], "complete")
            self.assertEqual(paper_result["run_id"], DEBUG_ID)
            self.assertTrue(
                (
                    debug_dir
                    / "papers"
                    / ARXIV_ID
                    / "literature_hvs_candidates.json"
                ).is_file()
            )

            result = finalize_network_debug_run(workspace, DEBUG_ID)
            self.assertTrue(result["terminal_network_check"]["passed"])
            self.assertEqual(result["papers"][0]["origin"], "recovered")
            self.assertEqual(result["papers"][0]["retry_commands"], 1)
            self.assertEqual(result["retry_commands"], 1)
            total_cny = result["estimated_api_cost"]["total_cny"]
            if total_cny is not None:
                self.assertGreater(Decimal(total_cny), Decimal("0"))
            self.assertIn(
                result["estimated_api_cost"]["status"], {"complete", "partial"}
            )
            self.assertEqual(
                result["estimated_api_cost"]["pricing_snapshot"]["snapshot_id"],
                "tokendance-2026-08-03-screenshots-v1",
            )
            gate = evaluate_network_gate(debug_dir)
            self.assertTrue(gate["passed"])
            self.assertEqual(gate["mode"], "network_debug")
            self.assertEqual(gate["source_run_id"], SOURCE_ID)
            self.assertEqual(gate["network_attempt_errors"], 3)

            with self.assertRaisesRegex(ValueError, "already finalized"):
                finalize_network_debug_run(workspace, DEBUG_ID)
            with self.assertRaisesRegex(ValueError, "already finalized"):
                retry_network_nodes(
                    workspace,
                    DEBUG_ID,
                    transport=retry_transport,
                    api_key="k",
                    base_url="u",
                    sleep=lambda _: None,
                )
            self.assertEqual(tree_digest(source_run_dir), source_digest)

    def test_roster_network_death_full_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.make_workspace_with_pricing(tmp)

            def dead_roster(kwargs: dict) -> dict:
                name = kwargs["extra_body"]["tools"][0]["function"]["name"]
                if name != "submit_candidate_fields":
                    raise network_transport_error()
                raise AssertionError("field stage must not run")

            self.make_source_run(workspace, dead_roster)
            source_paper_result = json.loads(
                (
                    workspace
                    / "benchmark"
                    / "campaigns"
                    / "hvs-extraction-v6"
                    / "runs"
                    / SOURCE_ID
                    / "papers"
                    / ARXIV_ID
                    / "paper_result.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(source_paper_result["status"], "failed")
            self.assertEqual(
                source_paper_result["failure"]["code"],
                "extractor_terminal_failure",
            )

            state = init_network_debug_run(
                workspace,
                source_run_id=SOURCE_ID,
                debug_run_id=DEBUG_ID,
            )
            self.assertEqual(state["papers"][0]["retry_nodes"], ["roster"])

            summary = retry_network_nodes(
                workspace,
                DEBUG_ID,
                transport=RecordingTransport(
                    roster_handler(ROSTER_SUBMISSION, field_submission())
                ),
                api_key="k",
                base_url="u",
                sleep=lambda _: None,
            )
            self.assertTrue(summary["transport_clean"])
            debug_dir = debug_run_dir(workspace, DEBUG_ID)
            proposal = json.loads(
                (
                    debug_dir
                    / "papers"
                    / ARXIV_ID
                    / "roster_proposal-slot-0.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(len(proposal["attempts"]), 4)
            paper_result = json.loads(
                (debug_dir / "papers" / ARXIV_ID / "paper_result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(paper_result["status"], "complete")

            result = finalize_network_debug_run(workspace, DEBUG_ID)
            self.assertTrue(result["terminal_network_check"]["passed"])
            gate = evaluate_network_gate(debug_dir)
            self.assertTrue(gate["passed"])

    def test_non_network_failure_is_not_retryable_but_finalize_allows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.make_workspace_with_pricing(tmp)

            def broken_field(kwargs: dict) -> dict:
                name = kwargs["extra_body"]["tools"][0]["function"]["name"]
                if name == "submit_candidate_fields":
                    return {
                        "choices": [
                            {
                                "index": 0,
                                "message": {
                                    "role": "assistant",
                                    "tool_calls": [
                                        {
                                            "id": "call_1",
                                            "type": "function",
                                            "function": {
                                                "name": name,
                                                "arguments": json.dumps(
                                                    {"broken": True}
                                                ),
                                            },
                                        }
                                    ],
                                },
                            }
                        ],
                        "usage": {"total_tokens": 3},
                    }
                return roster_handler(ROSTER_SUBMISSION, field_submission())(
                    kwargs
                )

            self.make_source_run(workspace, broken_field)
            state = init_network_debug_run(
                workspace,
                source_run_id=SOURCE_ID,
                debug_run_id=DEBUG_ID,
            )
            paper = state["papers"][0]
            self.assertEqual(paper["retry_nodes"], [])
            self.assertEqual(
                paper["candidates"]["candidate-001"]["state"], "non_retryable"
            )
            self.assertTrue(state["transport_clean"])

            summary = retry_network_nodes(
                workspace,
                DEBUG_ID,
                transport=RecordingTransport(
                    roster_handler(ROSTER_SUBMISSION, field_submission())
                ),
                api_key="k",
                base_url="u",
                sleep=lambda _: None,
            )
            self.assertEqual(summary["retried_papers"], [])
            with self.assertRaisesRegex(ValueError, "not currently network-retryable"):
                retry_network_nodes(
                    workspace,
                    DEBUG_ID,
                    transport=RecordingTransport(lambda kwargs: {}),
                    api_key="k",
                    base_url="u",
                    nodes=[f"{ARXIV_ID}:candidate-001"],
                    sleep=lambda _: None,
                )

            result = finalize_network_debug_run(workspace, DEBUG_ID)
            self.assertEqual(result["papers"][0]["status"], "partial")
            self.assertTrue(result["terminal_network_check"]["passed"])
            gate = evaluate_network_gate(debug_run_dir(workspace, DEBUG_ID))
            self.assertTrue(gate["passed"])


class NetworkDebugRefusalTest(unittest.TestCase):
    def make_initialized(self, tmp: str) -> Path:
        workspace = NetworkDebugEndToEndTest().make_workspace_with_pricing(tmp)
        NetworkDebugEndToEndTest().make_source_run(
            workspace,
            NetworkDebugEndToEndTest().failing_field_handler(),
        )
        init_network_debug_run(
            workspace,
            source_run_id=SOURCE_ID,
            debug_run_id=DEBUG_ID,
        )
        return workspace

    def test_double_init_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.make_initialized(tmp)
            with self.assertRaises(FileExistsError):
                init_network_debug_run(
                    workspace,
                    source_run_id=SOURCE_ID,
                    debug_run_id=DEBUG_ID,
                )

    def test_finalize_refused_while_nodes_remain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.make_initialized(tmp)
            with self.assertRaisesRegex(
                ValueError, "network-terminal nodes remaining"
            ):
                finalize_network_debug_run(workspace, DEBUG_ID)

    def test_workspace_drift_blocks_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.make_initialized(tmp)
            main_tex = (
                workspace / "literature" / ARXIV_ID / "arxiv_source" / "main.tex"
            )
            main_tex.write_text(
                main_tex.read_text(encoding="utf-8") + "\n% drifted\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "drifted"):
                retry_network_nodes(
                    workspace,
                    DEBUG_ID,
                    transport=RecordingTransport(lambda kwargs: {}),
                    api_key="k",
                    base_url="u",
                    sleep=lambda _: None,
                )

    def test_unknown_node_and_paper_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.make_initialized(tmp)
            with self.assertRaises(ValueError):
                retry_network_nodes(
                    workspace,
                    DEBUG_ID,
                    transport=RecordingTransport(lambda kwargs: {}),
                    api_key="k",
                    base_url="u",
                    nodes=["2406.99995:nonsense"],
                    sleep=lambda _: None,
                )
            with self.assertRaises(ValueError):
                retry_network_nodes(
                    workspace,
                    DEBUG_ID,
                    transport=RecordingTransport(lambda kwargs: {}),
                    api_key="k",
                    base_url="u",
                    papers=["9999.99999"],
                    sleep=lambda _: None,
                )

    def test_missing_credentials_block_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = self.make_initialized(tmp)
            with self.assertRaisesRegex(ValueError, "credentials"):
                retry_network_nodes(
                    workspace,
                    DEBUG_ID,
                    transport=RecordingTransport(lambda kwargs: {}),
                    api_key="",
                    base_url="",
                    sleep=lambda _: None,
                )


class NetworkDebugCliTest(unittest.TestCase):
    def load_module(self):
        import importlib.util

        path = ROOT / "scripts" / "run_hvs_network_debug.py"
        spec = importlib.util.spec_from_file_location("hvs_network_debug_cli", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_actions_parse(self) -> None:
        module = self.load_module()
        args = module.parse_args(
            [
                "--init",
                "--debug-run-id",
                DEBUG_ID,
                "--source-run",
                SOURCE_ID,
            ]
        )
        self.assertTrue(args.init)
        self.assertEqual(args.source_run, SOURCE_ID)
        args = module.parse_args(["--debug-run-id", DEBUG_ID, "--status"])
        self.assertTrue(args.status)
        args = module.parse_args(
            [
                "--debug-run-id",
                DEBUG_ID,
                "--retry-failed",
                "--paper",
                ARXIV_ID,
            ]
        )
        self.assertTrue(args.retry_failed)
        self.assertEqual(args.paper, [ARXIV_ID])
        args = module.parse_args(
            [
                "--debug-run-id",
                DEBUG_ID,
                "--retry-node",
                f"{ARXIV_ID}:roster",
                "--retry-node",
                f"{ARXIV_ID}:candidate-001",
            ]
        )
        self.assertEqual(
            args.retry_node, [f"{ARXIV_ID}:roster", f"{ARXIV_ID}:candidate-001"]
        )
        args = module.parse_args(["--debug-run-id", DEBUG_ID, "--finalize"])
        self.assertTrue(args.finalize)


if __name__ == "__main__":
    unittest.main()
