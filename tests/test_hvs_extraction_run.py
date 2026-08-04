"""End-to-end extraction pipeline integration tests with fake transports."""

from __future__ import annotations

import json
import io
import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from stella.hvs_extraction.finalize import PAPER_COMPLETE
from stella.hvs_extraction.method_config import default_hvs_extraction_method_config
from stella.hvs_extraction.run import (
    ProgressReporter,
    _aggregate_usage,
    _format_validation,
    build_run_summary,
    create_run_config,
    run_papers,
)
from stella.hvs_extraction.run_policy import (
    inspect_hvs_extraction_worktree,
    load_active_manifest,
    run_preflight,
    select_run_papers,
)
from stella.hvs_extraction.roster_stage import _atomic_write_json
from stella.benchmark.run_contract import require_v6_run_manifest
from stella.schema_registry import schema_ref
from tests.test_hvs_extraction_field_schema import valid_submission


ROOT = Path(__file__).resolve().parents[1]
ARXIV_ID = "2406.99995"
RUN_ID = "run-e2e-test"
MAIN_TEX = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "HVS-1 is unbound with radial velocity 805 km/s \\cite{smith2024}.\n"
    "\\begin{table}\\caption{Data}\\label{tab:data}\\end{table}\n"
    "\\bibliography{references}\n"
    "\\end{document}\n"
)
GOOD_ECSV = (
    "# %ECSV 1.0\n"
    "# ---\n"
    "# datatype:\n"
    "# - {name: col_001, datatype: string, description: Name}\n"
    "# - {name: col_002, datatype: string, description: RV}\n"
    "# schema: astropy-2.0\n"
    "col_001 col_002\n"
    "HVS-1 805\n"
)

ROSTER_SUBMISSION = {
    "candidates": [
        {
            "identifiers": [
                {
                    "value": "HVS-1",
                    "source_refs": [{"path": "main.tex", "start_line": 3, "end_line": 3}],
                }
            ],
            "qualification": {
                "reason": "The paper concludes HVS-1 is unbound.",
                "source_refs": [{"path": "main.tex", "start_line": 3, "end_line": 3}],
            },
        }
    ],
    "reviewed_exclusions": [],
    "range_groups": [],
}

BROKEN_ROSTER = {
    "candidates": [
        {
            "identifiers": [
                {
                    "value": "GHOST-9",
                    "source_refs": [{"path": "main.tex", "start_line": 3, "end_line": 3}],
                }
            ],
            "qualification": {
                "reason": "The paper concludes GHOST-9 is unbound.",
                "source_refs": [{"path": "main.tex", "start_line": 3, "end_line": 3}],
            },
        }
    ],
    "reviewed_exclusions": [],
    "range_groups": [],
}

EMPTY_ROSTER = {"candidates": [], "reviewed_exclusions": [], "range_groups": []}


def field_submission() -> dict:
    payload = valid_submission()
    payload["candidate_origin"]["origin_type"] = "cited_from_literature"
    payload["candidate_origin"]["bibkey"] = "smith2024"
    payload["core"]["observed_phase_space"]["radial_velocity"]["direct_evidence"][0][
        "source"
    ] = {
        "kind": "ecsv_cell",
        "path": "catalog_tables/t1.ecsv",
        "line": 8,
        "column": "col_002",
    }
    return payload


