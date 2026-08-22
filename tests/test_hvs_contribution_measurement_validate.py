"""Deterministic grouped-measurement validation tests."""

from __future__ import annotations

import unittest

from tests.hvs_contribution_fixtures import (
    MEASUREMENT_SUBMISSION,
    alternative_value,
    coordinate_value,
    measurement_manuscript_text,
    measurement_value,
    prior_adopted_value,
    probability_value,
    superseded_value,
)
from stella.hvs_extraction.field_validate import FieldValidationContext
from stella.hvs_contribution_extraction.measurement_validate import (
    BIBKEY_NOT_VERBATIM,
    CITATION_NOT_VERBATIM,
    CONDITION_NOTE_REQUIRED,
    DIRECT_EVIDENCE_MISSING,
    FIELD_DUPLICATE_GROUP,
    FIELD_NOT_IN_VOCABULARY,
    PAPER_PREFERRED_REQUIRED,
    SOURCE_KIND_INVALID,
    VALUE_DUPLICATE,
    VALUES_EMPTY,
    hydrate_measurement_submission,
    validate_measurement_submission,
)


def context(tex: str | None = None) -> FieldValidationContext:
    text = tex if tex is not None else measurement_manuscript_text()
    return FieldValidationContext(
        tex_line_counts={"main.tex": text.count("\n")},
        tex_texts={"main.tex": text},
        ecsv_structures={},
        ecsv_texts={},
    )


def codes(issues) -> set[str]:
    return {issue.code for issue in issues}


