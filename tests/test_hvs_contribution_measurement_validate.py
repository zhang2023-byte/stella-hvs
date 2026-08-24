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
from stella.hvs_contribution_extraction.quantity_validate import (
    CONDITION_REQUIRED,
    DIRECT_EVIDENCE_MISSING,
    QUANTITY_DUPLICATE_GROUP,
    QUANTITY_NOT_IN_VOCABULARY,
    PAPER_PREFERRED_REQUIRED,
    PROBABILITY_REPRESENTATION_INVALID,
    SOURCE_KIND_INVALID,
    SOURCE_REQUIRED,
    VALUE_DUPLICATE,
    VALUES_EMPTY,
    hydrate_quantity_submission,
    validate_quantity_submission,
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
        issues = validate_quantity_submission(MEASUREMENT_SUBMISSION, context())
        self.assertEqual(issues, [])

    def test_field_vocabulary_and_duplicate_groups(self) -> None:
        payload = {
            "quantities": [
                {"quantity": "spectroscopy.teff", "values": [measurement_value()]},
            ]
        }
        issues = validate_quantity_submission(payload, context())
        self.assertIn(QUANTITY_NOT_IN_VOCABULARY, codes(issues))

        payload = {
            "quantities": [
                {"quantity": "observed_phase_space.distance", "values": [measurement_value()]},
                {"quantity": "observed_phase_space.distance", "values": [alternative_value()]},
            ]
        }
        issues = validate_quantity_submission(payload, context())
        self.assertIn(QUANTITY_DUPLICATE_GROUP, codes(issues))

        payload = {"quantities": [{"quantity": "observed_phase_space.distance", "values": []}]}
        issues = validate_quantity_submission(payload, context())
        self.assertIn(VALUES_EMPTY, codes(issues))

    def test_exact_duplicate_values_rejected_distinct_retained(self) -> None:
        payload = {
            "quantities": [
                {
                    "quantity": "observed_phase_space.distance",
                    "values": [measurement_value(), measurement_value()],
                }
            ]
        }
        issues = validate_quantity_submission(payload, context())
        self.assertIn(VALUE_DUPLICATE, codes(issues))

        payload = {
            "quantities": [
                {
                    "quantity": "observed_phase_space.distance",
                    "values": [
                        measurement_value(),
                        alternative_value(),
                        prior_adopted_value(),
                        superseded_value(),
                    ],
                }
            ]
        }
        issues = validate_quantity_submission(payload, context())
        self.assertEqual(issues, [])

    def test_required_per_value_fields(self) -> None:
        no_condition = measurement_value()
        del no_condition["condition"]
        no_preferred = measurement_value()
        del no_preferred["paper_preferred"]
        no_source = measurement_value()
        del no_source["source"]
        bad_kind = measurement_value(source="external")
        legacy_source = measurement_value(source={"kind": "this_paper"})
        for value in (no_condition, no_preferred, no_source, bad_kind, legacy_source):
            payload = {
                "quantities": [
                    {"quantity": "observed_phase_space.distance", "values": [value]}
                ]
            }
            issues = validate_quantity_submission(payload, context())
            self.assertTrue(issues, "expected at least one issue")

        payload = {
            "quantities": [{"quantity": "observed_phase_space.distance", "values": [no_condition]}]
        }
        self.assertIn(CONDITION_REQUIRED, codes(validate_quantity_submission(payload, context())))
        payload = {
            "quantities": [{"quantity": "observed_phase_space.distance", "values": [no_preferred]}]
        }
        self.assertIn(PAPER_PREFERRED_REQUIRED, codes(validate_quantity_submission(payload, context())))
        payload = {
            "quantities": [{"quantity": "observed_phase_space.distance", "values": [no_source]}]
        }
        self.assertIn(SOURCE_REQUIRED, codes(validate_quantity_submission(payload, context())))
        payload = {
            "quantities": [{"quantity": "observed_phase_space.distance", "values": [bad_kind]}]
        }
        self.assertIn(SOURCE_KIND_INVALID, codes(validate_quantity_submission(payload, context())))
        payload = {
            "quantities": [{"quantity": "observed_phase_space.distance", "values": [legacy_source]}]
        }
        self.assertIn(SOURCE_KIND_INVALID, codes(validate_quantity_submission(payload, context())))

    def test_populated_component_requires_direct_evidence(self) -> None:
        value = measurement_value()
        value["direct_evidence"] = [value["direct_evidence"][0]]  # drop the error part
        payload = {
            "quantities": [{"quantity": "observed_phase_space.distance", "values": [value]}]
        }
        issues = validate_quantity_submission(payload, context())
        self.assertIn(DIRECT_EVIDENCE_MISSING, codes(issues))

    def test_unstructured_source_note_needs_no_extra_citation_contract(self) -> None:
        value = prior_adopted_value(
            source_note="The paper attributes this value to Smith et al. (2020)."
        )
        payload = {
            "quantities": [
                {"quantity": "observed_phase_space.distance", "values": [value]}
            ]
        }
        self.assertEqual(validate_quantity_submission(payload, context()), [])

    def test_coordinate_invariants_reused(self) -> None:
        bad_coordinate = coordinate_value(
            coordinate_format="decimal_degrees",
        )
        payload = {
            "quantities": [{"quantity": "observed_phase_space.ra", "values": [bad_coordinate]}]
        }
        issues = validate_quantity_submission(payload, context())
        self.assertTrue(issues)
        joined = " ".join(issue.code for issue in issues)
        self.assertIn("coordinate_format_inconsistent", joined)

    def test_probability_fraction_and_percent_forms(self) -> None:
        percent_text = measurement_manuscript_text().replace("0.92", "92%")
        for value, validation_context in (
            (probability_value(), context()),
            (
                probability_value(
                    value="92",
                    unit="%",
                    direct_evidence=[
                        {
                            "part": "value",
                            "source": {
                                "kind": "text",
                                "path": "main.tex",
                                "start_line": 7,
                                "end_line": 7,
                                "raw_value": "92%",
                            },
                        }
                    ],
                ),
                context(percent_text),
            ),
        ):
            payload = {
                "quantities": [
                    {
                        "quantity": "bound_assessment.unbound_probability",
                        "values": [value],
                    }
                ]
            }
            with self.subTest(value=value["value"], unit=value["unit"]):
                self.assertEqual(
                    validate_quantity_submission(payload, validation_context), []
                )

        for value in (
            probability_value(value="92", unit=None),
            probability_value(unit="km/s"),
            probability_value(value="101", unit="%"),
        ):
            payload = {
                "quantities": [
                    {
                        "quantity": "bound_assessment.unbound_probability",
                        "values": [value],
                    }
                ]
            }
            self.assertIn(
                PROBABILITY_REPRESENTATION_INVALID,
                codes(validate_quantity_submission(payload, context())),
            )

    def test_hydration_adds_resolved_text_and_hash(self) -> None:
        hydrated = hydrate_quantity_submission(
            MEASUREMENT_SUBMISSION,
            context(),
            tex_sha256={"main.tex": "1" * 64},
        )
        group = next(
            item
            for item in hydrated["quantities"]
            if item["quantity"] == "observed_phase_space.distance"
        )
        first = group["values"][0]
        direct = first["direct_evidence"][0]["source"]
        self.assertEqual(direct["source_sha256"], "1" * 64)
        self.assertIn("resolved_text", direct)
        self.assertIn("8.2", direct["resolved_text"])
        prior = group["values"][2]
        self.assertEqual(prior["source"], "prior_work")
        self.assertIn("Smith et al. (2020)", prior["source_note"])


if __name__ == "__main__":
    unittest.main()