def make_workspace(tmp: str) -> Path:
    workspace = Path(tmp)
    shutil.copytree(
        ROOT / "skills/hvs-candidates-extraction/rules",
        workspace / "skills/hvs-candidates-extraction/rules",
    )
    paper_dir = workspace / "literature" / ARXIV_ID
    (paper_dir / "arxiv_source").mkdir(parents=True)
    (paper_dir / "arxiv_source" / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    (paper_dir / "arxiv_source" / "references.bib").write_text(
        "@article{smith2024,\n  author = {Smith, A.},\n  year = {2024}\n}\n",
        encoding="utf-8",
    )
    (paper_dir / "catalog_extraction.json").write_text(
        json.dumps(
            {
                "files": [
                    {
                        "id": "t1",
                        "status": "written",
                        "source_ref": {
                            "path": f"literature/{ARXIV_ID}/arxiv_source/main.tex",
                            "start_line": 4,
                            "end_line": 4,
                            "label": "tab:data",
                        },
                    }
                ],
                "tables": [
                    {
                        "id": "t1",
                        "status": "success",
                        "ecsv_path": f"literature/{ARXIV_ID}/catalog_tables/t1.ecsv",
                        "label": "tab:data",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (paper_dir / "catalog_tables").mkdir()
    (paper_dir / "catalog_tables" / "t1.ecsv").write_text(GOOD_ECSV, encoding="utf-8")
    return workspace


def fake_response(payload: dict, tool_name: str) -> dict:
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
                                "name": tool_name,
                                "arguments": json.dumps(payload, ensure_ascii=False),
                            },
                        }
                    ],
                },
            }
        ],
        "usage": {"total_tokens": 10},
    }


def tool_name_of(kwargs: dict) -> str:
    return kwargs["extra_body"]["tools"][0]["function"]["name"]


class RecordingTransport:
    def __init__(self, handler) -> None:
        self.handler = handler
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.handler(kwargs)

    def by_tool(self, name: str) -> int:
        return sum(1 for call in self.calls if tool_name_of(call) == name)


def roster_handler(roster_payload: dict, field_payload: dict):
    def handler(kwargs: dict):
        name = tool_name_of(kwargs)
        if name == "submit_candidate_fields":
            return fake_response(field_payload, name)
        return fake_response(roster_payload, name)

    return handler


