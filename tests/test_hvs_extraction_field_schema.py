"""submit_candidate_fields schema compilation tests."""

from __future__ import annotations

import unittest

from stella.hvs_extraction.field_schema import (
    CORE_FIELD_PATHS,
    build_field_submission_schema,
)
from stella.lit.extraction.schema_check import collect_schema_errors


TEX = ["main.tex"]
ECSV = ["catalog_tables/t1.ecsv"]


def quantity(**overrides) -> dict:
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
                    "kind": "text",
                    "path": "main.tex",
                    "start_line": 3,
                    "end_line": 3,
                    "raw_value": "805",
                },
            }
        ],
        "context_evidence": [],
    }
    base.update(overrides)
    return base


def valid_submission() -> dict:
    return {
        "candidate_origin": {
            "origin_type": "introduced_by_this_paper",
            "bibkey": None,
            "evidence": [
                {"kind": "text", "path": "main.tex", "start_line": 3, "end_line": 3}
            ],
        },
        "core": {
            "observed_phase_space": {
                "ra": None,
                "dec": None,
                "distance": None,
                "parallax": None,
                "proper_motion_ra": None,
                "proper_motion_dec": None,
                "radial_velocity": quantity(),
            },
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


class FieldSchemaTest(unittest.TestCase):
    def test_all_19_core_fields_are_required(self) -> None:
        schema = build_field_submission_schema(TEX, ECSV)
        self.assertEqual(len(CORE_FIELD_PATHS), 19)
        core = schema["properties"]["core"]
        for group, fields in (
            ("observed_phase_space", 7),
            ("derived_kinematics", 10),
            ("bound_assessment", 2),
        ):
            group_schema = core["properties"][group]
            self.assertEqual(len(group_schema["required"]), fields)
            self.assertEqual(
                set(group_schema["required"]), set(group_schema["properties"])
            )

    def test_valid_submission_passes(self) -> None:
        schema = build_field_submission_schema(TEX, ECSV)
        self.assertEqual(collect_schema_errors(valid_submission(), schema), [])

    def test_missing_field_key_and_extra_key_are_format_errors(self) -> None:
        schema = build_field_submission_schema(TEX, ECSV)
        payload = valid_submission()
        del payload["core"]["observed_phase_space"]["ra"]
        payload["core"]["bound_assessment"]["invented"] = None
        issues = collect_schema_errors(payload, schema)
        rendered = "\n".join(issue.render() for issue in issues)
        self.assertIn("missing required property 'ra'", rendered)
        self.assertIn("unexpected property 'invented'", rendered)

    def test_quantity_accepts_null_or_object_only(self) -> None:
        schema = build_field_submission_schema(TEX, ECSV)
        payload = valid_submission()
        payload["core"]["observed_phase_space"]["distance"] = "12.5"
        issues = collect_schema_errors(payload, schema)
        self.assertTrue(
            any("oneOf" in issue.message for issue in issues),
            [issue.render() for issue in issues],
        )

    def test_coordinate_format_required_for_ra_dec(self) -> None:
        schema = build_field_submission_schema(TEX, ECSV)
        payload = valid_submission()
        coord = quantity(coordinate_format="decimal_degrees")
        payload["core"]["observed_phase_space"]["ra"] = coord
        self.assertEqual(collect_schema_errors(payload, schema), [])
        del coord["coordinate_format"]
        issues = collect_schema_errors(payload, schema)
        self.assertTrue(
            any("coordinate_format" in issue.render() for issue in issues)
        )

    def test_ecsv_branch_present_only_when_ecsv_visible(self) -> None:
        with_ecsv = build_field_submission_schema(TEX, ECSV)
        self.assertIn("ecsv_cell", str(with_ecsv))
        tex_only = build_field_submission_schema(TEX, [])
        self.assertNotIn("ecsv_cell", str(tex_only))
        # TeX-only mode forbids provenance conflicts entirely.
        self.assertEqual(
            tex_only["properties"]["provenance_conflicts"].get("maxItems"), 0
        )
        payload = valid_submission()
        self.assertEqual(collect_schema_errors(payload, tex_only), [])

    def test_conflict_item_shape_when_ecsv_visible(self) -> None:
        schema = build_field_submission_schema(TEX, ECSV)
        payload = valid_submission()
        payload["provenance_conflicts"].append(
            {
                "field": "observed_phase_space.radial_velocity",
                "tex_source": {"path": "main.tex", "start_line": 3, "end_line": 3},
                "ecsv_source": {
                    "path": "catalog_tables/t1.ecsv",
                    "line": 7,
                    "column": "col_002",
                },
                "resolution": "use_tex",
                "reason": "The converted cell dropped the sign.",
            }
        )
        self.assertEqual(collect_schema_errors(payload, schema), [])
        payload["provenance_conflicts"][0]["field"] = "invented.field"
        issues = collect_schema_errors(payload, schema)
        self.assertTrue(any("enum" in issue.message for issue in issues))


if __name__ == "__main__":
    unittest.main()
