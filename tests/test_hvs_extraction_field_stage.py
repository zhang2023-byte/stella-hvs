"""Field stage orchestration tests: per-candidate parallel extraction (D025, D044-D046)."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from stella.hvs_extraction.method_config import (
    HvsComponentHashes,
    HvsContextBudget,
    HvsExtractionMethodConfig,
    HvsModelRoute,
)
from stella.hvs_extraction.prepare import (
    build_prepared_input,
    estimate_tokens,
    write_prepared_input,
)
from stella.hvs_extraction.field_stage import (
    FIELD_EXTRACTION_FAILED,
    FIELDS_COMPLETE,
    NO_TRUSTED_ROSTER,
    run_field_stage,
)
from tests.test_hvs_extraction_field_schema import valid_submission


ROOT = Path(__file__).resolve().parents[1]
ARXIV_ID = "2406.99997"
RUN_ID = "run-field-test"
MAIN_TEX = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "HVS-1 is unbound with radial velocity 805 km/s \\cite{smith2024}.\n"
    "HVS-2 is also unbound.\n"
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
    "HVS-2 900\n"
)


def budget(limit: int = 900000) -> HvsContextBudget:
    return HvsContextBudget(
        model_context_limit=limit,
        reserve_system_and_rules=8000,
        reserve_tool_schema=4000,
        reserve_candidate_suffix=2000,
        reserve_output=8000,
        reserve_provider_framing=1000,
    )


def frozen_config() -> HvsExtractionMethodConfig:
    extractor = HvsModelRoute(
        provider="deepseek",
        model="deepseek-v4-pro",
        structured_output_mode="tool_submission",
        temperature=0.2,
        top_p=1.0,
        seed_honored=True,
    )
    adjudicator = HvsModelRoute(
        provider="bigmodel",
        model="glm-5.2",
        structured_output_mode="tool_submission",
        temperature=0.0,
        top_p=1.0,
        seed_honored=False,
    )
    return HvsExtractionMethodConfig(
        roster_extractor=extractor,
        roster_adjudicator=adjudicator,
        field_extractor=extractor,
        roster_extractor_seeds=(101, 202, 303),
        roster_context_budget=budget(),
        field_context_budget=budget(),
        components=HvsComponentHashes(
            rule_profile_sha256={"hvs_candidate_core_fields_tex_ecsv": "a" * 64},
            prompt_template_sha256={"field_extractor": "b" * 64},
            submission_schema_sha256={"submit_candidate_fields": "c" * 64},
        ),
    )


def ref(path: str, start: int, end: int, text: str) -> dict:
    return {
        "path": path,
        "start_line": start,
        "end_line": end,
        "resolved_text": text,
        "source_sha256": "0" * 64,
    }


def roster_candidate(index: int, name: str, line: int, text: str) -> dict:
    return {
        "record_id": f"candidate-{index:03d}",
        "display_name": name,
        "identifiers": [
            {
                "value": name,
                "source_refs": [ref("main.tex", line, line, text)],
                "recognition": {"kind": "other"},
            }
        ],
        "qualification": {
            "reason": f"The paper concludes {name} is unbound.",
            "source_refs": [ref("main.tex", line, line, text)],
        },
    }


def make_workspace(tmp: str, *, field_limit: int = 900000, roster_candidates: list[dict] | None = None) -> Path:
    workspace = Path(tmp)
    shutil.copytree(
        ROOT / "skills/hvs-candidates-extraction/rules",
        workspace / "skills/hvs-candidates-extraction/rules",
    )
    paper_dir = workspace / "literature" / ARXIV_ID
    (paper_dir / "arxiv_source").mkdir(parents=True)
    (paper_dir / "arxiv_source" / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    (paper_dir / "arxiv_source" / "references.bib").write_text(
        "@article{smith2024,\n"
        "  author = {Smith, A.},\n"
        "  year = {2024},\n"
        "  title = {HVS survey},\n"
        "  doi = {10.1234/x}\n"
        "}\n",
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
                            "start_line": 5,
                            "end_line": 5,
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
    artifact = build_prepared_input(
        workspace,
        ARXIV_ID,
        roster_budget=budget(),
        field_budget=budget(field_limit),
    )
    assert artifact["status"] == "prepared", artifact.get("failure")
    write_prepared_input(workspace, RUN_ID, artifact)
    candidates = (
        roster_candidates
        if roster_candidates is not None
        else [
            roster_candidate(1, "HVS-1", 3, "HVS-1 is unbound with radial velocity 805 km/s \\cite{smith2024}."),
            roster_candidate(2, "HVS-2", 4, "HVS-2 is also unbound."),
        ]
    )
    roster_final = {
        "schema": {"name": "hvs_extraction.roster_final", "version": 1},
        "paper": {"arxiv_id": ARXIV_ID},
        "run_id": RUN_ID,
        "variant": "ensemble",
        "status": "roster_complete",
        "roster_status": "candidates_found" if candidates else "no_candidates",
        "candidates": candidates,
        "reviewed_exclusions": [],
    }
    paper_out = (
        workspace
        / "benchmark/campaigns/hvs-extraction-v5/runs"
        / RUN_ID
        / "papers"
        / ARXIV_ID
    )
    paper_out.mkdir(parents=True)
    (paper_out / "roster_final.json").write_text(
        json.dumps(roster_final), encoding="utf-8"
    )
    return workspace


def fake_response(payload: dict) -> dict:
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
                                "name": "submit_candidate_fields",
                                "arguments": json.dumps(payload, ensure_ascii=False),
                            },
                        }
                    ],
                },
            }
        ]
    }

def no_call_response() -> dict:
    return {
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "not submitted"},
            }
        ]
    }


def with_usage(response: dict, tokens: int) -> dict:
    response["usage"] = {"total_tokens": tokens}
    return response


def ecsv_submission() -> dict:
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


def candidate_artifact(workspace: Path, record_id: str) -> dict:
    path = (
        workspace
        / "benchmark/campaigns/hvs-extraction-v5/runs"
        / RUN_ID
        / "papers"
        / ARXIV_ID
        / "candidates"
        / f"{record_id}.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


class RecordingTransport:
    def __init__(self, handler) -> None:
        self.handler = handler
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.handler(kwargs)


def assigned_candidate_text(kwargs: dict) -> str:
    user = kwargs["messages"][1]["content"]
    return user.split("===== BEGIN ASSIGNED CANDIDATE =====", 1)[1]


class FieldStageTest(unittest.TestCase):
    def test_two_candidates_complete_in_parallel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            transport = RecordingTransport(lambda kwargs: fake_response(ecsv_submission()))
            summary = run_field_stage(
                workspace,
                RUN_ID,
                ARXIV_ID,
                config=frozen_config(),
                transport=transport,
                sleep=lambda _: None,
            )
            self.assertEqual(
                summary["candidates"],
                {"candidate-001": FIELDS_COMPLETE, "candidate-002": FIELDS_COMPLETE},
            )
            self.assertEqual(len(transport.calls), 2)
            first = candidate_artifact(workspace, "candidate-001")
            self.assertEqual(first["status"], FIELDS_COMPLETE)
            self.assertIsNone(first["failure"])
            source = first["fields"]["core"]["observed_phase_space"]["radial_velocity"][
                "direct_evidence"
            ][0]["source"]
            self.assertEqual(source["cell_raw_value"], "805")
            self.assertEqual(source["column_header"], "RV")
            bibliography = first["bibliography"]
            self.assertEqual(
                bibliography["resolution"]["status"], "resolved"
            )
            self.assertEqual(
                bibliography["resolution"]["reference"]["metadata"]["doi"], "10.1234/x"
            )
            self.assertTrue(bibliography["paper_reassesses_unbound_status"])
            self.assertEqual(
                first["provenance"]["rule_profile"],
                "hvs_candidate_core_fields_tex_ecsv",
            )

    def test_candidate_sees_only_its_own_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            transport = RecordingTransport(lambda kwargs: fake_response(ecsv_submission()))
            run_field_stage(
                workspace,
                RUN_ID,
                ARXIV_ID,
                config=frozen_config(),
                transport=transport,
                sleep=lambda _: None,
            )
            for call in transport.calls:
                suffix = assigned_candidate_text(call)
                self.assertNotIn("record_id", suffix)
                for message in call["messages"]:
                    self.assertNotIn("Proposal A", message["content"])
            suffixes = sorted(assigned_candidate_text(call) for call in transport.calls)
            self.assertIn("HVS-1", suffixes[0])
            self.assertNotIn("HVS-2", suffixes[0])
            self.assertIn("HVS-2", suffixes[1])
            self.assertNotIn("HVS-1", suffixes[1].split("END ASSIGNED")[0])

    def test_one_candidate_failure_is_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            state = {"calls": 0}

            def handler(kwargs: dict):
                state["calls"] += 1
                suffix = assigned_candidate_text(kwargs)
                if "HVS-2" in suffix:
                    response = fake_response({"broken": True})
                    response["usage"] = {"total_tokens": 4}
                    return response
                return fake_response(ecsv_submission())

            transport = RecordingTransport(handler)
            summary = run_field_stage(
                workspace,
                RUN_ID,
                ARXIV_ID,
                config=frozen_config(),
                transport=transport,
                sleep=lambda _: None,
            )
            self.assertEqual(summary["candidates"]["candidate-001"], FIELDS_COMPLETE)
            self.assertEqual(
                summary["candidates"]["candidate-002"], FIELD_EXTRACTION_FAILED
            )
            failed = candidate_artifact(workspace, "candidate-002")
            self.assertIsNone(failed["fields"])
            self.assertEqual(failed["failure"]["code"], "submission_format_failure")
            # The failed candidate burned an initial call plus one format
            # correction; both belong in the cost ledger.
            self.assertEqual(len(failed["attempts"]), 2)
            self.assertEqual(
                [usage["total_tokens"] for usage in failed["usages"]], [4, 4]
            )
            complete = candidate_artifact(workspace, "candidate-001")
            self.assertEqual(complete["status"], FIELDS_COMPLETE)

    def test_format_then_evidence_repair_share_three_calls_and_are_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            only = [
                roster_candidate(
                    1,
                    "HVS-1",
                    3,
                    "HVS-1 is unbound with radial velocity 805 km/s \\cite{smith2024}.",
                )
            ]
            workspace = make_workspace(tmp, roster_candidates=only)
            invalid_evidence = ecsv_submission()
            invalid_evidence["core"]["observed_phase_space"]["radial_velocity"][
                "direct_evidence"
            ][0]["source"]["line"] = 999
            responses = [
                with_usage(no_call_response(), 3),
                with_usage(fake_response(invalid_evidence), 5),
                with_usage(fake_response(ecsv_submission()), 7),
            ]
            state = {"index": 0}

            def handler(_kwargs: dict) -> dict:
                response = responses[state["index"]]
                state["index"] += 1
                return response

            transport = RecordingTransport(handler)
            summary = run_field_stage(
                workspace,
                RUN_ID,
                ARXIV_ID,
                config=frozen_config(),
                transport=transport,
                sleep=lambda _: None,
                max_workers=1,
            )
            self.assertEqual(summary["candidates"]["candidate-001"], FIELDS_COMPLETE)
            self.assertEqual(len(transport.calls), 3)
            artifact = candidate_artifact(workspace, "candidate-001")
            self.assertEqual(
                [item["type"] for item in artifact["repair_history"]],
                ["format_correction", "evidence_correction"],
            )
            self.assertEqual(
                [usage["total_tokens"] for usage in artifact["usages"]],
                [3, 5, 7],
            )
            self.assertTrue(
                all(item["final_status"] == "ok" for item in artifact["repair_history"])
            )

    def test_null_fields_differ_from_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            transport = RecordingTransport(lambda kwargs: fake_response(valid_submission()))
            summary = run_field_stage(
                workspace,
                RUN_ID,
                ARXIV_ID,
                config=frozen_config(),
                transport=transport,
                sleep=lambda _: None,
            )
            self.assertEqual(summary["candidates"]["candidate-001"], FIELDS_COMPLETE)
            artifact = candidate_artifact(workspace, "candidate-001")
            core = artifact["fields"]["core"]
            self.assertIsNone(core["derived_kinematics"]["galactocentric_x"])
            self.assertIsNotNone(artifact["fields"])

    def test_tex_only_mode_uses_tex_profile_and_no_ecsv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            prepared = json.loads(
                (
                    workspace
                    / "benchmark/campaigns/hvs-extraction-v5/runs"
                    / RUN_ID
                    / "prepared_inputs"
                    / f"{ARXIV_ID}.json"
                ).read_text(encoding="utf-8")
            )
            view_est = estimate_tokens(prepared["manuscript"]["view"])
            # Rebuild with a field budget that fits the manuscript but not the
            # manuscript plus ECSV tables: input_budget = limit - 23000.
            workspace2 = Path(tmp) / "second"
            shutil.copytree(workspace, workspace2, dirs_exist_ok=True)
            artifact = build_prepared_input(
                workspace2,
                ARXIV_ID,
                roster_budget=budget(),
                field_budget=budget(view_est + 23000 + 30),
            )
            self.assertEqual(
                artifact["context"]["field_context_mode"],
                "tex_only_due_to_context_budget",
            )
            write_prepared_input(workspace2, RUN_ID, artifact)
            transport = RecordingTransport(lambda kwargs: fake_response(valid_submission()))
            summary = run_field_stage(
                workspace2,
                RUN_ID,
                ARXIV_ID,
                config=frozen_config(),
                transport=transport,
                sleep=lambda _: None,
            )
            self.assertEqual(summary["candidates"]["candidate-001"], FIELDS_COMPLETE)
            artifact = candidate_artifact(workspace2, "candidate-001")
            self.assertEqual(
                artifact["provenance"]["rule_profile"], "hvs_candidate_core_fields_tex"
            )
            for call in transport.calls:
                user = call["messages"][1]["content"]
                self.assertNotIn("CONVERTED TABLES", user)
                self.assertNotIn("ecsv", call["messages"][0]["content"])

    def test_field_input_too_large_fails_every_candidate_without_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp, field_limit=10)
            transport = RecordingTransport(lambda kwargs: fake_response(ecsv_submission()))
            summary = run_field_stage(
                workspace,
                RUN_ID,
                ARXIV_ID,
                config=frozen_config(),
                transport=transport,
                sleep=lambda _: None,
            )
            self.assertEqual(
                set(summary["candidates"].values()), {FIELD_EXTRACTION_FAILED}
            )
            self.assertEqual(transport.calls, [])
            failed = candidate_artifact(workspace, "candidate-001")
            self.assertEqual(failed["failure"]["code"], "field_input_too_large")

    def test_no_trusted_roster_skips_field_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            roster_path = (
                workspace
                / "benchmark/campaigns/hvs-extraction-v5/runs"
                / RUN_ID
                / "papers"
                / ARXIV_ID
                / "roster_final.json"
            )
            roster = json.loads(roster_path.read_text(encoding="utf-8"))
            roster["status"] = "roster_failed"
            roster_path.write_text(json.dumps(roster), encoding="utf-8")
            transport = RecordingTransport(lambda kwargs: fake_response(ecsv_submission()))
            summary = run_field_stage(
                workspace,
                RUN_ID,
                ARXIV_ID,
                config=frozen_config(),
                transport=transport,
                sleep=lambda _: None,
            )
            self.assertEqual(summary["status"], NO_TRUSTED_ROSTER)
            self.assertEqual(transport.calls, [])


if __name__ == "__main__":
    unittest.main()
