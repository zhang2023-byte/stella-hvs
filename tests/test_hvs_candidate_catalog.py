from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
SCRIPT = ROOT / "scripts" / "merge_hvs_candidate_catalog.py"
SPEC = importlib.util.spec_from_file_location("merge_hvs_candidate_catalog", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
merge_cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(merge_cli)

from high_velocity_lit.hvs_candidate_catalog import (  # noqa: E402
    INDEX_JSON_FILENAME,
    INDEX_MARKDOWN_FILENAME,
    OBJECT_SCHEMA_VERSION,
    rebuild_hvs_candidate_catalog,
    render_hvs_candidate_catalog_index,
    update_hvs_candidate_catalog,
    write_rebuilt_hvs_candidate_catalog,
    write_updated_hvs_candidate_catalog,
)
from high_velocity_lit.schema_specs import LITERATURE_HVS_CANDIDATES_SCHEMA_VERSION  # noqa: E402


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def quantity(value: str, *, unit: str = "km s^-1", method_ref: str = "step-02") -> dict[str, object]:
    return {
        "raw_value": value,
        "value": value,
        "unit": unit,
        "source_refs": [],
        "method_refs": [method_ref],
    }


def coordinate(value: str, *, unit: str = "deg", method_ref: str = "step-01") -> dict[str, object]:
    return {
        "raw_value": value,
        "value": value,
        "unit": unit,
        "source_refs": [],
        "method_refs": [method_ref],
        "coordinate_format": "decimal_degrees",
        "reference_frame": {
            "value": "ICRS",
            "raw_value": "ICRS",
            "source_refs": [],
        },
        "epoch": {
            "value": "J2016.0",
            "epoch_kind": "reference_epoch",
            "raw_value": "J2016.0",
            "source_refs": [],
        },
    }


def candidate(
    arxiv_id: str,
    index: int,
    *,
    paper_candidate_id: str,
    gaia_source_id: str = "",
    ra: str = "",
    dec: str = "",
) -> dict[str, object]:
    observed: dict[str, object] = {}
    if ra and dec:
        observed["ra"] = coordinate(ra, unit="deg")
        observed["dec"] = coordinate(dec, unit="deg")
    return {
        "identifiers": {
            "record_id": f"{arxiv_id}:cand-{index:03d}",
            "paper_candidate_id": paper_candidate_id,
            "gaia_source_id": gaia_source_id,
            "all": [{"value": paper_candidate_id, "source_refs": []}],
        },
        "inclusion_assessment": {
            "summary": "Fixture candidate.",
            "paper_labels": ["hvs_candidate", "unbound_star"],
            "galactic_bound_claim": "unbound",
            "inclusion_basis": "explicit_unbound_text",
            "extraction_confidence": "high",
            "confidence_reason": "Fixture extraction has direct candidate evidence.",
            "source_refs": [],
        },
        "candidate_origin": {
            "origin_type": "introduced_by_this_paper",
            "paper_reassesses_unbound_status": True,
            "source_refs": [],
        },
        "core": {
            "observed_phase_space": observed,
            "derived_kinematics": {"total_velocity": quantity("700")},
            "bound_assessment": {"unbound_probability": quantity("0.8", unit="", method_ref="step-03")},
        },
        "photometry": [],
        "spectroscopy": [],
        "stellar_parameters": {"other": []},
        "abundances": [],
        "quality_flags": [],
        "orbit": {"other": []},
        "astrophysical_origin": {"hypothesis_metrics": [], "other": []},
        "extra": [],
    }


def payload(arxiv_id: str, *, month: str, candidates: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": LITERATURE_HVS_CANDIDATES_SCHEMA_VERSION,
        "generated_at": "2026-05-19T12:00:00",
        "paper": {
            "arxiv_id": arxiv_id,
            "bibcode": f"2026TEST.{arxiv_id}",
            "title": f"Paper {arxiv_id}",
            "month": month,
            "source_note_json": f"notes/{month[:4]}/{month}/{month}.json",
            "links": {"abs": f"https://arxiv.org/abs/{arxiv_id}", "pdf": f"https://arxiv.org/pdf/{arxiv_id}"},
        },
        "inputs": {
            "paper_dir": f"literature/{arxiv_id}",
            "audit_path": f"literature/{arxiv_id}/audit.json",
            "catalog_review_path": f"literature/{arxiv_id}/catalog_review.json",
            "catalog_extraction_path": f"literature/{arxiv_id}/catalog_extraction.json",
            "ecsv_paths": [],
        },
        "extraction": {
            "status": "candidates_found" if candidates else "no_candidates",
            "extracted_at": "2026-05-19T12:00:00",
            "extractor": "agent",
            "summary": "Fixture extraction.",
        },
        "method_chain": [
            {
                "id": "step-01",
                "depends_on": [],
                "step_type": "input_catalog",
                "summary": "Gaia input catalog.",
                "source_refs": [{"kind": "text", "path": "paper.tex", "start_line": 1, "end_line": 1, "context": "x"}],
            },
            {
                "id": "step-02",
                "depends_on": ["step-01"],
                "step_type": "velocity_calculation",
                "summary": "Velocity calculation.",
                "source_refs": [{"kind": "text", "path": "paper.tex", "start_line": 2, "end_line": 2, "context": "x"}],
            },
            {
                "id": "step-03",
                "depends_on": ["step-02"],
                "step_type": "escape_or_bound_assessment",
                "summary": "Unbound probability.",
                "source_refs": [{"kind": "text", "path": "paper.tex", "start_line": 3, "end_line": 3, "context": "x"}],
            },
        ],
        "candidates": candidates,
        "candidate_groups_considered": [],
    }


class HvsCandidateCatalogTest(unittest.TestCase):
    def test_rebuild_merges_same_gaia_and_strips_source_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature = workspace / "literature"
            catalog = workspace / "catalog"
            write_json(
                literature / "2601.00001" / "literature_hvs_candidates.json",
                payload(
                    "2601.00001",
                    month="2026-01",
                    candidates=[
                        candidate(
                            "2601.00001",
                            1,
                            paper_candidate_id="HVS-A",
                            gaia_source_id="Gaia DR3 123",
                            ra="10.0",
                            dec="20.0",
                        )
                    ],
                ),
            )
            write_json(
                literature / "2602.00002" / "literature_hvs_candidates.json",
                payload(
                    "2602.00002",
                    month="2026-02",
                    candidates=[
                        candidate(
                            "2602.00002",
                            1,
                            paper_candidate_id="HVS-B",
                            gaia_source_id="Gaia DR3 123",
                            ra="10.0",
                            dec="20.0",
                        )
                    ],
                ),
            )

            result = write_rebuilt_hvs_candidate_catalog(literature, catalog, workspace=workspace)

            self.assertEqual(result["index_record"]["summary"]["object_count"], 1)
            record = result["object_records"][0]
            self.assertEqual(record["object_id"], "Gaia_DR3_123")
            self.assertEqual(len(record["sources"]), 2)
            self.assertNotIn("source_refs", json.dumps(record))
            first_quantity = record["candidates"][0]["core"]["derived_kinematics"]["total_velocity"]
            self.assertEqual(first_quantity, {"value": "700", "unit": "km s^-1", "method_refs": ["step-02"]})
            self.assertTrue((catalog / "Gaia_DR3_123.json").exists())
            self.assertTrue((catalog / INDEX_JSON_FILENAME).exists())
            self.assertTrue((catalog / INDEX_MARKDOWN_FILENAME).exists())

    def test_rebuild_merges_edr3_and_dr3_with_same_source_number(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature = workspace / "literature"
            catalog = workspace / "catalog"
            write_json(
                literature / "2206.00417" / "literature_hvs_candidates.json",
                payload(
                    "2206.00417",
                    month="2022-06",
                    candidates=[
                        candidate(
                            "2206.00417",
                            3,
                            paper_candidate_id="HV-RRL-03",
                            gaia_source_id="Gaia EDR3 2644870582050682240",
                            ra="349.9803",
                            dec="-0.1865",
                        )
                    ],
                ),
            )
            write_json(
                literature / "2509.24010" / "literature_hvs_candidates.json",
                payload(
                    "2509.24010",
                    month="2025-09",
                    candidates=[
                        candidate(
                            "2509.24010",
                            164,
                            paper_candidate_id="HV-RRL-164",
                            gaia_source_id="Gaia DR3 2644870582050682240",
                            ra="349.9803",
                            dec="-0.1865",
                        )
                    ],
                ),
            )

            result = rebuild_hvs_candidate_catalog(literature, catalog, workspace=workspace)

            self.assertEqual(result["index_record"]["summary"]["object_count"], 1)
            record = result["object_records"][0]
            self.assertEqual(record["object_id"], "Gaia_DR3_2644870582050682240")
            self.assertEqual(record["canonical_identifier"]["value"], "Gaia DR3 2644870582050682240")
            self.assertEqual({source["gaia_source_id"] for source in record["sources"]}, {
                "Gaia EDR3 2644870582050682240",
                "Gaia DR3 2644870582050682240",
            })
            self.assertFalse(result["index_record"]["warnings"])

    def test_rebuild_keeps_dr2_and_dr3_with_same_source_number_split(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature = workspace / "literature"
            catalog = workspace / "catalog"
            for arxiv_id, gaia_id in (
                ("2601.00001", "Gaia DR2 777"),
                ("2602.00002", "Gaia DR3 777"),
            ):
                write_json(
                    literature / arxiv_id / "literature_hvs_candidates.json",
                    payload(
                        arxiv_id,
                        month="2026-01",
                        candidates=[
                            candidate(arxiv_id, 1, paper_candidate_id=f"HVS-{arxiv_id}", gaia_source_id=gaia_id, ra="10", dec="20")
                        ],
                    ),
                )

            result = rebuild_hvs_candidate_catalog(literature, catalog, workspace=workspace)

            object_ids = {record["object_id"] for record in result["object_records"]}
            warning_types = {warning["type"] for warning in result["index_record"]["warnings"]}
            self.assertEqual(result["index_record"]["summary"]["object_count"], 2)
            self.assertEqual(object_ids, {"Gaia_DR2_777", "Gaia_DR3_777"})
            self.assertIn("different_gaia_near_coordinates", warning_types)

    def test_rebuild_merges_by_coordinates_when_gaia_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature = workspace / "literature"
            catalog = workspace / "catalog"
            write_json(
                literature / "2601.00001" / "literature_hvs_candidates.json",
                payload(
                    "2601.00001",
                    month="2026-01",
                    candidates=[candidate("2601.00001", 1, paper_candidate_id="HVS-A", ra="10.0", dec="20.0")],
                ),
            )
            write_json(
                literature / "2602.00002" / "literature_hvs_candidates.json",
                payload(
                    "2602.00002",
                    month="2026-02",
                    candidates=[
                        candidate(
                            "2602.00002",
                            1,
                            paper_candidate_id="HVS-B",
                            gaia_source_id="Gaia DR3 999",
                            ra="10.0001",
                            dec="20.0001",
                        )
                    ],
                ),
            )

            result = rebuild_hvs_candidate_catalog(literature, catalog, workspace=workspace)

            self.assertEqual(result["index_record"]["summary"]["object_count"], 1)
            self.assertEqual(result["object_records"][0]["merge"]["match_strategy"], "coordinates")
            self.assertEqual(result["object_records"][0]["object_id"], "Gaia_DR3_999")

    def test_different_gaia_near_coordinates_warns_without_merging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature = workspace / "literature"
            catalog = workspace / "catalog"
            for arxiv_id, gaia_id in (("2601.00001", "Gaia DR3 111"), ("2602.00002", "Gaia DR3 222")):
                write_json(
                    literature / arxiv_id / "literature_hvs_candidates.json",
                    payload(
                        arxiv_id,
                        month="2026-01",
                        candidates=[
                            candidate(arxiv_id, 1, paper_candidate_id=f"HVS-{gaia_id[-3:]}", gaia_source_id=gaia_id, ra="10", dec="20")
                        ],
                    ),
                )

            result = rebuild_hvs_candidate_catalog(literature, catalog, workspace=workspace)

            self.assertEqual(result["index_record"]["summary"]["object_count"], 2)
            warning_types = {warning["type"] for warning in result["index_record"]["warnings"]}
            self.assertIn("different_gaia_near_coordinates", warning_types)

    def test_same_gaia_far_coordinates_warns_and_merges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature = workspace / "literature"
            catalog = workspace / "catalog"
            write_json(
                literature / "2601.00001" / "literature_hvs_candidates.json",
                payload(
                    "2601.00001",
                    month="2026-01",
                    candidates=[
                        candidate("2601.00001", 1, paper_candidate_id="A", gaia_source_id="Gaia DR3 333", ra="10", dec="20")
                    ],
                ),
            )
            write_json(
                literature / "2602.00002" / "literature_hvs_candidates.json",
                payload(
                    "2602.00002",
                    month="2026-02",
                    candidates=[
                        candidate("2602.00002", 1, paper_candidate_id="B", gaia_source_id="Gaia DR3 333", ra="40", dec="20")
                    ],
                ),
            )

            result = rebuild_hvs_candidate_catalog(literature, catalog, workspace=workspace)

            self.assertEqual(result["index_record"]["summary"]["object_count"], 1)
            self.assertEqual(result["index_record"]["warnings"][0]["type"], "same_gaia_far_coordinates")

    def test_update_adds_new_source_to_existing_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature = workspace / "literature"
            catalog = workspace / "catalog"
            first_path = literature / "2601.00001" / "literature_hvs_candidates.json"
            second_path = literature / "2602.00002" / "literature_hvs_candidates.json"
            write_json(
                first_path,
                payload(
                    "2601.00001",
                    month="2026-01",
                    candidates=[
                        candidate("2601.00001", 1, paper_candidate_id="A", gaia_source_id="Gaia DR3 444", ra="10", dec="20")
                    ],
                ),
            )
            write_rebuilt_hvs_candidate_catalog(literature, catalog, workspace=workspace)
            write_json(
                second_path,
                payload(
                    "2602.00002",
                    month="2026-02",
                    candidates=[
                        candidate("2602.00002", 1, paper_candidate_id="B", gaia_source_id="Gaia DR3 444", ra="10", dec="20")
                    ],
                ),
            )

            result = write_updated_hvs_candidate_catalog(second_path, catalog, literature_dir=literature, workspace=workspace)

            self.assertEqual(result["new_candidate_count"], 1)
            self.assertEqual(result["index_record"]["summary"]["object_count"], 1)
            self.assertEqual(result["object_records"][0]["sources"][1]["source"], "src-002")

    def test_update_reads_v1_catalog_and_removes_stale_object_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature = workspace / "literature"
            catalog = workspace / "catalog"
            catalog.mkdir()
            old_record = {
                "schema_version": "stella.hvs_candidate_catalog.object.v1",
                "generated_at": "2026-05-19T12:00:00",
                "object_id": "Gaia_EDR3_123",
                "canonical_identifier": {"kind": "gaia_source_id", "value": "Gaia EDR3 123", "source": "src-001"},
                "sources": [
                    {
                        "source": "src-001",
                        "paper": {
                            "arxiv_id": "2601.00001",
                            "bibcode": "2026TEST.2601.00001",
                            "title": "Paper 2601.00001",
                            "month": "2026-01",
                            "source_note_json": "notes/2026/2026-01/2026-01.json",
                            "links": {"abs": "https://arxiv.org/abs/2601.00001"},
                        },
                        "source_json_path": "literature/2601.00001/literature_hvs_candidates.json",
                        "record_id": "2601.00001:cand-001",
                        "paper_candidate_id": "A",
                        "gaia_source_id": "Gaia EDR3 123",
                    }
                ],
                "method_chain": [{"source": "src-001", "steps": []}],
                "candidates": [
                    {
                        "source": "src-001",
                        "identifiers": {
                            "record_id": "2601.00001:cand-001",
                            "paper_candidate_id": "A",
                            "gaia_source_id": "Gaia EDR3 123",
                        },
                        "core": {
                            "observed_phase_space": {
                                "ra": {"value": "10", "unit": "deg", "method_refs": []},
                                "dec": {"value": "20", "unit": "deg", "method_refs": []},
                            },
                            "derived_kinematics": {},
                            "bound_assessment": {},
                        },
                    }
                ],
                "merge": {"match_strategy": "singleton", "warnings": []},
            }
            write_json(catalog / "Gaia_EDR3_123.json", old_record)
            new_path = literature / "2602.00002" / "literature_hvs_candidates.json"
            write_json(
                new_path,
                payload(
                    "2602.00002",
                    month="2026-02",
                    candidates=[
                        candidate("2602.00002", 1, paper_candidate_id="B", gaia_source_id="Gaia DR3 123", ra="10", dec="20")
                    ],
                ),
            )

            result = write_updated_hvs_candidate_catalog(new_path, catalog, literature_dir=literature, workspace=workspace)

            self.assertEqual(result["index_record"]["summary"]["object_count"], 1)
            self.assertEqual(result["object_records"][0]["schema_version"], OBJECT_SCHEMA_VERSION)
            self.assertEqual(result["object_records"][0]["object_id"], "Gaia_DR3_123")
            self.assertEqual(len(result["object_records"][0]["sources"]), 2)
            self.assertFalse((catalog / "Gaia_EDR3_123.json").exists())
            self.assertTrue((catalog / "Gaia_DR3_123.json").exists())

    def test_strong_slug_collision_suffixes_all_colliding_objects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature = workspace / "literature"
            catalog = workspace / "catalog"
            for arxiv_id, ra in (("2601.00001", "10"), ("2602.00002", "40")):
                write_json(
                    literature / arxiv_id / "literature_hvs_candidates.json",
                    payload(
                        arxiv_id,
                        month="2026-01",
                        candidates=[candidate(arxiv_id, 1, paper_candidate_id="HVS1", ra=ra, dec="20")],
                    ),
                )

            result = rebuild_hvs_candidate_catalog(literature, catalog, workspace=workspace)

            object_ids = [record["object_id"] for record in result["object_records"]]
            self.assertIn("HVS1__2601_00001_cand-001", object_ids)
            self.assertIn("HVS1__2602_00002_cand-001", object_ids)

    def test_strong_paper_id_slug_preserves_ascii_plus_and_minus(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature = workspace / "literature"
            catalog = workspace / "catalog"
            for index, paper_candidate_id in enumerate(("J0546+0836", "LAMOST-HVS7"), start=1):
                write_json(
                    literature / f"260{index}.0000{index}" / "literature_hvs_candidates.json",
                    payload(
                        f"260{index}.0000{index}",
                        month="2026-01",
                        candidates=[candidate(f"260{index}.0000{index}", 1, paper_candidate_id=paper_candidate_id)],
                    ),
                )

            result = rebuild_hvs_candidate_catalog(literature, catalog, workspace=workspace)

            object_ids = {record["object_id"] for record in result["object_records"]}
            self.assertEqual(object_ids, {"J0546+0836", "LAMOST-HVS7"})

    def test_numeric_paper_id_uses_coordinate_slug(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature = workspace / "literature"
            catalog = workspace / "catalog"
            write_json(
                literature / "2601.00001" / "literature_hvs_candidates.json",
                payload(
                    "2601.00001",
                    month="2026-01",
                    candidates=[
                        candidate(
                            "2601.00001",
                            1,
                            paper_candidate_id="1",
                            ra="267.9756666667",
                            dec="-28.027425",
                        )
                    ],
                ),
            )

            result = rebuild_hvs_candidate_catalog(literature, catalog, workspace=workspace)

            record = result["object_records"][0]
            self.assertEqual(record["object_id"], "J17515416-2801387")
            self.assertEqual(record["canonical_identifier"]["kind"], "coordinate")
            self.assertFalse((catalog / "1.json").exists())

    def test_weak_paper_id_without_coordinate_uses_record_id_slug(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature = workspace / "literature"
            catalog = workspace / "catalog"
            for arxiv_id in ("2601.00001", "2602.00002"):
                write_json(
                    literature / arxiv_id / "literature_hvs_candidates.json",
                    payload(
                        arxiv_id,
                        month="2026-01",
                        candidates=[candidate(arxiv_id, 1, paper_candidate_id="1")],
                    ),
                )

            result = rebuild_hvs_candidate_catalog(literature, catalog, workspace=workspace)

            object_ids = {record["object_id"] for record in result["object_records"]}
            self.assertEqual(object_ids, {"src_2601_00001_cand-001", "src_2602_00002_cand-001"})

    def test_dry_run_does_not_write_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature = workspace / "literature"
            catalog = workspace / "catalog"
            write_json(
                literature / "2601.00001" / "literature_hvs_candidates.json",
                payload(
                    "2601.00001",
                    month="2026-01",
                    candidates=[
                        candidate("2601.00001", 1, paper_candidate_id="A", gaia_source_id="Gaia DR3 555", ra="10", dec="20")
                    ],
                ),
            )

            result = write_rebuilt_hvs_candidate_catalog(literature, catalog, workspace=workspace, dry_run=True)

            self.assertTrue(result["planned_write_paths"])
            self.assertFalse(catalog.exists())

    def test_invalid_input_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature = workspace / "literature"
            catalog = workspace / "catalog"
            write_json(literature / "2601.00001" / "literature_hvs_candidates.json", {"candidates": []})

            result = rebuild_hvs_candidate_catalog(literature, catalog, workspace=workspace)

            self.assertEqual(result["index_record"]["summary"]["object_count"], 0)
            self.assertEqual(result["index_record"]["summary"]["skipped_count"], 1)
            self.assertIn("literature/2601.00001/literature_hvs_candidates.json", result["skipped"][0]["path"])

    def test_cli_fail_on_skipped_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature = workspace / "literature"
            catalog = workspace / "catalog"
            write_json(literature / "2601.00001" / "literature_hvs_candidates.json", {"candidates": []})

            with patch.object(
                sys,
                "argv",
                [
                    "merge_hvs_candidate_catalog.py",
                    "rebuild",
                    "--literature-dir",
                    str(literature),
                    "--catalog-dir",
                    str(catalog),
                    "--fail-on-skipped",
                ],
            ):
                with patch("sys.stderr", new_callable=io.StringIO) as stderr:
                    with patch("sys.stdout", new_callable=io.StringIO):
                        exit_code = merge_cli.main()

            self.assertEqual(exit_code, 1)
            self.assertIn("Skipped malformed HVS catalog inputs", stderr.getvalue())

    def test_markdown_renders_objects_and_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature = workspace / "literature"
            catalog = workspace / "catalog"
            write_json(
                literature / "2601.00001" / "literature_hvs_candidates.json",
                payload(
                    "2601.00001",
                    month="2026-01",
                    candidates=[
                        candidate("2601.00001", 1, paper_candidate_id="A", gaia_source_id="Gaia DR3 666", ra="10", dec="20")
                    ],
                ),
            )

            result = rebuild_hvs_candidate_catalog(literature, catalog, workspace=workspace)
            markdown = render_hvs_candidate_catalog_index(result["index_record"])

            self.assertIn("HVS Candidate Object Catalog", markdown)
            self.assertIn("Gaia_DR3_666", markdown)
            self.assertIn("Objects", markdown)


if __name__ == "__main__":
    unittest.main()
