from __future__ import annotations

import copy
import unittest
from pathlib import Path

import yaml
from pydantic import ValidationError

from stella.benchmark.gold import (
    GOLD_SCHEMA_VERSION,
    SCORED_QUANTITY_FIELDS,
    GoldAnnotation,
    lint_annotation,
    upgrade_annotation,
)
ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = ROOT / "benchmark" / "templates"


def example_payload() -> dict:
    path = TEMPLATES_DIR / "gold_annotation_example.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def quantity_by_field(payload: dict, field: str) -> dict:
    for quantity in payload["candidates"][0]["quantities"]:
        if quantity["field"] == field:
            return quantity
    raise AssertionError(f"missing quantity field {field!r}")


class TemplateFilesTest(unittest.TestCase):
    def test_example_template_is_valid(self) -> None:
        document = upgrade_annotation(example_payload())
        self.assertEqual(document["schema_version"], GOLD_SCHEMA_VERSION)
        self.assertEqual(document["status"], "candidates_found")
        self.assertEqual(len(document["candidates"]), 1)

    def test_blank_template_parses_as_yaml(self) -> None:
        path = TEMPLATES_DIR / "gold_annotation_template.yaml"
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], GOLD_SCHEMA_VERSION)
        self.assertEqual(payload["evidence_basis"], "pdf")
        # The blank template is intentionally incomplete and must NOT pass
        # validation as-is, otherwise empty annotations could reach gold.
        with self.assertRaises(ValidationError):
            GoldAnnotation.model_validate(payload)


class VocabularySyncTest(unittest.TestCase):
    def test_scored_fields_come_from_frozen_models(self) -> None:
        self.assertIn("observed_phase_space.radial_velocity", SCORED_QUANTITY_FIELDS)
        self.assertIn("derived_kinematics.total_velocity", SCORED_QUANTITY_FIELDS)
        self.assertIn("derived_kinematics.galactocentric_radius", SCORED_QUANTITY_FIELDS)
        self.assertIn("bound_assessment.escape_velocity", SCORED_QUANTITY_FIELDS)


class GoldValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = example_payload()

    def assert_invalid(self, payload: dict, fragment: str) -> None:
        with self.assertRaises(ValidationError) as ctx:
            GoldAnnotation.model_validate(payload)
        self.assertIn(fragment, str(ctx.exception))

    def test_unknown_quantity_field_is_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["candidates"][0]["quantities"][0]["field"] = "core.banana"
        self.assert_invalid(payload, "unknown scored quantity field")

    def test_no_candidates_with_candidates_is_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["status"] = "no_candidates"
        self.assert_invalid(payload, "must not list candidates")

    def test_no_candidates_document_is_valid_without_candidates(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["status"] = "no_candidates"
        payload["candidates"] = []
        document = upgrade_annotation(payload)
        self.assertEqual(document["candidates"], [])

    def test_range_quantity_requires_empty_value_and_bounds(self) -> None:
        payload = copy.deepcopy(self.payload)
        quantity = quantity_by_field(payload, "observed_phase_space.distance")
        self.assertEqual(quantity["limit_kind"], "range")
        quantity["value"] = "9.9"
        self.assert_invalid(payload, "range quantities keep value empty")

    def test_range_bounds_without_range_kind_are_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        quantity = quantity_by_field(payload, "observed_phase_space.radial_velocity")
        quantity["range_lower"] = "1"
        quantity["range_upper"] = "2"
        self.assert_invalid(payload, "range bounds require limit_kind")

    def test_candidate_without_identity_is_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["candidates"][0]["paper_candidate_id"] = ""
        payload["candidates"][0]["gaia_source_id"] = ""
        payload["candidates"][0]["aliases"] = []
        self.assert_invalid(payload, "at least one paper_candidate_id")

    def test_empty_alias_is_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["candidates"][0]["aliases"] = [""]
        self.assert_invalid(payload, "aliases must be non-empty")

    def test_candidate_without_evidence_is_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["candidates"][0]["evidence"] = []
        self.assert_invalid(payload, "candidate-level evidence is required")

    def test_duplicate_paper_candidate_ids_are_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["candidates"].append(copy.deepcopy(payload["candidates"][0]))
        self.assert_invalid(payload, "paper_candidate_id values must be unique")

    def test_duplicate_gaia_source_ids_are_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        duplicate = copy.deepcopy(payload["candidates"][0])
        duplicate["paper_candidate_id"] = "other"
        payload["candidates"].append(duplicate)
        self.assert_invalid(payload, "gaia_source_id values must be unique")

    def test_extra_keys_are_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["surprise"] = True
        with self.assertRaises(ValidationError):
            GoldAnnotation.model_validate(payload)

    def test_legacy_method_facts_are_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["method_facts"] = []
        with self.assertRaises(ValidationError):
            GoldAnnotation.model_validate(payload)

    def test_legacy_step_types_are_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["step_types_present"] = []
        with self.assertRaises(ValidationError):
            GoldAnnotation.model_validate(payload)

    def test_legacy_top_level_coordinates_are_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["candidates"][0]["ra_deg"] = 188.512
        with self.assertRaises(ValidationError):
            GoldAnnotation.model_validate(payload)

    def test_missing_guideline_version_is_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["guideline_version"] = "  "
        self.assert_invalid(payload, "guideline_version is required")


class ContentChecksTest(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = example_payload()

    def assert_invalid(self, payload: dict, fragment: str) -> None:
        with self.assertRaises(ValidationError) as ctx:
            GoldAnnotation.model_validate(payload)
        self.assertIn(fragment, str(ctx.exception))

    def test_non_numeric_value_is_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        quantity_by_field(payload, "observed_phase_space.radial_velocity")[
            "value"
        ] = "~612"
        self.assert_invalid(payload, "must be a plain number")

    def test_sexagesimal_non_coordinate_value_is_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        quantity_by_field(payload, "observed_phase_space.radial_velocity")[
            "value"
        ] = "12:34:56"
        self.assert_invalid(payload, "must be a plain number")

    def test_unicode_minus_plain_number_is_accepted(self) -> None:
        payload = copy.deepcopy(self.payload)
        quantity_by_field(payload, "observed_phase_space.radial_velocity")[
            "value"
        ] = "\u2212612.3"
        upgrade_annotation(payload)

    def test_non_numeric_error_is_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        quantity_by_field(payload, "observed_phase_space.radial_velocity")[
            "error"
        ] = "4.1 km/s"
        self.assert_invalid(payload, "must be a plain number")

    def test_sexagesimal_coordinate_values_are_accepted_verbatim(self) -> None:
        payload = copy.deepcopy(self.payload)
        quantity_by_field(payload, "observed_phase_space.ra")[
            "value"
        ] = "12:34:02.88"
        quantity_by_field(payload, "observed_phase_space.ra")["unit"] = "hms"
        dec_value = "\u221266:13:26.9"
        quantity_by_field(payload, "observed_phase_space.dec")["value"] = dec_value
        quantity_by_field(payload, "observed_phase_space.dec")["unit"] = "dms"

        document = upgrade_annotation(payload)

        self.assertEqual(
            quantity_by_field(document, "observed_phase_space.ra")["value"],
            "12:34:02.88",
        )
        self.assertEqual(
            quantity_by_field(document, "observed_phase_space.dec")["value"],
            dec_value,
        )

    def test_malformed_sexagesimal_coordinate_is_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        quantity_by_field(payload, "observed_phase_space.dec")[
            "value"
        ] = "66:61:00"
        self.assert_invalid(payload, "plain number or sexagesimal coordinate")

    def test_scientific_notation_is_accepted(self) -> None:
        payload = copy.deepcopy(self.payload)
        quantity_by_field(payload, "observed_phase_space.radial_velocity")[
            "value"
        ] = "1.3e5"
        upgrade_annotation(payload)

    def test_dec_quantity_out_of_range_is_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        quantity_by_field(payload, "observed_phase_space.dec")["value"] = "99"
        self.assert_invalid(payload, "observed_phase_space.dec out of range")

    def test_ra_quantity_out_of_range_is_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        quantity_by_field(payload, "observed_phase_space.ra")["value"] = "360"
        self.assert_invalid(payload, "observed_phase_space.ra out of range")

    def test_malformed_gaia_id_is_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["candidates"][0]["gaia_source_id"] = "GaiaDR3 123"
        self.assert_invalid(payload, "gaia_source_id must look like")


class LintTest(unittest.TestCase):
    def test_clean_example_has_no_lint_warnings(self) -> None:
        annotation = GoldAnnotation.model_validate(example_payload())
        self.assertEqual(lint_annotation(annotation), [])

    def test_unusual_velocity_unit_warns(self) -> None:
        payload = example_payload()
        quantity_by_field(payload, "observed_phase_space.radial_velocity")[
            "unit"
        ] = "m/s"
        annotation = GoldAnnotation.model_validate(payload)
        warnings = lint_annotation(annotation)
        self.assertEqual(len(warnings), 1)
        self.assertIn("unusual", warnings[0])

    def test_probability_with_unit_warns(self) -> None:
        payload = example_payload()
        payload["candidates"][0]["quantities"][0] = {
            "field": "bound_assessment.unbound_probability",
            "value": "0.99995",
            "unit": "%",
            "evidence": [{"location": "Table 2"}],
        }
        annotation = GoldAnnotation.model_validate(payload)
        warnings = lint_annotation(annotation)
        self.assertEqual(len(warnings), 1)
        self.assertIn("unitless", warnings[0])

    def test_transformed_distance_unit_is_not_flagged(self) -> None:
        # log distance / distance modulus are kept verbatim (no conversion, to
        # stay aligned with the frozen AI side); their free-text units must not
        # trip the "unusual unit" warning.
        for unit in ("log(D/kpc)", "mag", "dex"):
            payload = example_payload()
            payload["candidates"][0]["quantities"] = [
                {
                    "field": "observed_phase_space.distance",
                    "value": "0.936",
                    "unit": unit,
                    "evidence": [{"location": "Table 1"}],
                }
            ]
            annotation = GoldAnnotation.model_validate(payload)
            self.assertEqual(
                lint_annotation(annotation), [], f"unit {unit!r} should be clean"
            )


if __name__ == "__main__":
    unittest.main()
