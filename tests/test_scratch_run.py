"""End-to-end scratch pipeline integration tests with fake transports."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from stella.benchmark.scratch.method_config import default_scratch_method_config
from stella.benchmark.scratch.run import create_run_config, run_papers
from test_scratch_field_schema import valid_submission


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
}

EMPTY_ROSTER = {"candidates": [], "reviewed_exclusions": []}


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
    def run_pipeline(self, workspace: Path, transport, *, variant: str = "ensemble", rerun_failed: bool = False):
        config = default_scratch_method_config(workspace)
        create_run_config(
            workspace,
            RUN_ID,
            [ARXIV_ID],
            config=config,
            variant=variant,
            code={"commit": "test", "dirty": False},
        )
        return run_papers(
            workspace,
            RUN_ID,
            [ARXIV_ID],
            config=config,
            variant=variant,
            transport=transport,
            rerun_failed=rerun_failed,
            sleep=lambda _: None,
        )

    def paper_result(self, workspace: Path) -> dict:
        path = (
            workspace
            / "benchmark/scratch/hvs-extraction/runs"
            / RUN_ID
            / "papers"
            / ARXIV_ID
            / "paper_result.json"
        )
        return json.loads(path.read_text(encoding="utf-8"))

    def test_full_chain_complete_ensemble(self) -> None:
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
                {"roster_extractor": 3, "adjudicator": 1, "field": 1},
            )
            self.assertEqual(paper["total_tokens"], 50)
            result = self.paper_result(workspace)
            self.assertEqual(result["status"], "complete")
            self.assertEqual(
                result["candidates"][0]["bibliography"]["resolution"]["status"],
                "resolved",
            )
            run_config = json.loads(
                (
                    workspace
                    / "benchmark/scratch/hvs-extraction/runs"
                    / RUN_ID
                    / "run_config.json"
                ).read_text(encoding="utf-8")
            )
            self.assertTrue(run_config["method_fingerprint"])
            self.assertEqual(run_config["variant"], "ensemble")

    def test_full_chain_complete_single_variant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            transport = RecordingTransport(
                roster_handler(ROSTER_SUBMISSION, field_submission())
            )
            summary = self.run_pipeline(workspace, transport, variant="single")
            paper = summary["papers"][ARXIV_ID]
            self.assertEqual(paper["status"], "complete")
            self.assertEqual(
                paper["stage_calls"],
                {"roster_extractor": 1, "adjudicator": 0, "field": 1},
            )

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
            self.assertEqual(paper["stage_calls"]["field"], 0)

    def test_roster_failure_is_paper_failed_without_field_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            transport = RecordingTransport(
                roster_handler(BROKEN_ROSTER, field_submission())
            )
            summary = self.run_pipeline(workspace, transport)
            paper = summary["papers"][ARXIV_ID]
            self.assertEqual(paper["status"], "failed")
            self.assertEqual(paper["failure_code"], "insufficient_valid_proposals")
            self.assertEqual(paper["stage_calls"]["field"], 0)
            self.assertEqual(transport.by_tool("submit_candidate_fields"), 0)
            # Every failed slot still ran an initial call plus one evidence
            # correction: attempts and tokens reach the ledger.
            self.assertEqual(paper["stage_calls"]["roster_extractor"], 6)
            self.assertEqual(paper["stage_calls"]["adjudicator"], 0)
            self.assertEqual(paper["total_tokens"], 60)

    def test_resume_skips_completed_papers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            first = RecordingTransport(roster_handler(ROSTER_SUBMISSION, field_submission()))
            self.run_pipeline(workspace, first)
            baseline = len(first.calls)
            second = RecordingTransport(roster_handler(ROSTER_SUBMISSION, field_submission()))
            summary = self.run_pipeline(workspace, second)
            self.assertEqual(len(second.calls), 0)
            self.assertEqual(summary["totals"]["complete"], 1)
            self.assertGreater(baseline, 0)

    def test_failed_paper_reruns_only_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            broken = RecordingTransport(roster_handler(BROKEN_ROSTER, field_submission()))
            summary = self.run_pipeline(workspace, broken)
            self.assertEqual(summary["totals"]["failed"], 1)
            skipped = RecordingTransport(roster_handler(BROKEN_ROSTER, field_submission()))
            self.run_pipeline(workspace, skipped)
            self.assertEqual(len(skipped.calls), 0)
            fixed = RecordingTransport(roster_handler(ROSTER_SUBMISSION, field_submission()))
            summary = self.run_pipeline(workspace, fixed, rerun_failed=True)
            self.assertGreater(len(fixed.calls), 0)
            self.assertEqual(summary["totals"]["complete"], 1)


class RealPaperEndToEndTest(unittest.TestCase):
    def test_2406_14134_full_chain(self) -> None:
        real = ROOT / "literature/2406.14134"
        if not real.is_dir():
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
            config = default_scratch_method_config(workspace)
            create_run_config(
                workspace,
                RUN_ID,
                ["2406.14134"],
                config=config,
                variant="ensemble",
                code={"commit": "test", "dirty": False},
            )
            summary = run_papers(
                workspace,
                RUN_ID,
                ["2406.14134"],
                config=config,
                variant="ensemble",
                transport=transport,
                sleep=lambda _: None,
            )
            paper = summary["papers"]["2406.14134"]
            self.assertEqual(paper["status"], "complete")
            result = json.loads(
                (
                    workspace
                    / "benchmark/scratch/hvs-extraction/runs"
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


if __name__ == "__main__":
    unittest.main()
