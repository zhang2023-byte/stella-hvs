"""Scratch-to-scorer projection tests (D034, D038)."""

from __future__ import annotations

import unittest

from stella.benchmark.scoring import score_paper
from stella.benchmark.scratch.projection import (
    project_paper_result,
    project_quantity,
)
from test_benchmark_scoring import (
    ai_document,
    gold_candidate,
    gold_document,
)


def scratch_quantity(**overrides) -> dict:
    base = {
        "value": "805",
        "error": None,
        "lower_error": None,
        "upper_error": None,
        "unit": "km/s",
        "limit_kind": "none",
        "range_lower": None,
        "range_upper": None,
        "direct_evidence": [
            {
                "part": "value",
                "source": {
                    "kind": "ecsv_cell",
                    "path": "catalog_tables/t1.ecsv",
                    "line": 8,
                    "column": "col_002",
                    "quantity_raw_value": "805",
                },
            }
        ],
        "context_evidence": [],
    }
    base.update(overrides)
    return base


def paper_result(
    *,
    status: str = "complete",
    roster_status: str = "candidates_found",
    candidates: list[dict] | None = None,
    fields: dict | None = None,
) -> dict:
    roster_candidates = [
        {
            "record_id": "candidate-001",
            "display_name": "HVS-1",
            "identifiers": [
                {
                    "value": "HVS-1",
                    "source_refs": [],
                    "recognition": {"kind": "other"},
                },
                {
                    "value": "Gaia DR3 123456789",
                    "source_refs": [],
                    "recognition": {
                        "kind": "gaia",
                        "release": "DR3",
                        "source_id": "123456789",
                    },
                },
            ],
            "qualification": {"reason": "r", "source_refs": []},
        }
    ]
    entries = []
    for index, candidate in enumerate(candidates or [], 1):
        entry = {
            "record_id": candidate["record_id"],
            "display_name": "HVS-1",
            "status": candidate["status"],
            "fields": fields if candidate["status"] == "fields_complete" else None,
            "bibliography": {
                "origin_type": "introduced_by_this_paper",
                "paper_reassesses_unbound_status": False,
                "resolution": None,
            },
            "failure": candidate.get("failure"),
            "attempts": [],
            "provenance": {},
        }
        entries.append(entry)
    return {
        "status": status,
        "roster_status": roster_status,
        "roster": {"candidates": roster_candidates, "reviewed_exclusions": []},
        "candidates": entries,
    }


def complete_fields(**core_overrides) -> dict:
    observed = {
        "ra": None,
        "dec": None,
        "distance": None,
        "parallax": None,
        "proper_motion_ra": None,
        "proper_motion_dec": None,
        "radial_velocity": scratch_quantity(),
    }
    observed.update(core_overrides)
    return {
        "candidate_origin": {
            "origin_type": "introduced_by_this_paper",
            "bibkey": None,
            "evidence": [],
        },
        "core": {
            "observed_phase_space": observed,
            "derived_kinematics": {
                "galactocentric_x": None,
                "galactocentric_y": None,
                "galactocentric_z": None,
                "galactocentric_radius": None,
                "galactocentric_vx": None,
                "galactocentric_vy": None,
                "galactocentric_vz": None,
                "tangential_velocity": None,
                "galactocentric_tangential_velocity": None,
                "galactic_rest_frame_velocity": None,
            },
            "bound_assessment": {
                "bound_probability": None,
                "unbound_probability": None,
            },
        },
        "provenance_conflicts": [],
    }


