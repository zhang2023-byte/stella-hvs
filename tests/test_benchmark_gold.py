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


if __name__ == "__main__":
    unittest.main()