class EndToEndTest(unittest.TestCase):
    def run_pipeline(
        self,
        workspace: Path,
        transport,
        *,
        run_id: str = RUN_ID,
        pricing_snapshot_path: Path | None = None,
    ):
        config = default_hvs_extraction_method_config(workspace)
        create_run_config(
            workspace,
            run_id,
            [ARXIV_ID],
            config=config,
            code={"commit": "test", "dirty": False},
        )
        return run_papers(
            workspace,
            run_id,
            config=config,
            transport=transport,
            sleep=lambda _: None,
            pricing_snapshot_path=pricing_snapshot_path,
        )

    def paper_result(self, workspace: Path) -> dict:
        path = (
            workspace
            / "benchmark/campaigns/hvs-extraction-v6/runs"
            / RUN_ID
            / "papers"
            / ARXIV_ID
            / "paper_result.json"
        )
        return json.loads(path.read_text(encoding="utf-8"))

    def test_full_chain_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            transport = RecordingTransport(
                roster_handler(ROSTER_SUBMISSION, field_submission())
            )
            summary = self.run_pipeline(workspace, transport)
            self.assertEqual(summary["totals"]["complete"], 1)
            paper = summary["papers"][ARXIV_ID]
            self.assertEqual(paper["status"], "complete")
            self.assertEqual(
                paper["stage_calls"],
                {"roster": 1, "core_fields": 1},
            )
            self.assertEqual(paper["total_tokens"], 20)
            result = self.paper_result(workspace)
            self.assertEqual(result["status"], "complete")
            self.assertEqual(
                result["candidates"][0]["bibliography"]["resolution"]["status"],
                "resolved",
            )
            run_config = json.loads(
                (
                    workspace
                    / "benchmark/campaigns/hvs-extraction-v6/runs"
                    / RUN_ID
                    / "run_config.json"
                ).read_text(encoding="utf-8")
            )
            self.assertTrue(run_config["method_fingerprint"])
            self.assertEqual(
                run_config["models"],
                {"roster": "glm-5.2", "core_fields": "deepseek-v4-pro"},
            )
            self.assertEqual(run_config["scope"], "targeted_dev")
            self.assertEqual(run_config["papers"], [ARXIV_ID])
            self.assertEqual(
                run_config["execution"]["field_request_policy"][
                    "max_physical_provider_requests"
                ],
                3,
            )
            self.assertTrue(run_config["run_fingerprint"])
            manifest = json.loads(
                (
                    workspace
                    / "benchmark/campaigns/hvs-extraction-v6/runs"
                    / RUN_ID
                    / "run_manifest.json"
                ).read_text(encoding="utf-8")
            )
            l1, l2 = require_v6_run_manifest(manifest)
            self.assertEqual(l1["complete"], [ARXIV_ID])
            self.assertEqual(l2["complete"], [ARXIV_ID])
            self.assertEqual(l2["candidate_counts"]["total"], 1)

    def test_terminal_run_automatically_persists_cost_when_pricing_is_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            pricing_path = (
                ROOT
                / "benchmark"
                / "pricing"
                / "tokendance"
                / "tokendance-2026-08-03-screenshots-v1.json"
            )
            workspace_pricing_path = (
                workspace
                / "benchmark"
                / "pricing"
                / "tokendance"
                / pricing_path.name
            )
            workspace_pricing_path.parent.mkdir(parents=True)
            shutil.copy2(pricing_path, workspace_pricing_path)
            transport = RecordingTransport(
                roster_handler(ROSTER_SUBMISSION, field_submission())
            )
            self.run_pipeline(
                workspace,
                transport,
            )
            cost_path = (
                workspace
                / "benchmark/campaigns/hvs-extraction-v6/runs"
                / RUN_ID
                / "run_cost.json"
            )
            artifact = json.loads(cost_path.read_text(encoding="utf-8"))
            self.assertEqual(artifact["run_id"], RUN_ID)
            self.assertEqual(
                artifact["estimated_api_cost"]["pricing_snapshot"]["snapshot_id"],
                "tokendance-2026-08-03-screenshots-v1",
            )

    def test_v3_core_delivery_is_written_and_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            transport = RecordingTransport(
                roster_handler(ROSTER_SUBMISSION, field_submission())
            )
            summary = self.run_pipeline(workspace, transport)
            paper = summary["papers"][ARXIV_ID]
            self.assertEqual(paper["status"], "complete")
            self.assertEqual(
                paper["stage_calls"],
                {"roster": 1, "core_fields": 1},
            )
            core_path = (
                workspace
                / "benchmark/campaigns/hvs-extraction-v6/runs"
                / RUN_ID
                / "papers"
                / ARXIV_ID
                / "literature_hvs_candidates.json"
            )
            core = json.loads(core_path.read_text(encoding="utf-8"))
            self.assertEqual(
                core["schema"],
                {"name": "literature_hvs_candidates", "version": 3},
            )
            self.assertEqual(core["inputs"]["source_run_id"], RUN_ID)

    def test_empty_roster_is_complete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            transport = RecordingTransport(
                roster_handler(EMPTY_ROSTER, field_submission())
            )
            summary = self.run_pipeline(workspace, transport)
            paper = summary["papers"][ARXIV_ID]
            self.assertEqual(paper["status"], "complete")
            self.assertEqual(paper["roster_status"], "no_candidates")
            self.assertEqual(paper["stage_calls"]["core_fields"], 0)

    def test_roster_failure_is_paper_failed_without_field_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            transport = RecordingTransport(
                roster_handler(BROKEN_ROSTER, field_submission())
            )
            summary = self.run_pipeline(workspace, transport)
            paper = summary["papers"][ARXIV_ID]
            self.assertEqual(paper["status"], "failed")
            self.assertEqual(paper["failure_code"], "extractor_terminal_failure")
            self.assertEqual(paper["stage_calls"]["core_fields"], 0)
            self.assertEqual(transport.by_tool("submit_candidate_fields"), 0)
            # Every failed slot still ran an initial call plus one evidence
            # correction: attempts and tokens reach the ledger.
            self.assertEqual(paper["stage_calls"]["roster"], 2)
            self.assertEqual(paper["total_tokens"], 20)

    def test_same_run_id_cannot_start_twice_or_overwrite_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            first = RecordingTransport(roster_handler(ROSTER_SUBMISSION, field_submission()))
            self.run_pipeline(workspace, first)
            config_path = (
                workspace
                / "benchmark/campaigns/hvs-extraction-v6/runs"
                / RUN_ID
                / "run_config.json"
            )
            baseline = config_path.read_bytes()
            second = RecordingTransport(roster_handler(ROSTER_SUBMISSION, field_submission()))
            with self.assertRaises(FileExistsError):
                self.run_pipeline(workspace, second)
            self.assertEqual(second.calls, [])
            self.assertEqual(config_path.read_bytes(), baseline)

    def test_failed_run_cannot_be_resumed_and_new_id_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            broken = RecordingTransport(roster_handler(BROKEN_ROSTER, field_submission()))
            summary = self.run_pipeline(workspace, broken)
            self.assertEqual(summary["totals"]["failed"], 1)
            config = default_hvs_extraction_method_config(workspace)
            fixed = RecordingTransport(roster_handler(ROSTER_SUBMISSION, field_submission()))
            with self.assertRaises(FileExistsError):
                run_papers(
                    workspace,
                    RUN_ID,
                    config=config,
                    transport=fixed,
                    sleep=lambda _: None,
                )
            self.assertEqual(fixed.calls, [])
            summary = self.run_pipeline(
                workspace, fixed, run_id="run-e2e-test-fixed"
            )
            self.assertGreater(len(fixed.calls), 0)
            self.assertEqual(summary["totals"]["complete"], 1)


