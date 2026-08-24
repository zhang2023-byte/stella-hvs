"""Explicit dynamics input-selection tests (synthetic fixtures only)."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from tests.test_hvs_contribution_scoring import (
    ai_contribution,
    ai_document,
    ai_identifier,
    ai_value,
)
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
    rv["direct_evidence"].append(
        {
            "part": "error",
            "source": {
                "kind": "text",
                "path": "main.tex",
                "start_line": 3,
                "end_line": 3,
                "raw_value": "4",
            },
        }
    )
    contribution = ai_contribution(
        identifiers=[
            ai_identifier("Gaia DR3 123"),
            ai_identifier("FIC-1"),
        ],
        quantities=[
            {
                "quantity": "observed_phase_space.radial_velocity",
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
        "identifiers": ["FIC-1", "Gaia DR3 123"],
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
    (catalog_dir / "index.json").write_text(
        json.dumps({"objects": [{"object_id": "hvc-fic-1"}]}),
        encoding="utf-8",
    )
    rv = document["object_contributions"][0]["quantities"][0]["values"][0]
    selection = build_input_selection(
        workspace=workspace,
        object_id="hvc-fic-1",
        gaia_identity="Gaia DR3 123",
        astrometry_source="gaia_dr3",
        selected_values={"observed_phase_space.radial_velocity": rv},
        contribution_path="literature/2601.00001/literature_hvs_contributions.json",
        record_id="obj-001",
        selector="expert-a",
        selected_at="2026-08-22",
        rationale="Explicit expert choice of the fiducial RV measurement.",
        evidence=[],
    )
    return catalog_dir, contribution_path, document, selection


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
        changed_condition = copy.deepcopy(rv)
        changed_condition["condition"] = "another condition"
        self.assertNotEqual(base, selected_value_fingerprint(changed_condition))

    def test_validate_verifies_and_stale_fingerprint_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            _catalog_dir, _path, _document, selection = stage(workspace)
            validate_input_selection(selection, workspace=workspace, expected_object_id="hvc-fic-1")
            stale = copy.deepcopy(selection)
            stale["selected"]["values"]["observed_phase_space.radial_velocity"]["fingerprint"] = "0" * 64
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
            catalog_dir, _contribution_path, _document, selection = stage(workspace)
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

    def test_contribution_astrometry_requires_and_uses_explicit_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            _catalog_dir, contribution_path, document, _selection = stage(workspace)
            contribution = document["object_contributions"][0]

            def value(text: str, unit: str) -> dict:
                item = ai_value(text)
                item["unit"] = unit
                return item

            parallax_a = value("0.20", "mas")
            parallax_b = value("0.25", "mas")
            pmra = value("1.2", "mas/yr")
            pmdec = value("-0.2", "mas/yr")
            contribution["quantities"].extend(
                [
                    {
                        "quantity": "observed_phase_space.parallax",
                        "values": [parallax_a, parallax_b],
                    },
                    {
                        "quantity": "observed_phase_space.proper_motion_ra",
                        "values": [pmra],
                    },
                    {
                        "quantity": "observed_phase_space.proper_motion_dec",
                        "values": [pmdec],
                    },
                ]
            )
            contribution_path.write_text(json.dumps(document), encoding="utf-8")
            rv = contribution["quantities"][0]["values"][0]
            selection = build_input_selection(
                workspace=workspace,
                object_id="hvc-fic-1",
                gaia_identity="Gaia DR3 123",
                astrometry_source="contribution",
                selected_values={
                    "observed_phase_space.radial_velocity": rv,
                    "observed_phase_space.parallax": parallax_b,
                    "observed_phase_space.proper_motion_ra": pmra,
                    "observed_phase_space.proper_motion_dec": pmdec,
                },
                contribution_path="literature/2601.00001/literature_hvs_contributions.json",
                record_id="obj-001",
                selector="expert-a",
                selected_at="2026-08-22",
                rationale="Explicit selection of every dynamics input.",
            )
            adapter = contribution_dynamics_adapter_record(
                catalog_object(), selection, document
            )
            observed = adapter["candidates"][0]["core"]["observed_phase_space"]
            self.assertEqual(observed["parallax"]["value"], "0.25")

            contribution["quantities"][1]["values"].reverse()
            reordered = contribution_dynamics_adapter_record(
                catalog_object(), selection, document
            )
            self.assertEqual(
                reordered["candidates"][0]["core"]["observed_phase_space"]["parallax"]["value"],
                "0.25",
            )

    def test_selection_requires_source_hash_and_all_astrometry_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            _catalog_dir, _path, document, selection = stage(workspace)
            missing_hash = copy.deepcopy(selection)
            missing_hash["source_artifact_sha256"] = ""
            with self.assertRaisesRegex(InputSelectionError, "source_artifact_sha256"):
                validate_input_selection(missing_hash, workspace=workspace)

            rv = document["object_contributions"][0]["quantities"][0]["values"][0]
            with self.assertRaisesRegex(InputSelectionError, "exactly"):
                build_input_selection(
                    workspace=workspace,
                    object_id="hvc-fic-1",
                    gaia_identity="Gaia DR3 123",
                    astrometry_source="contribution",
                    selected_values={"observed_phase_space.radial_velocity": rv},
                    contribution_path="literature/2601.00001/literature_hvs_contributions.json",
                    record_id="obj-001",
                    selector="expert-a",
                    selected_at="2026-08-22",
                    rationale="Incomplete selection must fail.",
                )


if __name__ == "__main__":
    unittest.main()
