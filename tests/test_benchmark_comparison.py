import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "benchmark" / "comparison" / "build_gold_ai_comparison.py"
SPEC = importlib.util.spec_from_file_location("build_gold_ai_comparison", SCRIPT)
comparison = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(comparison)


class BenchmarkComparisonTests(unittest.TestCase):
    def test_probability_percent_and_unit_spelling_are_aligned(self) -> None:
        probability = comparison.compare_quantity_row(
            "J1603-6613",
            "bound_assessment.unbound_probability",
            {"value": "1"},
            {"value": "100", "unit": "%"},
        )
        self.assertEqual(probability["status"], "一致")
        self.assertFalse(probability["review_required"])

        velocity = comparison.compare_quantity_row(
            "J0905+2510",
            "derived_kinematics.galactic_rest_frame_velocity",
            {"value": "730", "unit": "km/s"},
            {"value": "~730", "unit": "km s^-1"},
        )
        self.assertEqual(velocity["status"], "一致")
        self.assertFalse(velocity["review_required"])

    def test_missing_uncertainty_is_not_numeric_mismatch(self) -> None:
        row = comparison.compare_quantity_row(
            "Li10",
            "observed_phase_space.radial_velocity",
            {"value": "234", "error": "5", "unit": "km/s"},
            {"value": "234", "unit": "km s^-1", "raw_value": "234 +/- 5"},
        )
        self.assertEqual(row["status"], "缺误差")
        self.assertEqual(row["kind"], "quantity_uncertainty_missing")
        self.assertIn("raw_value", row["note"])

    def test_numeric_mismatch_is_marked_as_numeric(self) -> None:
        row = comparison.compare_quantity_row(
            "J1603-6613",
            "observed_phase_space.radial_velocity",
            {"value": "-480", "unit": "km/s"},
            {"value": "-485", "unit": "km s^-1"},
        )
        self.assertEqual(row["status"], "数值不一致")
        self.assertEqual(row["class"], "critical")

    def test_identity_gaia_alias_origin_and_evidence_align(self) -> None:
        rows = comparison.compare_candidate_surface(
            {
                "paper_candidate_id": "LP40−365",
                "gaia_source_id": "Gaia DR2 5405579151566448896",
                "aliases": ["WD J1603-6613"],
                "origin_type": "cited_from_literature",
                "evidence": [{"location": "Sec. 4"}],
                "quantities": [],
            },
            {
                "identifiers": {
                    "paper_candidate_id": "LP 40-365",
                    "gaia_source_id": "5405579151566448896",
                    "all": [
                        {"value": "LP 40-365"},
                        {"value": "WD J1603-6613"},
                        {"value": "Gaia DR2 5405579151566448896"},
                    ],
                },
                "candidate_origin": {
                    "origin_type": "introduced_by_previous_paper",
                    "source_refs": [{"path": "paper.tex"}],
                },
                "inclusion_assessment": {"source_refs": [{"path": "paper.tex"}]},
            },
        )["rows"]
        self.assertFalse([row for row in rows if row["review_required"]])

    def test_ai_only_gaia_source_id_is_review_item(self) -> None:
        rows = comparison.compare_identity_rows(
            {"paper_candidate_id": "LP40−365", "gaia_source_id": "", "aliases": []},
            {
                "identifiers": {
                    "paper_candidate_id": "LP 40-365",
                    "gaia_source_id": "Gaia DR2 5405579151566448896",
                }
            },
            "LP40-365",
        )
        gaia_row = next(row for row in rows if row["field"] == "gaia_source_id")
        self.assertEqual(gaia_row["status"], "AI-only")
        self.assertTrue(gaia_row["review_required"])

    def test_ai_paper_id_can_use_gold_gaia_when_gold_has_no_paper_id(self) -> None:
        rows = comparison.compare_identity_rows(
            {
                "paper_candidate_id": "",
                "gaia_source_id": "Gaia DR3 1309092223502856576",
                "aliases": [],
            },
            {
                "identifiers": {
                    "paper_candidate_id": "Gaia DR3 1309092223502856576",
                    "gaia_source_id": "Gaia DR3 1309092223502856576",
                }
            },
            "Gaia DR3 1309092223502856576",
        )
        paper_row = next(row for row in rows if row["field"] == "paper_candidate_id")
        self.assertEqual(paper_row["status"], "一致")
        self.assertFalse(paper_row["review_required"])


if __name__ == "__main__":
    unittest.main()
