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
    parse_dec_raw_degrees,
    parse_ra_raw_degrees,
    upgrade_annotation,
)
from stella.lit.schema_specs import (
    LITERATURE_HVS_METHOD_STEP_TYPES,
)

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = ROOT / "benchmark" / "templates"


def example_payload() -> dict:
    path = TEMPLATES_DIR / "gold_annotation_example.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


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

    def test_example_step_types_are_in_frozen_vocabulary(self) -> None:
        payload = example_payload()
        for step in payload["step_types_present"]:
            self.assertIn(step, LITERATURE_HVS_METHOD_STEP_TYPES)


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

    def test_unknown_step_type_is_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["step_types_present"].append("data_collection")
        self.assert_invalid(payload, "unknown step types")

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
        quantity = payload["candidates"][0]["quantities"][3]
        self.assertEqual(quantity["limit_kind"], "range")
        quantity["value"] = "9.9"
        self.assert_invalid(payload, "range quantities keep value empty")

    def test_range_bounds_without_range_kind_are_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        quantity = payload["candidates"][0]["quantities"][0]
        quantity["range_lower"] = "1"
        quantity["range_upper"] = "2"
        self.assert_invalid(payload, "range bounds require limit_kind")

    def test_candidate_without_identity_is_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["candidates"][0]["names"] = []
        payload["candidates"][0]["gaia_source_id"] = ""
        self.assert_invalid(payload, "at least one name or a gaia_source_id")

    def test_candidate_without_evidence_is_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["candidates"][0]["evidence"] = []
        self.assert_invalid(payload, "candidate-level evidence is required")

    def test_duplicate_record_ids_are_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["candidates"].append(copy.deepcopy(payload["candidates"][0]))
        self.assert_invalid(payload, "record_id values must be unique")

    def test_reported_fact_needs_value(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["method_facts"][0]["value"] = ""
        self.assert_invalid(payload, "reported method facts need a value")

    def test_not_reported_fact_keeps_value_empty(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["method_facts"][2]["value"] = "233"
        self.assert_invalid(payload, "not_reported method facts keep value empty")

    def test_duplicate_method_fact_names_are_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["method_facts"].append(copy.deepcopy(payload["method_facts"][0]))
        self.assert_invalid(payload, "duplicate method facts")

    def test_extra_keys_are_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["surprise"] = True
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
        payload["candidates"][0]["quantities"][0]["value"] = "~612"
        self.assert_invalid(payload, "must be a plain number")

    def test_non_numeric_error_is_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["candidates"][0]["quantities"][0]["error"] = "4.1 km/s"
        self.assert_invalid(payload, "must be a plain number")

    def test_scientific_notation_is_accepted(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["candidates"][0]["quantities"][0]["value"] = "1.3e5"
        upgrade_annotation(payload)

    def test_dec_out_of_range_is_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["candidates"][0]["dec_deg"] = 99.0
        self.assert_invalid(payload, "dec_deg out of range")

    def test_ra_out_of_range_is_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["candidates"][0]["ra_deg"] = 360.0
        self.assert_invalid(payload, "ra_deg out of range")

    def test_epoch_out_of_range_is_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["candidates"][0]["epoch_year"] = 1066.0
        self.assert_invalid(payload, "epoch_year out of range")

    def test_malformed_gaia_id_is_rejected(self) -> None:
        payload = copy.deepcopy(self.payload)
        payload["candidates"][0]["gaia_source_id"] = "GaiaDR3 123"
        self.assert_invalid(payload, "gaia_source_id must look like")


class CoordinateConversionTest(unittest.TestCase):
    def test_hms_string_converts_to_degrees(self) -> None:
        self.assertAlmostEqual(
            parse_ra_raw_degrees("12h34m03.0s"), 188.5125, places=4
        )

    def test_colon_separated_ra_is_hours(self) -> None:
        self.assertAlmostEqual(parse_ra_raw_degrees("12:00:00"), 180.0, places=6)

    def test_explicit_deg_marker_is_degrees(self) -> None:
        self.assertAlmostEqual(
            parse_ra_raw_degrees("243.0979 deg"), 243.0979, places=4
        )

    def test_plain_number_ra_is_degrees(self) -> None:
        self.assertAlmostEqual(parse_ra_raw_degrees("188.512"), 188.512, places=4)

    def test_dms_dec_converts(self) -> None:
        self.assertAlmostEqual(
            parse_dec_raw_degrees("+56d46m51.6s"), 56.781, places=4
        )
        self.assertAlmostEqual(
            parse_dec_raw_degrees("-06:01:12"), -6.02, places=4
        )

    def test_candidate_raw_fields_fill_decimal_fields(self) -> None:
        payload = example_payload()
        candidate = payload["candidates"][0]
        candidate["ra_deg"] = None
        candidate["dec_deg"] = None
        candidate["ra_raw"] = "12h34m02.88s"
        candidate["dec_raw"] = "+56:46:51.6"
        document = upgrade_annotation(payload)
        out = document["candidates"][0]
        self.assertAlmostEqual(out["ra_deg"], 188.512, places=3)
        self.assertAlmostEqual(out["dec_deg"], 56.781, places=3)

    def test_raw_and_decimal_together_are_rejected(self) -> None:
        payload = example_payload()
        payload["candidates"][0]["ra_raw"] = "12h34m03s"  # ra_deg already set
        with self.assertRaises(ValidationError) as ctx:
            GoldAnnotation.model_validate(payload)
        self.assertIn("not both", str(ctx.exception))

    def test_unparseable_raw_is_rejected(self) -> None:
        payload = example_payload()
        candidate = payload["candidates"][0]
        candidate["ra_deg"] = None
        candidate["ra_raw"] = "twelve hours and a bit"
        with self.assertRaises(ValidationError) as ctx:
            GoldAnnotation.model_validate(payload)
        self.assertIn("cannot parse ra_raw", str(ctx.exception))


class LintTest(unittest.TestCase):
    def test_clean_example_has_no_lint_warnings(self) -> None:
        annotation = GoldAnnotation.model_validate(example_payload())
        self.assertEqual(lint_annotation(annotation), [])

    def test_unusual_velocity_unit_warns(self) -> None:
        payload = example_payload()
        payload["candidates"][0]["quantities"][0]["unit"] = "m/s"
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


if __name__ == "__main__":
    unittest.main()