class ImmutableRunContractTest(unittest.TestCase):
    def test_cli_defaults_to_single_and_has_no_resume_flag(self) -> None:
        path = ROOT / "scripts/run_hvs_candidate_extraction.py"
        spec = importlib.util.spec_from_file_location("hvs_runner_cli", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        args = module.parse_args(
            [
                "--dev",
                "--run-id",
                "new-run",
                "--roster-thinking",
                "enabled",
                "--roster-reasoning-effort",
                "high",
                "--core-field-reasoning-effort",
                "low",
            ]
        )
        self.assertEqual(args.roster_thinking, "enabled")
        self.assertEqual(args.roster_reasoning_effort, "high")
        self.assertEqual(args.core_field_reasoning_effort, "low")
        self.assertFalse(hasattr(args, "variant"))
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            module.parse_args(["--dev", "--run-id", "new-run", "--rerun-failed"])
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            module.parse_args(["--dev", "--run-id", "new-run", "--variant", "single"])

    def test_malicious_run_ids_are_rejected_without_creating_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            config = default_hvs_extraction_method_config(workspace)
            for run_id in ("../escape", "/absolute", "two/parts", "bad id", ".hidden"):
                with self.subTest(run_id=run_id), self.assertRaises(ValueError):
                    create_run_config(
                        workspace,
                        run_id,
                        [ARXIV_ID],
                        config=config,
                        code={"revision": "test"},
                    )

    def test_concurrent_same_id_has_exactly_one_winner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            config = default_hvs_extraction_method_config(workspace)

            def reserve() -> str:
                create_run_config(
                    workspace,
                    RUN_ID,
                    [ARXIV_ID],
                    config=config,
                    code={"revision": "test"},
                )
                return "created"

            outcomes: list[str] = []
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(reserve) for _ in range(2)]
                for future in futures:
                    try:
                        outcomes.append(future.result())
                    except FileExistsError:
                        outcomes.append("rejected")
            self.assertEqual(sorted(outcomes), ["created", "rejected"])
            config_path = (
                workspace
                / "benchmark/campaigns/hvs-extraction-v6/runs"
                / RUN_ID
                / "run_config.json"
            )
            self.assertTrue(config_path.is_file())

    def test_summary_uses_config_papers_and_marks_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            config = default_hvs_extraction_method_config(workspace)
            create_run_config(
                workspace,
                RUN_ID,
                [ARXIV_ID],
                config=config,
                code={"revision": "test"},
            )
            extra = (
                workspace
                / "benchmark/campaigns/hvs-extraction-v6/runs"
                / RUN_ID
                / "papers"
                / "residual-not-in-config"
            )
            extra.mkdir(parents=True)
            summary = build_run_summary(workspace, RUN_ID)
            self.assertEqual(list(summary["papers"]), [ARXIV_ID])
            self.assertEqual(summary["papers"][ARXIV_ID]["status"], "missing")
            self.assertEqual(summary["totals"]["missing"], 1)
            self.assertEqual(summary["totals"]["delivery_rate"], 0.0)

    def test_harness_failure_isolated_from_other_paper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            config = default_hvs_extraction_method_config(workspace)
            other_id = "2406.99994"
            create_run_config(
                workspace,
                RUN_ID,
                [ARXIV_ID, other_id],
                config=config,
                code={"revision": "test"},
            )

            def fake_run_paper(
                workspace_arg: Path,
                run_id: str,
                arxiv_id: str,
                **_kwargs,
            ) -> dict:
                if arxiv_id == ARXIV_ID:
                    raise RuntimeError("synthetic worker crash")
                artifact = {
                    "schema": schema_ref(
                        "hvs_extraction.paper_result"
                    ),
                    "generated_at": "2026-07-26T00:00:00+00:00",
                    "paper": {"arxiv_id": arxiv_id},
                    "run_id": run_id,
                    "status": PAPER_COMPLETE,
                    "roster_status": "no_candidates",
                    "failure": None,
                    "roster": None,
                    "candidates": [],
                }
                path = (
                    workspace_arg
                    / "benchmark/campaigns/hvs-extraction-v6/runs"
                    / run_id
                    / "papers"
                    / arxiv_id
                    / "paper_result.json"
                )
                _atomic_write_json(path, artifact)
                return artifact

            with patch(
                "stella.hvs_extraction.run.run_paper",
                side_effect=fake_run_paper,
            ):
                summary = run_papers(
                    workspace,
                    RUN_ID,
                    config=config,
                    transport=lambda **_kwargs: {},
                )
            self.assertEqual(summary["papers"][ARXIV_ID]["status"], "failed")
            self.assertEqual(
                summary["papers"][ARXIV_ID]["failure_code"], "harness_failure"
            )
            self.assertEqual(summary["papers"][other_id]["status"], "complete")

    def test_keyboard_interrupt_persists_interrupted_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            config = default_hvs_extraction_method_config(workspace)
            create_run_config(
                workspace,
                RUN_ID,
                [ARXIV_ID],
                config=config,
                code={"revision": "test"},
                paper_workers=1,
            )
            with patch(
                "stella.hvs_extraction.run.run_paper",
                side_effect=KeyboardInterrupt,
            ), self.assertRaises(KeyboardInterrupt):
                run_papers(
                    workspace,
                    RUN_ID,
                    config=config,
                    transport=lambda **_kwargs: {},
                )
            summary_path = (
                workspace
                / "benchmark/campaigns/hvs-extraction-v6/runs"
                / RUN_ID
                / "run_summary.json"
            )
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["state"], "interrupted")
            self.assertEqual(summary["totals"]["missing"], 1)
            with self.assertRaises(FileExistsError):
                run_papers(
                    workspace,
                    RUN_ID,
                    config=config,
                    transport=lambda **_kwargs: {},
                )

    def test_live_progress_has_safe_stage_attempt_duration_and_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            transport = RecordingTransport(
                roster_handler(ROSTER_SUBMISSION, field_submission())
            )
            config = default_hvs_extraction_method_config(workspace)
            create_run_config(
                workspace,
                RUN_ID,
                [ARXIV_ID],
                config=config,
                code={"revision": "test"},
                paper_workers=1,
                candidate_workers=1,
            )
            stream = io.StringIO()
            run_papers(
                workspace,
                RUN_ID,
                config=config,
                transport=transport,
                sleep=lambda _: None,
                progress=ProgressReporter(stream),
            )
            output = stream.getvalue()
            for expected in (
                "run_start",
                "paper_start",
                "stage=prepare",
                "stage=roster",
                "stage=field",
                "stage=finalize",
                "candidate_start",
                "api_attempt_start",
                "api_attempt_end",
                "duration_ms=",
                "tokens=",
                "cumulative_tokens=",
                "paper_end",
                "run_end",
            ):
                self.assertIn(expected, output)
            for forbidden in (
                "secret-key",
                "HVS-1 is unbound",
                '"arguments"',
                "hidden reasoning",
            ):
                self.assertNotIn(forbidden, output)

    def test_dev_and_test_smoke_selection_boundaries(self) -> None:
        _path, manifest, _sha = load_active_manifest(ROOT)
        dev = [paper["arxiv_id"] for paper in manifest["papers"] if paper["split"] == "dev"]
        test = [paper["arxiv_id"] for paper in manifest["papers"] if paper["split"] == "test"]
        scope, papers = select_run_papers(
            manifest,
            full_dev=True,
            requested_ids=None,
            allow_test_smoke=False,
        )
        self.assertEqual(scope, "full_dev")
        self.assertEqual(papers, dev)
        with self.assertRaisesRegex(ValueError, "forbidden"):
            select_run_papers(
                manifest,
                full_dev=False,
                requested_ids=[test[0]],
                allow_test_smoke=False,
            )
        scope, papers = select_run_papers(
            manifest,
            full_dev=False,
            requested_ids=[test[0]],
            allow_test_smoke=True,
        )
        self.assertEqual(scope, "test_smoke")
        self.assertEqual(papers, [test[0]])

    def test_worktree_guard_warns_root_file_and_blocks_execution_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=workspace,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "HVS extraction Test"],
                cwd=workspace,
                check=True,
            )
            (workspace / "README.md").write_text("tracked\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=workspace, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "fixture"], cwd=workspace, check=True
            )
            (workspace / "kimi-export.md").write_text("chat\n", encoding="utf-8")
            (workspace / "src").mkdir()
            (workspace / "src/new_runner.py").write_text(
                "print('x')\n", encoding="utf-8"
            )
            state = inspect_hvs_extraction_worktree(workspace)
            self.assertFalse(state["clean_for_dev"])
            self.assertEqual(state["blocking_untracked"], ["src/new_runner.py"])
            self.assertTrue(
                any("kimi-export.md" in item for item in state["warnings"])
            )

    def test_preflight_only_neither_creates_run_nor_calls_transport(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=workspace,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "HVS extraction Test"],
                cwd=workspace,
                check=True,
            )
            subprocess.run(["git", "add", "."], cwd=workspace, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "fixture"], cwd=workspace, check=True
            )
            config = default_hvs_extraction_method_config(workspace)
            result = run_preflight(
                workspace,
                RUN_ID,
                [ARXIV_ID],
                config=config,
                api_key="present",
                base_url="https://example.invalid",
            )
            self.assertEqual(result["api_calls"], 0)
            self.assertFalse(result["run_created"])
            self.assertFalse(
                (
                    workspace
                    / "benchmark/campaigns/hvs-extraction-v6/runs"
                    / RUN_ID
                ).exists()
            )


