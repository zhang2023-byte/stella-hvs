"""Submission-schema and prompt contract tests for grouped measurements."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from stella.hvs_contribution_extraction.measurement_prompts import (
    build_measurement_prompts,
)
from stella.hvs_contribution_extraction.measurement_schema import (
    SUBMIT_OBJECT_MEASUREMENTS,
    build_measurement_submission_schema,
)
from stella.lit.schema_specs import HVS_CONTRIBUTION_MEASUREMENT_FIELDS

ROOT = Path(__file__).resolve().parents[1]
VIEW = "main.tex\n1|\\documentclass{article}\n2|\\begin{document}\n3|text\n"

ASSIGNED_CONTRIBUTION = json.dumps(
    {
        "record_id": "obj-001",
        "identifiers": [{"value": "J1234"}],
        "contribution_type": "candidates_found",
    }
)


class MeasurementSchemaTest(unittest.TestCase):
    def test_top_level_contract(self) -> None:
        schema = build_measurement_submission_schema(["main.tex"], [])
        self.assertEqual(SUBMIT_OBJECT_MEASUREMENTS, "submit_object_measurements")
        self.assertEqual(set(schema["required"]), {"measurements"})
        self.assertFalse(schema.get("additionalProperties"))
        group = schema["properties"]["measurements"]["items"]
        self.assertEqual(set(group["required"]), {"field", "values"})
        self.assertEqual(group["properties"]["values"].get("minItems"), 1)

    def test_field_enum_is_the_frozen_nineteen(self) -> None:
        schema = build_measurement_submission_schema(["main.tex"], [])
        enum = schema["properties"]["measurements"]["items"]["properties"]["field"]["enum"]
        self.assertEqual(set(enum), set(HVS_CONTRIBUTION_MEASUREMENT_FIELDS))
        self.assertEqual(len(enum), 19)
        self.assertNotIn("derived_kinematics.total_velocity", enum)

    def test_value_contract_requires_preference_and_provenance(self) -> None:
        schema = build_measurement_submission_schema(["main.tex"], [])
        value = schema["properties"]["measurements"]["items"]["properties"]["values"]["items"]
        required = set(value["required"])
        for key in (
            "value",
            "error",
            "lower_error",
            "upper_error",
            "unit",
            "limit_kind",
            "range_lower",
            "range_upper",
            "condition_note",
            "paper_preferred",
            "source",
            "direct_evidence",
            "context_evidence",
        ):
            self.assertIn(key, required)
        source = value["properties"]["source"]
        self.assertEqual(set(source["required"]), {"kind"})
        self.assertEqual(set(source["properties"]), {"kind"})
        self.assertEqual(
            source["properties"]["kind"]["enum"],
            ["this_paper", "prior_work", "unclear"],
        )
        preferred = value["properties"]["paper_preferred"]
        self.assertEqual(
            {branch.get("type") for branch in preferred["oneOf"]},
            {"boolean", "null"},
        )
        condition = value["properties"]["condition_note"]
        self.assertEqual(condition["type"], "string")
        self.assertEqual(value["properties"]["notes"]["type"], "string")
        self.assertNotIn("notes", required)

    def test_coordinate_format_declared_with_field_annotation(self) -> None:
        schema = build_measurement_submission_schema(["main.tex"], [])
        value = schema["properties"]["measurements"]["items"]["properties"]["values"]["items"]
        coordinate_format = value["properties"]["coordinate_format"]
        self.assertEqual(set(coordinate_format["enum"]), {
            "decimal_degrees", "sexagesimal_hms", "sexagesimal_dms", "sexagesimal_colon",
        })
        self.assertEqual(
            set(coordinate_format["_applies_to"]),
            {"observed_phase_space.ra", "observed_phase_space.dec"},
        )

    def test_no_scenario_or_measurement_id_anywhere(self) -> None:
        schema = build_measurement_submission_schema(["main.tex"], [])
        text = json.dumps(schema)
        for forbidden in ("scenario", "measurement_id", "ordinal", "sequence"):
            self.assertNotIn(forbidden, text)


class MeasurementPromptTest(unittest.TestCase):
    def test_prompts_render_measurement_rules_not_roster_rules(self) -> None:
        prompts = build_measurement_prompts(
            ROOT,
            manuscript_view=VIEW,
            ecsv_blocks=[],
            assigned_contribution_json=ASSIGNED_CONTRIBUTION,
        )
        system = prompts["system"]
        self.assertIn("[hvs.contrib.all_values_after_l1]", system)
        self.assertIn("[hvs.contrib.grouped_multivalue]", system)
        self.assertIn("[hvs.contrib.paper_preferred]", system)
        # Roster-stage rules stay out of the measurement prompt.
        self.assertNotIn("[hvs.contrib.follow_up]", system)
        self.assertNotIn("[hvs.contrib.paper_boundness]", system)
        # V6 field rules (single-value policy) stay out.
        self.assertNotIn("hvs.field.multiple_estimates", system)
        self.assertNotIn("fewest additional model assumptions", system)
        self.assertIn("submit_object_measurements", system)
        self.assertIn(ASSIGNED_CONTRIBUTION, prompts["user"])
        self.assertIn(VIEW, prompts["user"])

    def test_ecsv_blocks_rendered_when_present(self) -> None:
        prompts = build_measurement_prompts(
            ROOT,
            manuscript_view=VIEW,
            ecsv_blocks=["===== ECSV SOURCE MAPPING -----\necsv_path: catalog_tables/x.ecsv"],
            assigned_contribution_json=ASSIGNED_CONTRIBUTION,
        )
        self.assertIn("CONVERTED TABLES", prompts["user"])
        self.assertIn("ecsv_path: catalog_tables/x.ecsv", prompts["user"])
        self.assertEqual(len(prompts["system_sha256"]), 64)
        self.assertEqual(len(prompts["user_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
