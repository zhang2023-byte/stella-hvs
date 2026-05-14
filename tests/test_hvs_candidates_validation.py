from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_hvs_candidates.py"
SPEC = importlib.util.spec_from_file_location("validate_hvs_candidates", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
validate_cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate_cli)
sys.path.insert(0, str(ROOT / "src"))

from high_velocity_lit.schema_specs import LITERATURE_HVS_CANDIDATES_SCHEMA_VERSION  # noqa: E402


def write_json_file(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_ecsv(path: Path) -> int:
    text = "\n".join(
        [
            "# %ECSV 1.0",
            "# ---",
            "# datatype:",
            "# - {name: col_001, datatype: string, description: Name}",
            "# - {name: col_002, datatype: string, description: 'vtan_g | [km/s]'}",
            "# schema: astropy-2.0",
            "col_001 col_002",
            "HVS1 701",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")
    return text.splitlines().index("HVS1 701") + 1


def write_source(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                r"\section{Selection}",
                "We identify HVS1 for the first time as an unbound hypervelocity-star candidate.",
                "The sample is selected from Gaia DR3 and filtered by quality cuts.",
                r"HVS2 was reported as an unbound star by \citet{Smith2020}, and we reassess it here.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def write_bib(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "@ARTICLE{Smith2020,",
                "  author = {Smith, A. and Doe, B.},",
                "  title = {An earlier unbound star candidate},",
                "  year = {2020}",
                "}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def valid_payload(workspace: Path, *, status: str = "candidates_found") -> dict[str, object]:
    paper_dir = workspace / "literature" / "2603.00001"
    ecsv_line = write_ecsv(paper_dir / "catalog_tables" / "table-hvs.ecsv")
    write_source(paper_dir / "arxiv_source" / "main.tex")
    write_bib(paper_dir / "arxiv_source" / "refs.bib")
    write_json_file(paper_dir / "catalog_review.json", {"paper": {"arxiv_id": "2603.00001"}})
    write_json_file(paper_dir / "catalog_extraction.json", {"paper": {"arxiv_id": "2603.00001"}})

    text_ref = {
        "kind": "text",
        "path": "literature/2603.00001/arxiv_source/main.tex",
        "start_line": 2,
        "end_line": 2,
        "context": "paper explicitly identifies HVS1 as an unbound candidate",
    }
    cell_ref = {
        "kind": "ecsv_cell",
        "path": "literature/2603.00001/catalog_tables/table-hvs.ecsv",
        "line": ecsv_line,
        "column": "col_002",
        "column_header": "vtan_g | [km/s]",
        "raw_value": "701",
    }
    candidates: list[dict[str, object]] = []
    if status != "no_candidates":
        candidates.append(
            {
                "candidate_id": "2603.00001:candidate-001",
                "identifiers": {
                    "primary": "HVS1",
                    "aliases": [{"value": "HVS1", "source_refs": [text_ref]}],
                },
                "candidate_assessment": {
                    "summary": "The paper explicitly identifies HVS1 as an unbound HVS candidate.",
                    "candidate_status": "unbound_candidate",
                    "confidence": "high",
                    "source_refs": [text_ref],
                },
                "candidate_origin": {
                    "origin_type": "introduced_by_this_paper",
                    "paper_reassesses_unbound_status": True,
                    "source_refs": [text_ref],
                },
                "method_chain_refs": ["method-1"],
                "core": {
                    "observed_phase_space": {},
                    "derived_kinematics": {
                        "galactocentric_tangential_velocity": {
                            "raw_value": "701",
                            "value": "701",
                            "unit": "km/s",
                            "kind": "vtan_g",
                            "source_refs": [cell_ref],
                        }
                    },
                    "probabilities": {},
                },
                "extra": [
                    {
                        "name": "selection_note",
                        "raw_value": "quality-filtered Gaia DR3 candidate",
                        "value": "quality-filtered Gaia DR3 candidate",
                        "source_refs": [text_ref],
                    }
                ],
            }
        )

    return {
        "schema_version": LITERATURE_HVS_CANDIDATES_SCHEMA_VERSION,
        "generated_at": "2026-05-12T12:00:00",
        "paper": {"arxiv_id": "2603.00001", "bibcode": "2026MNRAS.123..456H", "title": "HVS candidates", "month": "2026-03"},
        "inputs": {
            "catalog_review_path": "literature/2603.00001/catalog_review.json",
            "catalog_extraction_path": "literature/2603.00001/catalog_extraction.json",
        },
        "extraction": {"status": status, "extractor": "agent"},
        "method_chain": [
            {
                "id": "method-1",
                "step_type": "selection",
                "summary": "Gaia DR3 candidates are filtered by quality cuts.",
                "source_refs": [text_ref],
            }
        ],
        "candidates": candidates,
        "candidate_groups_considered": [
            {
                "group_id": "main-candidates",
                "decision": "included",
                "source_refs": [text_ref],
            }
        ],
    }


def cited_payload(workspace: Path) -> dict[str, object]:
    payload = valid_payload(workspace)
    candidate = payload["candidates"][0]  # type: ignore[index]
    candidate["candidate_id"] = "2603.00001:candidate-002"
    candidate["identifiers"]["primary"] = "HVS2"  # type: ignore[index]
    candidate["candidate_assessment"]["summary"] = "The paper reassesses HVS2, previously reported as unbound."  # type: ignore[index]
    candidate["candidate_assessment"]["source_refs"] = [  # type: ignore[index]
        {
            "kind": "text",
            "path": "literature/2603.00001/arxiv_source/main.tex",
            "start_line": 4,
            "end_line": 4,
            "context": "paper cites earlier unbound candidate literature",
        }
    ]
    candidate["candidate_origin"] = {  # type: ignore[index]
        "origin_type": "cited_from_literature",
        "paper_reassesses_unbound_status": True,
        "source_refs": [
            {
                "kind": "text",
                "path": "literature/2603.00001/arxiv_source/main.tex",
                "start_line": 4,
                "end_line": 4,
                "context": "paper states the candidate was previously reported",
            }
        ],
        "citation": {
            "bibkey": "Smith2020",
            "title": "An earlier unbound star candidate",
            "year": "2020",
            "authors": ["Smith, A.", "Doe, B."],
            "source_refs": [
                {
                    "kind": "text",
                    "path": "literature/2603.00001/arxiv_source/main.tex",
                    "start_line": 4,
                    "end_line": 4,
                    "context": "paper cite command",
                },
                {
                    "kind": "text",
                    "path": "literature/2603.00001/arxiv_source/refs.bib",
                    "start_line": 1,
                    "end_line": 5,
                    "context": "Smith2020 bibliography entry",
                },
            ],
        },
    }
    candidate["method_chain_refs"] = []  # type: ignore[index]
    return payload


class HvsCandidatesValidationTest(unittest.TestCase):
    def test_valid_candidate_payload_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            errors = validate_cli.validate_hvs_candidates(valid_payload(workspace), workspace=workspace)

            self.assertEqual(errors, [])

    def test_valid_cited_candidate_payload_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            errors = validate_cli.validate_hvs_candidates(cited_payload(workspace), workspace=workspace)

            self.assertEqual(errors, [])

    def test_no_candidates_payload_passes_with_empty_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            errors = validate_cli.validate_hvs_candidates(
                valid_payload(workspace, status="no_candidates"),
                workspace=workspace,
            )

            self.assertEqual(errors, [])

    def test_missing_core_provenance_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            payload = valid_payload(workspace)
            candidate = payload["candidates"][0]  # type: ignore[index]
            velocity = candidate["core"]["derived_kinematics"]["galactocentric_tangential_velocity"]  # type: ignore[index]
            del velocity["source_refs"]

            errors = validate_cli.validate_hvs_candidates(payload, workspace=workspace)

            self.assertTrue(any("must include source_refs" in error for error in errors))

    def test_missing_quantity_raw_value_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            payload = valid_payload(workspace)
            candidate = payload["candidates"][0]  # type: ignore[index]
            velocity = candidate["core"]["derived_kinematics"]["galactocentric_tangential_velocity"]  # type: ignore[index]
            del velocity["raw_value"]

            errors = validate_cli.validate_hvs_candidates(payload, workspace=workspace)

            self.assertTrue(any("must include raw_value" in error for error in errors))

    def test_bad_ecsv_header_line_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            payload = valid_payload(workspace)
            candidate = payload["candidates"][0]  # type: ignore[index]
            velocity = candidate["core"]["derived_kinematics"]["galactocentric_tangential_velocity"]  # type: ignore[index]
            ref = velocity["source_refs"][0]
            ref["line"] = 7

            errors = validate_cli.validate_hvs_candidates(payload, workspace=workspace)

            self.assertTrue(any("header row" in error for error in errors))

    def test_bad_ecsv_raw_value_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            payload = valid_payload(workspace)
            candidate = payload["candidates"][0]  # type: ignore[index]
            velocity = candidate["core"]["derived_kinematics"]["galactocentric_tangential_velocity"]  # type: ignore[index]
            ref = velocity["source_refs"][0]
            ref["raw_value"] = "702"

            errors = validate_cli.validate_hvs_candidates(payload, workspace=workspace)

            self.assertTrue(any("does not match ECSV cell" in error for error in errors))

    def test_quantity_raw_value_must_match_ecsv_ref_raw_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            payload = valid_payload(workspace)
            candidate = payload["candidates"][0]  # type: ignore[index]
            velocity = candidate["core"]["derived_kinematics"]["galactocentric_tangential_velocity"]  # type: ignore[index]
            velocity["raw_value"] = "702"

            errors = validate_cli.validate_hvs_candidates(payload, workspace=workspace)

            self.assertTrue(any("must match the quantity record raw_value" in error for error in errors))

    def test_latex_residue_in_value_fails_but_raw_value_may_keep_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            payload = valid_payload(workspace)
            candidate = payload["candidates"][0]  # type: ignore[index]
            velocity = candidate["core"]["derived_kinematics"]["galactocentric_tangential_velocity"]  # type: ignore[index]
            text_ref = candidate["candidate_assessment"]["source_refs"][0]  # type: ignore[index]
            velocity["source_refs"] = [text_ref]
            velocity["raw_value"] = "701^{+2}_{-1}"
            velocity["value"] = "701"
            velocity["lower_error"] = "1"
            velocity["upper_error"] = "2"

            errors = validate_cli.validate_hvs_candidates(payload, workspace=workspace)
            self.assertEqual(errors, [])

            velocity["value"] = "701^{+2}_{-1}"
            errors = validate_cli.validate_hvs_candidates(payload, workspace=workspace)

            self.assertTrue(any("contains LaTeX residue" in error for error in errors))

    def test_runaway_candidate_status_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            payload = valid_payload(workspace)
            candidate = payload["candidates"][0]  # type: ignore[index]
            candidate["candidate_assessment"]["candidate_status"] = "runaway_candidate"  # type: ignore[index]

            errors = validate_cli.validate_hvs_candidates(payload, workspace=workspace)

            self.assertTrue(any("candidate_status" in error for error in errors))

    def test_candidate_assessment_requires_paper_text_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            payload = valid_payload(workspace)
            candidate = payload["candidates"][0]  # type: ignore[index]
            velocity = candidate["core"]["derived_kinematics"]["galactocentric_tangential_velocity"]  # type: ignore[index]
            candidate["candidate_assessment"]["source_refs"] = velocity["source_refs"]  # type: ignore[index]

            errors = validate_cli.validate_hvs_candidates(payload, workspace=workspace)

            self.assertTrue(any("Galactic-unbound candidate evidence" in error for error in errors))

    def test_cited_candidate_requires_citation_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            payload = cited_payload(workspace)
            candidate = payload["candidates"][0]  # type: ignore[index]
            del candidate["candidate_origin"]["citation"]  # type: ignore[index]

            errors = validate_cli.validate_hvs_candidates(payload, workspace=workspace)

            self.assertTrue(any("candidate_origin.citation" in error for error in errors))

    def test_introduced_candidate_requires_method_chain_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            payload = valid_payload(workspace)
            candidate = payload["candidates"][0]  # type: ignore[index]
            candidate["method_chain_refs"] = []

            errors = validate_cli.validate_hvs_candidates(payload, workspace=workspace)

            self.assertTrue(any("must reference at least one method_chain" in error for error in errors))

    def test_missing_bibcode_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            payload = valid_payload(workspace)
            del payload["paper"]["bibcode"]  # type: ignore[index]
            errors = validate_cli.validate_hvs_candidates(payload, workspace=workspace)
            self.assertEqual(errors, [])

    def test_empty_bibcode_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            payload = valid_payload(workspace)
            payload["paper"]["bibcode"] = ""  # type: ignore[index]
            errors = validate_cli.validate_hvs_candidates(payload, workspace=workspace)
            self.assertTrue(any("$.paper.bibcode" in error for error in errors))

    def test_cli_reports_valid_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            path = workspace / "literature" / "2603.00001" / "literature_hvs_candidates.json"
            write_json_file(path, valid_payload(workspace))

            with patch.object(
                sys,
                "argv",
                [
                    "validate_hvs_candidates.py",
                    "--path",
                    str(path),
                    "--workspace",
                    str(workspace),
                ],
            ):
                with patch("builtins.print") as fake_print:
                    exit_code = validate_cli.main()

            self.assertEqual(exit_code, 0)
            self.assertIn("OK:", fake_print.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
