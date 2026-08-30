"""Submission-schema and prompt contract tests for grouped quantities."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from stella.lit.extraction.quantity_prompts import (
    build_quantity_prompts,
)
from stella.lit.extraction.quantity_schema import (
    SUBMIT_OBJECT_QUANTITIES,
    build_quantity_submission_schema,
)
from stella.lit.schema_specs import HVS_CONTRIBUTION_QUANTITIES

ROOT = Path(__file__).resolve().parents[3]
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
        schema = build_quantity_submission_schema(["main.tex"], [])
        self.assertEqual(SUBMIT_OBJECT_QUANTITIES, "submit_object_quantities")
        self.assertEqual(set(schema["required"]), {"quantities"})
        self.assertFalse(schema.get("additionalProperties"))
        group = schema["properties"]["quantities"]["items"]
        self.assertEqual(set(group["required"]), {"quantity", "values"})
        self.assertEqual(group["properties"]["values"].get("minItems"), 1)

    def test_field_enum_is_the_current_eighteen(self) -> None:
        schema = build_quantity_submission_schema(["main.tex"], [])
        enum = schema["properties"]["quantities"]["items"]["properties"]["quantity"]["enum"]
        self.assertEqual(set(enum), set(HVS_CONTRIBUTION_QUANTITIES))
        self.assertEqual(len(enum), 18)
        self.assertNotIn(
            "derived_kinematics.galactocentric_tangential_velocity", enum
        )
        self.assertNotIn("derived_kinematics.total_velocity", enum)

    def test_value_contract_requires_preference_and_provenance(self) -> None:
        schema = build_quantity_submission_schema(["main.tex"], [])
        value = schema["properties"]["quantities"]["items"]["properties"]["values"]["items"]
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
            "condition",
            "paper_preferred",
            "source",
            "direct_evidence",
            "context_evidence",
        ):
            self.assertIn(key, required)
        source = value["properties"]["source"]
        self.assertEqual(
            source["enum"],
            ["this_paper", "prior_work", "unclear"],
        )
        preferred = value["properties"]["paper_preferred"]
        self.assertEqual(
            {branch.get("type") for branch in preferred["oneOf"]},
            {"boolean", "null"},
        )
        condition = value["properties"]["condition"]
        self.assertEqual(condition["type"], "string")
        self.assertEqual(value["properties"]["source_note"]["type"], "string")
        self.assertNotIn("source_note", required)

    def test_coordinate_format_declared_with_field_annotation(self) -> None:
        schema = build_quantity_submission_schema(["main.tex"], [])
        value = schema["properties"]["quantities"]["items"]["properties"]["values"]["items"]
        coordinate_format = value["properties"]["coordinate_format"]
        self.assertEqual(set(coordinate_format["enum"]), {
            "decimal_degrees", "sexagesimal_hms", "sexagesimal_dms", "sexagesimal_colon",
        })
        self.assertEqual(
            set(coordinate_format["_applies_to"]),
            {"observed_phase_space.ra", "observed_phase_space.dec"},
        )

    def test_no_scenario_or_measurement_id_anywhere(self) -> None:
        schema = build_quantity_submission_schema(["main.tex"], [])
        text = json.dumps(schema)
        for forbidden in ("scenario", "measurement_id", "ordinal", "sequence"):
            self.assertNotIn(forbidden, text)

    def test_ecsv_direct_evidence_requires_component_raw_value(self) -> None:
        schema = build_quantity_submission_schema(["main.tex"], ["table.ecsv"])
        value = schema["properties"]["quantities"]["items"]["properties"]["values"]["items"]
        source = value["properties"]["direct_evidence"]["items"]["properties"]["source"]
        ecsv_branch = source["oneOf"][1]
        self.assertIn("component_raw_value", ecsv_branch["required"])
        self.assertNotIn(
            "Only for a compound cell",
            ecsv_branch["properties"]["component_raw_value"]["description"],
        )


class MeasurementPromptTest(unittest.TestCase):
    def test_prompts_render_measurement_rules_not_roster_rules(self) -> None:
        prompts = build_quantity_prompts(
            ROOT,
            manuscript_view=VIEW,
            ecsv_blocks=[],
            assigned_contribution_json=ASSIGNED_CONTRIBUTION,
        )
        system = prompts["system"]
        normalized_system = " ".join(system.split())
        self.assertIn("[hvs.contrib.all_values_after_l1]", system)
        self.assertIn("[hvs.contrib.grouped_multivalue]", system)
        self.assertIn("[hvs.contrib.paper_preferred]", system)
        self.assertIn(
            "Passing a sample-selection or quality-control criterion does not make",
            normalized_system,
        )
        self.assertIn(
            "Selection, query, quality-control, or sample-entry thresholds are not",
            normalized_system,
        )
        # Roster-stage rules stay out of the measurement prompt.
        self.assertNotIn("[hvs.contrib.follow_up]", system)
        self.assertNotIn("[hvs.contrib.paper_boundness]", system)
        # V6 field rules (single-value policy) stay out.
        self.assertNotIn("hvs.field.multiple_estimates", system)
        self.assertNotIn("fewest additional model assumptions", system)
        self.assertIn("submit_object_quantities", system)
        self.assertIn(ASSIGNED_CONTRIBUTION, prompts["user"])
        self.assertIn(VIEW, prompts["user"])

    def test_ecsv_blocks_rendered_when_present(self) -> None:
        prompts = build_quantity_prompts(
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