class RealPaperEndToEndTest(unittest.TestCase):
    def test_2406_14134_full_chain(self) -> None:
        real = ROOT / "literature/2406.14134"
        required = ["arxiv_source", "catalog_tables", "catalog_extraction.json"]
        if not all((real / name).exists() for name in required):
            self.skipTest("2406.14134 assets are not available locally")
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            shutil.copytree(
                ROOT / "skills/hvs-candidates-extraction/rules",
                workspace / "skills/hvs-candidates-extraction/rules",
            )
            paper_dir = workspace / "literature/2406.14134"
            paper_dir.mkdir(parents=True)
            shutil.copytree(real / "arxiv_source", paper_dir / "arxiv_source")
            shutil.copytree(real / "catalog_tables", paper_dir / "catalog_tables")
            shutil.copy2(
                real / "catalog_extraction.json", paper_dir / "catalog_extraction.json"
            )
            roster = {
                "candidates": [
                    {
                        "identifiers": [
                            {
                                "value": "16647293239608960",
                                "source_refs": [
                                    {"path": "main.tex", "start_line": 260, "end_line": 260}
                                ],
                            }
                        ],
                        "qualification": {
                            "reason": "The paper lists this source in its HVS candidate catalogue table.",
                            "source_refs": [
                                {"path": "main.tex", "start_line": 255, "end_line": 260}
                            ],
                        },
                    }
                ],
                "reviewed_exclusions": [],
                "range_groups": [],
            }
            fields = valid_submission()
            fields["candidate_origin"]["origin_type"] = "introduced_by_this_paper"
            fields["candidate_origin"]["bibkey"] = None
            fields["candidate_origin"]["evidence"] = [
                {"kind": "text", "path": "main.tex", "start_line": 255, "end_line": 260}
            ]
            fields["core"]["observed_phase_space"]["radial_velocity"][
                "direct_evidence"
            ][0]["source"] = {
                "kind": "ecsv_cell",
                "path": "catalog_tables/table-tab-source_table.ecsv",
                "line": 17,
                "column": "col_002",
            }
            transport = RecordingTransport(roster_handler(roster, fields))
            config = default_hvs_extraction_method_config(workspace)
            create_run_config(
                workspace,
                RUN_ID,
                ["2406.14134"],
                config=config,
                code={"commit": "test", "dirty": False},
            )
            summary = run_papers(
                workspace,
                RUN_ID,
                config=config,
                transport=transport,
                sleep=lambda _: None,
            )
            paper = summary["papers"]["2406.14134"]
            self.assertEqual(paper["status"], "complete")
            result = json.loads(
                (
                    workspace
                    / "benchmark/campaigns/hvs-extraction-v6/runs"
                    / RUN_ID
                    / "papers/2406.14134/paper_result.json"
                ).read_text(encoding="utf-8")
            )
            source = result["candidates"][0]["fields"]["core"]["observed_phase_space"][
                "radial_velocity"
            ]["direct_evidence"][0]["source"]
            self.assertEqual(source["cell_raw_value"], "805")
            self.assertEqual(
                result["roster"]["candidates"][0]["record_id"], "candidate-001"
            )