class QuantityProjectionTest(unittest.TestCase):
    def test_null_quantity_projects_to_empty_dict(self) -> None:
        self.assertEqual(project_quantity(None, coordinate=False), {})

    def test_conventions(self) -> None:
        projected = project_quantity(scratch_quantity(), coordinate=False)
        self.assertEqual(projected["value"], "805")
        self.assertEqual(projected["limit_kind"], "")
        self.assertEqual(projected["error"], "")
        self.assertEqual(projected["raw_value"], "805")
        ranged = project_quantity(
            scratch_quantity(
                value=None,
                limit_kind="range",
                range_lower="800",
                range_upper="810",
            ),
            coordinate=False,
        )
        self.assertEqual(ranged["limit_kind"], "range")
        self.assertEqual(ranged["range_lower"], "800")
        self.assertEqual(ranged["value"], "")

    def test_uncertainty_and_coordinate_format_preserved(self) -> None:
        projected = project_quantity(
            scratch_quantity(error="12", coordinate_format="decimal_degrees"),
            coordinate=True,
        )
        self.assertEqual(projected["error"], "12")
        self.assertEqual(projected["coordinate_format"], "decimal_degrees")


class PaperProjectionTest(unittest.TestCase):
    def test_complete_paper_full_mapping(self) -> None:
        result = paper_result(
            candidates=[{"record_id": "candidate-001", "status": "fields_complete"}],
            fields=complete_fields(),
        )
        document = project_paper_result(result)
        self.assertEqual(document["extraction"]["status"], "candidates_found")
        (candidate,) = document["candidates"]
        identifiers = candidate["identifiers"]
        self.assertEqual(identifiers["record_id"], "candidate-001")
        self.assertEqual(identifiers["paper_candidate_id"], "HVS-1")
        self.assertEqual(identifiers["gaia_source_id"], "Gaia DR3 123456789")
        self.assertEqual(
            [item["value"] for item in identifiers["all"]],
            ["HVS-1", "Gaia DR3 123456789"],
        )
        quantity = candidate["core"]["observed_phase_space"]["radial_velocity"]
        self.assertEqual(quantity["value"], "805")
        self.assertEqual(candidate["core"]["derived_kinematics"]["galactocentric_x"], {})
        self.assertEqual(
            candidate["candidate_origin"]["origin_type"], "introduced_by_this_paper"
        )

    def test_partial_paper_excludes_failed_candidates(self) -> None:
        result = paper_result(
            status="partial",
            candidates=[
                {"record_id": "candidate-001", "status": "field_extraction_failed"}
            ],
        )
        document = project_paper_result(result)
        self.assertEqual(document["extraction"]["status"], "partial")
        self.assertEqual(document["candidates"], [])

    def test_failed_paper_projects_empty(self) -> None:
        document = project_paper_result(paper_result(status="failed"))
        self.assertEqual(document["extraction"]["status"], "failed")
        self.assertEqual(document["candidates"], [])

    def test_empty_roster_projects_no_candidates(self) -> None:
        result = paper_result(roster_status="no_candidates", candidates=[])
        document = project_paper_result(result)
        self.assertEqual(document["extraction"]["status"], "no_candidates")

    def test_roster_only_candidates_project_with_identifiers_and_empty_core(self) -> None:
        result = paper_result(
            candidates=[{"record_id": "candidate-001", "status": "roster_only"}]
        )
        document = project_paper_result(result)
        self.assertEqual(document["extraction"]["status"], "candidates_found")
        (candidate,) = document["candidates"]
        identifiers = candidate["identifiers"]
        self.assertEqual(identifiers["record_id"], "candidate-001")
        self.assertEqual(identifiers["paper_candidate_id"], "HVS-1")
        self.assertEqual(identifiers["gaia_source_id"], "Gaia DR3 123456789")
        self.assertEqual(
            [item["value"] for item in identifiers["all"]],
            ["HVS-1", "Gaia DR3 123456789"],
        )
        # Roster-only candidates carry no field quantities (L1 experiment mode).
        self.assertEqual(
            candidate["core"]["observed_phase_space"]["radial_velocity"], {}
        )
        self.assertIsNone(candidate["candidate_origin"]["origin_type"])


