"""Explicit dynamics input-selection tests (synthetic fixtures only)."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from tests.test_hvs_contribution_scoring import ai_contribution, ai_document, ai_value
from stella.dyn.dynamics import (
    calculate_contribution_catalog_dynamics,
    contribution_dynamics_adapter_record,
)
from stella.dyn.input_selection import (
    InputSelectionError,
    build_input_selection,
    selected_value_fingerprint,
    selection_for_object,
    validate_input_selection,
)
from tests.test_hvs_dynamics import FakeClients


def contribution_document_with_rv() -> dict:
    document = ai_document()
    rv = ai_value("510", error="4", kind="this_paper")
    rv["unit"] = "km/s"
    contribution = ai_contribution(
        identifiers={
            "gaia_source_id": "Gaia DR3 123",
            "all": [{"value": "FIC-1", "evidence": []}],
        },
        measurements=[
            {
                "field": "observed_phase_space.radial_velocity",
                "values": [rv],
            }
        ],
    )
    document["object_contributions"] = [contribution]
    return document


def catalog_object(object_id: str = "hvc-fic-1") -> dict:
    return {
        "schema": {"name": "hvs_contribution_catalog.object", "version": 1},
        "generated_at": "2026-08-22T00:00:00+00:00",
        "object_id": object_id,
        "display_name": "FIC-1",
        "aliases": ["FIC-1"],
        "gaia_source_keys": ["gaia dr3 123"],
        "timeline": [],
        "display_note": "timeline record",
        "external_enrichment": {
            "status": "success",
            "providers": {
                "gaia_dr3": {
                    "status": "matched",
                    "source_id": "123",
                    "raw_columns": {
                        "source_id": 123,
                        "ra": 10.0,
                        "dec": 20.0,
                        "parallax": 1.0,
                        "parallax_error": 0.1,
                        "pmra": 1.2,
                        "pmra_error": 0.05,
                        "pmdec": -0.2,
                        "pmdec_error": 0.06,
                        "parallax_pmra_corr": 0.1,
                        "parallax_pmdec_corr": -0.1,
                        "pmra_pmdec_corr": 0.0,
                        "phot_g_mean_mag": 15.0,
                        "nu_eff_used_in_astrometry": 1.5,
                        "pseudocolour": "",
                        "ecl_lat": 30.0,
                        "astrometric_params_solved": 31,
                    },
                }
            },
        },
    }


def stage(workspace: Path) -> tuple[Path, Path, dict, dict]:
    literature_dir = workspace / "literature"
    paper_dir = literature_dir / "2601.00001"
    paper_dir.mkdir(parents=True)
    document = contribution_document_with_rv()
    contribution_path = paper_dir / "literature_hvs_contributions.json"
    contribution_path.write_text(
        json.dumps(document, ensure_ascii=False), encoding="utf-8"
    )
    catalog_dir = workspace / "catalog" / "contributions"
    catalog_dir.mkdir(parents=True)
    object_record = catalog_object()
    (catalog_dir / "hvc-fic-1.json").write_text(
        json.dumps(object_record, ensure_ascii=False), encoding="utf-8"
    )
    rv = document["object_contributions"][0]["measurements"][0]["values"][0]
    selection = build_input_selection(
        object_id="hvc-fic-1",
        gaia_identity="Gaia DR3 123",
        astrometry_source="gaia_dr3",
        radial_velocity_snapshot=rv,
        contribution_path="literature/2601.00001/literature_hvs_contributions.json",
        record_id="obj-001",
        field="observed_phase_space.radial_velocity",
        selector="expert-a",
        selected_at="2026-08-22",
        rationale="Explicit expert choice of the fiducial RV measurement.",
        evidence=[],
        contribution_artifact=document,
    )
    return catalog_dir, contribution_path, document, selection


def file_sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


class InputSelectionTest(unittest.TestCase):
    def test_fingerprint_is_value_and_evidence_sensitive(self) -> None:
        rv = ai_value("510", error="4")
        base = selected_value_fingerprint(rv)
        self.assertEqual(base, selected_value_fingerprint(copy.deepcopy(rv)))
        changed = copy.deepcopy(rv)
        changed["value"] = "511"
        self.assertNotEqual(base, selected_value_fingerprint(changed))
        moved = copy.deepcopy(rv)
        moved["direct_evidence"][0]["source"]["start_line"] = 99
        self.assertNotEqual(base, selected_value_fingerprint(moved))

    def test_validate_verifies_and_stale_fingerprint_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            _catalog_dir, _path, _document, selection = stage(workspace)
            # build_input_selection hashed the in-memory document; recompute
            # against the file so the artifact hash matches.
            contribution_path = workspace / selection["selected"]["contribution_path"]
            selection["source_artifact_sha256"] = file_sha(contribution_path)
            validate_input_selection(selection, workspace=workspace, expected_object_id="hvc-fic-1")
            stale = copy.deepcopy(selection)
            stale["selected"]["fingerprint"] = "0" * 64
            with self.assertRaises(InputSelectionError):
                validate_input_selection(stale, workspace=workspace)
            wrong_object = copy.deepcopy(selection)
            wrong_object["object_id"] = "hvc-other"
            with self.assertRaises(InputSelectionError):
                validate_input_selection(wrong_object, workspace=workspace, expected_object_id="hvc-fic-1")

    def test_stale_artifact_hash_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            _catalog_dir, contribution_path, _document, selection = stage(workspace)
            selection["source_artifact_sha256"] = file_sha(contribution_path)
            contribution_path.write_text(
                json.dumps(contribution_document_with_rv(), ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(InputSelectionError, "stale"):
                validate_input_selection(selection, workspace=workspace)

    def test_missing_selection_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            with self.assertRaisesRegex(InputSelectionError, "missing explicit input selection"):
                selection_for_object(workspace / "selections", "hvc-fic-1")

    def test_dynamics_requires_selection_and_computes_with_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            catalog_dir, contribution_path, _document, selection = stage(workspace)
            selection["source_artifact_sha256"] = file_sha(contribution_path)
            selection_dir = workspace / "selections"
            selection_dir.mkdir()
            (selection_dir / "hvc-fic-1.json").write_text(
                json.dumps(selection, ensure_ascii=False), encoding="utf-8"
            )
            missing = calculate_contribution_catalog_dynamics(
                catalog_dir,
                selection_dir=workspace / "nowhere",
                workspace=workspace,
                clients=FakeClients(),
            )
            (result,) = missing["results"]
            self.assertEqual(result["status"], "selection_missing")

            computed = calculate_contribution_catalog_dynamics(
                catalog_dir,
                selection_dir=selection_dir,
                workspace=workspace,
                clients=FakeClients(),
            )
            (result,) = computed["results"]
            self.assertNotEqual(result["status"], "selection_missing")
            self.assertNotEqual(result["status"], "selection_stale")

    def test_adapter_uses_only_selected_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            _catalog_dir, _path, document, selection = stage(workspace)
            selection["source_artifact_sha256"] = "0" * 64
            adapter = contribution_dynamics_adapter_record(
                catalog_object(), selection, document
            )
            self.assertEqual(
                adapter["canonical_identifier"]["value"], "Gaia DR3 123"
            )
            (candidate,) = adapter["candidates"]
            rv = candidate["core"]["observed_phase_space"]["radial_velocity"]
            self.assertEqual(rv["value"], "510")
            self.assertEqual(rv["error"], "4")
            # No automatic astrometry when the selection is Gaia-based.
            self.assertNotIn("parallax", candidate["core"]["observed_phase_space"])


if __name__ == "__main__":
    unittest.main()