class L0TelemetryTest(unittest.TestCase):
    def test_format_outcomes_cover_first_pass_repair_failure_and_transport(self) -> None:
        units = [
            ({"status": "valid", "attempts": [{"outcome": "response_received"}]}, "valid"),
            (
                {
                    "status": "valid",
                    "attempts": [{"outcome": "response_received"}] * 2,
                    "repair_history": [
                        {"type": "format_correction", "final_result": "accepted"}
                    ],
                },
                "valid",
            ),
            (
                {
                    "status": "failed",
                    "attempts": [{"outcome": "response_received"}] * 2,
                    "repair_history": [
                        {"type": "format_correction", "final_result": "failed"}
                    ],
                },
                "valid",
            ),
            ({"status": "failed", "attempts": [{"outcome": "transport_error"}]}, "valid"),
        ]
        self.assertEqual(
            _format_validation(units),
            {
                "observed_units": 3,
                "valid_first_pass": 1,
                "valid_after_correction": 1,
                "invalid": 1,
                "not_observed": 1,
                "first_pass_rate": 0.333333,
                "final_valid_rate": 0.666667,
            },
        )

    def test_usage_prefers_flat_cache_and_counts_all_retry_correction_calls(self) -> None:
        usage = _aggregate_usage(
            [
                {
                    "attempts": [
                        {"outcome": "transport_error"},
                        {"outcome": "response_received"},
                        {"outcome": "response_received"},
                    ],
                    "usages": [
                        {
                            "prompt_tokens": 100,
                            "prompt_cache_hit_tokens": 40,
                            "prompt_tokens_details": {"cached_tokens": 20},
                            "completion_tokens": 30,
                            "completion_tokens_details": {"reasoning_tokens": 10},
                            "total_tokens": 130,
                        },
                        {
                            "prompt_tokens": 50,
                            "prompt_tokens_details": {"cached_tokens": 5},
                            "completion_tokens": 20,
                            "completion_tokens_details": {"reasoning_tokens": 5},
                            "total_tokens": 70,
                        },
                    ],
                }
            ]
        )
        self.assertEqual(usage["api_calls"], 3)
        self.assertEqual(usage["prompt_tokens"], 150)
        self.assertEqual(usage["cached_input_tokens"], 45)
        self.assertEqual(usage["uncached_input_tokens"], 105)
        self.assertEqual(usage["completion_tokens"], 50)
        self.assertEqual(usage["reasoning_tokens"], 15)
        self.assertEqual(usage["total_tokens"], 200)
        self.assertEqual(usage["telemetry_status"], "partial")
        self.assertIn("cache_token_conflict", usage["warnings"])


if __name__ == "__main__":
    unittest.main()