class ProjectionScorerIntegrationTest(unittest.TestCase):
    def _score(self, gold_quantities: list[dict], fields: dict) -> list[dict]:
        gold = gold_document(
            [gold_candidate(gaia="Gaia DR3 123456789", quantities=gold_quantities)]
        )
        result = paper_result(
            candidates=[{"record_id": "candidate-001", "status": "fields_complete"}],
            fields=fields,
        )
        ai = project_paper_result(result)
        _, detail = score_paper("1902.05061", gold, ai, weight=1.0)
        return detail["pairs"][0]["l2"]

    def test_value_match_and_gold_only(self) -> None:
        rows = self._score(
            [
                {"field": "observed_phase_space.radial_velocity", "value": "805", "unit": "km/s"},
                {"field": "bound_assessment.unbound_probability", "value": "0.93"},
            ],
            complete_fields(),
        )
        statuses = {row["field"]: row["status"] for row in rows}
        self.assertEqual(statuses["observed_phase_space.radial_velocity"], "value_match")
        self.assertEqual(statuses["bound_assessment.unbound_probability"], "gold_only")

    def test_ai_only_for_spurious_value(self) -> None:
        fields = complete_fields(
            distance=scratch_quantity(value="6.6", unit="kpc")
        )
        rows = self._score(
            [{"field": "observed_phase_space.radial_velocity", "value": "805", "unit": "km/s"}],
            fields,
        )
        statuses = {row["field"]: row["status"] for row in rows}
        self.assertEqual(statuses["observed_phase_space.distance"], "ai_only")

    def test_unit_mismatch_and_within_gold_error(self) -> None:
        fields = complete_fields()
        fields["core"]["observed_phase_space"]["radial_velocity"] = scratch_quantity(
            unit="km s^-1"
        )
        fields["core"]["bound_assessment"]["unbound_probability"] = scratch_quantity(
            value="0.95", unit=None
        )
        rows = self._score(
            [
                {"field": "observed_phase_space.radial_velocity", "value": "805", "unit": "km/s"},
                {
                    "field": "bound_assessment.unbound_probability",
                    "value": "0.93",
                    "error": "0.05",
                },
            ],
            fields,
        )
        statuses = {row["field"]: row["status"] for row in rows}
        self.assertEqual(
            statuses["observed_phase_space.radial_velocity"], "value_match"
        )
        self.assertEqual(
            statuses["bound_assessment.unbound_probability"], "within_gold_error"
        )

    def test_probability_percent_raw_value_normalizes(self) -> None:
        fields = complete_fields()
        fields["core"]["bound_assessment"]["unbound_probability"] = scratch_quantity(
            value="0.93", unit=None
        )
        fields["core"]["bound_assessment"]["unbound_probability"][
            "direct_evidence"
        ][0]["source"]["quantity_raw_value"] = "93%"
        rows = self._score(
            [{"field": "bound_assessment.unbound_probability", "value": "0.93"}],
            fields,
        )
        self.assertEqual(rows[0]["status"], "value_match")
        # The percent-marked raw is not propagated to the scorer (R7 would
        # normalize the already-normalized fraction a second time).
        from stella.benchmark.scratch.projection import project_paper_result

        result = paper_result(
            candidates=[{"record_id": "candidate-001", "status": "fields_complete"}],
            fields=fields,
        )
        projected = project_paper_result(result)
        self.assertEqual(
            projected["candidates"][0]["core"]["bound_assessment"][
                "unbound_probability"
            ]["raw_value"],
            "0.93",
        )

    def test_limit_kind_mismatch(self) -> None:
        fields = complete_fields(
            radial_velocity=scratch_quantity(limit_kind="lower_limit")
        )
        rows = self._score(
            [{"field": "observed_phase_space.radial_velocity", "value": "805", "unit": "km/s"}],
            fields,
        )
        self.assertEqual(rows[0]["status"], "limit_kind_mismatch")


if __name__ == "__main__":
    unittest.main()