class MeasurementValidateTest(unittest.TestCase):
    def test_full_submission_passes(self) -> None:
        issues = validate_measurement_submission(MEASUREMENT_SUBMISSION, context())
        self.assertEqual(issues, [])

    def test_field_vocabulary_and_duplicate_groups(self) -> None:
        payload = {
            "measurements": [
                {"field": "spectroscopy.teff", "values": [measurement_value()]},
            ]
        }
        issues = validate_measurement_submission(payload, context())
        self.assertIn(FIELD_NOT_IN_VOCABULARY, codes(issues))

        payload = {
            "measurements": [
                {"field": "observed_phase_space.distance", "values": [measurement_value()]},
                {"field": "observed_phase_space.distance", "values": [alternative_value()]},
            ]
        }
        issues = validate_measurement_submission(payload, context())
        self.assertIn(FIELD_DUPLICATE_GROUP, codes(issues))

        payload = {"measurements": [{"field": "observed_phase_space.distance", "values": []}]}
        issues = validate_measurement_submission(payload, context())
        self.assertIn(VALUES_EMPTY, codes(issues))

    def test_exact_duplicate_values_rejected_distinct_retained(self) -> None:
        payload = {
            "measurements": [
                {
                    "field": "observed_phase_space.distance",
                    "values": [measurement_value(), measurement_value()],
                }
            ]
        }
        issues = validate_measurement_submission(payload, context())
        self.assertIn(VALUE_DUPLICATE, codes(issues))

        payload = {
            "measurements": [
                {
                    "field": "observed_phase_space.distance",
                    "values": [
                        measurement_value(),
                        alternative_value(),
                        prior_adopted_value(),
                        superseded_value(),
                    ],
                }
            ]
        }
        issues = validate_measurement_submission(payload, context())
        self.assertEqual(issues, [])

    def test_required_per_value_fields(self) -> None:
        no_condition = measurement_value()
        del no_condition["condition_note"]
        no_preferred = measurement_value()
        del no_preferred["paper_preferred"]
        bad_kind = measurement_value(
            source={"kind": "external", "paper_visible_citation": None, "bibkey": None, "citation_evidence": []}
        )
        for value in (no_condition, no_preferred, bad_kind):
            payload = {
                "measurements": [
                    {"field": "observed_phase_space.distance", "values": [value]}
                ]
            }
            issues = validate_measurement_submission(payload, context())
            self.assertTrue(issues, "expected at least one issue")

        payload = {
            "measurements": [{"field": "observed_phase_space.distance", "values": [no_condition]}]
        }
        self.assertIn(CONDITION_NOTE_REQUIRED, codes(validate_measurement_submission(payload, context())))
        payload = {
            "measurements": [{"field": "observed_phase_space.distance", "values": [no_preferred]}]
        }
        self.assertIn(PAPER_PREFERRED_REQUIRED, codes(validate_measurement_submission(payload, context())))
        payload = {
            "measurements": [{"field": "observed_phase_space.distance", "values": [bad_kind]}]
        }
        self.assertIn(SOURCE_KIND_INVALID, codes(validate_measurement_submission(payload, context())))

    def test_populated_component_requires_direct_evidence(self) -> None:
        value = measurement_value()
        value["direct_evidence"] = [value["direct_evidence"][0]]  # drop the error part
        payload = {
            "measurements": [{"field": "observed_phase_space.distance", "values": [value]}]
        }
        issues = validate_measurement_submission(payload, context())
        self.assertIn(DIRECT_EVIDENCE_MISSING, codes(issues))

    def test_citation_and_bibkey_resolve_verbatim(self) -> None:
        wrong_citation = prior_adopted_value(
            source={
                "kind": "prior_work",
                "paper_visible_citation": "Jones et al. (1999)",
                "bibkey": "smith2020",
                "citation_evidence": [
                    {"kind": "text", "path": "main.tex", "start_line": 5, "end_line": 5}
                ],
            }
        )
        payload = {
            "measurements": [{"field": "observed_phase_space.distance", "values": [wrong_citation]}]
        }
        issues = validate_measurement_submission(payload, context())
        self.assertIn(CITATION_NOT_VERBATIM, codes(issues))

        wrong_bibkey = prior_adopted_value(
            source={
                "kind": "prior_work",
                "paper_visible_citation": "Smith et al. (2020)",
                "bibkey": "jones1999",
                "citation_evidence": [
                    {"kind": "text", "path": "main.tex", "start_line": 5, "end_line": 5}
                ],
            }
        )
        payload = {
            "measurements": [{"field": "observed_phase_space.distance", "values": [wrong_bibkey]}]
        }
        issues = validate_measurement_submission(payload, context())
        self.assertIn(BIBKEY_NOT_VERBATIM, codes(issues))

    def test_coordinate_invariants_reused(self) -> None:
        bad_coordinate = coordinate_value(
            coordinate_format="decimal_degrees",
        )
        payload = {
            "measurements": [{"field": "observed_phase_space.ra", "values": [bad_coordinate]}]
        }
        issues = validate_measurement_submission(payload, context())
        self.assertTrue(issues)
        joined = " ".join(issue.code for issue in issues)
        self.assertIn("coordinate_format_inconsistent", joined)

    def test_probability_unitless_form_ok(self) -> None:
        payload = {
            "measurements": [
                {"field": "bound_assessment.unbound_probability", "values": [probability_value()]}
            ]
        }
        issues = validate_measurement_submission(payload, context())
        self.assertEqual(issues, [])

    def test_hydration_adds_resolved_text_and_hash(self) -> None:
        hydrated = hydrate_measurement_submission(
            MEASUREMENT_SUBMISSION,
            context(),
            tex_sha256={"main.tex": "1" * 64},
        )
        group = next(
            item
            for item in hydrated["measurements"]
            if item["field"] == "observed_phase_space.distance"
        )
        first = group["values"][0]
        direct = first["direct_evidence"][0]["source"]
        self.assertEqual(direct["source_sha256"], "1" * 64)
        self.assertIn("resolved_text", direct)
        self.assertIn("8.2", direct["resolved_text"])
        citation = group["values"][2]["source"]["citation_evidence"][0]
        self.assertIn("Smith et al. (2020)", citation["resolved_text"])
        self.assertEqual(citation["source_sha256"], "1" * 64)


if __name__ == "__main__":
    unittest.main()
