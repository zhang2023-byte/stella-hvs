"""Contract tests for the contribution-first HVS schema models."""

from __future__ import annotations

import unittest
from typing import Any

from pydantic import ValidationError

from stella.benchmark.hvs_contribution_gold import HvsContributionGoldAnnotation
from stella.lit.hvs_contribution_models import (
    HVS_CONTRIBUTION_QUANTITIES,
    LiteratureHvsContributionsRecord,
    derived_identifier_display_name,
    validate_literature_hvs_contributions_document,
)
from stella.schema_registry import model_for, require_schema, schema_ref

CONTRIBUTION_SCHEMA_NAMES = (
    "literature_hvs_contributions",
    "literature_hvs_contributions.index",
    "hvs_contribution_catalog.object",
    "hvs_contribution_catalog.index",
    "hvs_dynamics.input_selection",
    "benchmark.hvs_contribution_annotation",
    "benchmark.hvs_contribution_form_draft",
    "benchmark.hvs_contribution_scorecard",
    "benchmark.hvs_contribution_scoring_details",
    "hvs_contribution_extraction.method_config",
    "hvs_contribution_extraction.prepared_input",
    "hvs_contribution_extraction.roster_proposal",
    "hvs_contribution_extraction.roster_final",
    "hvs_contribution_extraction.object_quantities",
    "hvs_contribution_extraction.paper_result",
    "hvs_contribution_extraction.run_summary",
)


def text_ref(path: str = "sources/main.tex", start: int = 10, end: int = 12) -> dict[str, Any]:
    return {
        "kind": "text",
        "path": path,
        "start_line": start,
        "end_line": end,
    }


def measurement_value(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "value": "8.2",
        "error": "0.3",
        "lower_error": None,
        "upper_error": None,
        "unit": "kpc",
        "limit_kind": "none",
        "range_lower": None,
        "range_upper": None,
        "coordinate_format": None,
        "condition": "Fiducial distance adopted for the orbit analysis.",
        "paper_preferred": True,
        "source": "this_paper",
        "direct_evidence": [
            {"part": "value", "source": {**text_ref(), "raw_value": "8.2"}},
            {"part": "error", "source": {**text_ref(), "raw_value": "0.3"}},
        ],
        "context_evidence": [text_ref()],
        "source_note": "",
    }
    value.update(overrides)
    return value


def prior_work_value(**overrides: Any) -> dict[str, Any]:
    value = measurement_value(
        value="7.9",
        error="0.4",
        paper_preferred=False,
        condition="Literature value adopted for comparison.",
        source="prior_work",
        source_note="The paper attributes this value to Smith et al. (2020).",
    )
    value.update(overrides)
    return value


def object_contribution(**overrides: Any) -> dict[str, Any]:
    contribution: dict[str, Any] = {
        "record_id": "obj-001",
        "identifiers": [{"value": "HVS 1", "evidence": [text_ref()]}],
        "contribution_type": "candidates_found",
        "contribution_summary": (
            "The paper's systematic search selects this object and retains it "
            "as an unbound candidate."
        ),
        "contribution_evidence": [text_ref()],
        "paper_boundness": {"status": "unbound", "evidence": [text_ref()]},
        "quantity_extraction_status": "complete",
        "quantities": [
            {
                "quantity": "observed_phase_space.distance",
                "values": [measurement_value(), prior_work_value()],
            }
        ],
        "failure": None,
    }
    contribution.update(overrides)
    return contribution


def contributions_document(**overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema": {"name": "literature_hvs_contributions", "version": 1},
        "generated_at": "2026-08-22T00:00:00Z",
        "paper": {"arxiv_id": "2601.00001"},
        "inputs": {"source_run_id": "run-0001", "paper_context_sha256": "0" * 64},
        "production": {
            "producer": "hvs_contribution_extraction",
            "method_fingerprint": "fp",
            "component_hashes": {},
        },
        "extraction": {"status": "complete", "roster_status": "contributions_found"},
        "reviewed_exclusions": [],
        "object_contributions": [object_contribution()],
    }
    document.update(overrides)
    return document


class ContributionRegistryTests(unittest.TestCase):
    def test_new_schema_names_resolve_to_version_one(self) -> None:
        for name in CONTRIBUTION_SCHEMA_NAMES:
            with self.subTest(name=name):
                self.assertEqual(schema_ref(name), {"name": name, "version": 1})

    def test_model_for_dispatches_contribution_models(self) -> None:
        self.assertIs(
            model_for("literature_hvs_contributions", 1),
            LiteratureHvsContributionsRecord,
        )
        self.assertIs(
            model_for("benchmark.hvs_contribution_annotation", 1),
            HvsContributionGoldAnnotation,
        )

    def test_unknown_version_fails(self) -> None:
        payload = contributions_document()
        payload["schema"]["version"] = 2
        with self.assertRaisesRegex(ValueError, "not readable"):
            require_schema(payload, "literature_hvs_contributions")
        with self.assertRaises(ValidationError):
            LiteratureHvsContributionsRecord.model_validate(payload)

    def test_extra_fields_fail(self) -> None:
        payload = contributions_document()
        payload["surprise"] = 1
        with self.assertRaises(ValidationError):
            LiteratureHvsContributionsRecord.model_validate(payload)
        contribution = object_contribution()
        contribution["scenarios"] = [{"name": "fiducial"}]
        document = contributions_document(object_contributions=[contribution])
        with self.assertRaises(ValidationError):
            LiteratureHvsContributionsRecord.model_validate(document)

    def test_document_validator_dispatches(self) -> None:
        record = validate_literature_hvs_contributions_document(contributions_document())
        self.assertEqual(record.extraction.roster_status, "contributions_found")


class ContributionContractTests(unittest.TestCase):
    def test_minimal_document_validates(self) -> None:
        record = LiteratureHvsContributionsRecord.model_validate(contributions_document())
        self.assertEqual(record.object_contributions[0].contribution_type, "candidates_found")

    def test_identifiers_are_flat_and_display_name_is_downstream_only(self) -> None:
        contribution = object_contribution(
            identifiers=[
                {"value": "A LONG IDENTIFIER", "evidence": [text_ref()]},
                {"value": "HVS 1", "evidence": [text_ref()]},
            ]
        )
        record = LiteratureHvsContributionsRecord.model_validate(
            contributions_document(object_contributions=[contribution])
        )
        self.assertEqual(
            derived_identifier_display_name(
                record.object_contributions[0].identifiers,
                fallback=record.object_contributions[0].record_id,
            ),
            "HVS 1",
        )
        contribution["display_name"] = "HVS 1"
        with self.assertRaises(ValidationError):
            LiteratureHvsContributionsRecord.model_validate(
                contributions_document(object_contributions=[contribution])
            )

    def test_measurement_field_vocabulary_is_frozen_at_nineteen(self) -> None:
        self.assertEqual(len(HVS_CONTRIBUTION_QUANTITIES), 19)
        self.assertEqual(len(set(HVS_CONTRIBUTION_QUANTITIES)), 19)
        expected = {
            "observed_phase_space.ra",
            "observed_phase_space.dec",
            "observed_phase_space.distance",
            "observed_phase_space.parallax",
            "observed_phase_space.proper_motion_ra",
            "observed_phase_space.proper_motion_dec",
            "observed_phase_space.radial_velocity",
            "derived_kinematics.galactocentric_x",
            "derived_kinematics.galactocentric_y",
            "derived_kinematics.galactocentric_z",
            "derived_kinematics.galactocentric_radius",
            "derived_kinematics.galactocentric_vx",
            "derived_kinematics.galactocentric_vy",
            "derived_kinematics.galactocentric_vz",
            "derived_kinematics.tangential_velocity",
            "derived_kinematics.galactocentric_tangential_velocity",
            "derived_kinematics.galactic_rest_frame_velocity",
            "bound_assessment.bound_probability",
            "bound_assessment.unbound_probability",
        }
        self.assertEqual(set(HVS_CONTRIBUTION_QUANTITIES), expected)

    def test_unknown_field_vocabulary_fails(self) -> None:
        group = {
            "quantity": "spectroscopy.teff",
            "values": [measurement_value()],
        }
        with self.assertRaises(ValidationError):
            LiteratureHvsContributionsRecord.model_validate(
                contributions_document(
                    object_contributions=[object_contribution(quantities=[group])]
                )
            )

    def test_invalid_contribution_type_fails(self) -> None:
        with self.assertRaises(ValidationError):
            LiteratureHvsContributionsRecord.model_validate(
                contributions_document(
                    object_contributions=[
                        object_contribution(contribution_type="introduced")
                    ]
                )
            )

    def test_summary_and_evidence_are_required(self) -> None:
        with self.assertRaises(ValidationError):
            LiteratureHvsContributionsRecord.model_validate(
                contributions_document(
                    object_contributions=[object_contribution(contribution_summary="  ")]
                )
            )

    def test_identifier_and_reviewed_exclusion_evidence_are_required(self) -> None:
        contribution = object_contribution()
        contribution["identifiers"][0]["evidence"] = []
        with self.assertRaises(ValidationError):
            LiteratureHvsContributionsRecord.model_validate(
                contributions_document(object_contributions=[contribution])
            )

        with self.assertRaises(ValidationError):
            LiteratureHvsContributionsRecord.model_validate(
                contributions_document(
                    reviewed_exclusions=[
                        {"reason": "A meaningful near miss.", "evidence": []}
                    ]
                )
            )

    def test_probability_accepts_fractions_and_explicit_percents(self) -> None:
        for value, unit in (("0.92", None), ("92", "%")):
            with self.subTest(value=value, unit=unit):
                probability = measurement_value(
                    value=value,
                    error=None,
                    unit=unit,
                    direct_evidence=[
                        {
                            "part": "value",
                            "source": {
                                **text_ref(),
                                "raw_value": f"{value}{unit or ''}",
                            },
                        }
                    ],
                )
                record = LiteratureHvsContributionsRecord.model_validate(
                    contributions_document(
                        object_contributions=[
                            object_contribution(
                                quantities=[
                                    {
                                        "quantity": "bound_assessment.unbound_probability",
                                        "values": [probability],
                                    }
                                ]
                            )
                        ]
                    )
                )
                self.assertEqual(
                    record.object_contributions[0].quantities[0].values[0].value,
                    value,
                )

        for value, unit in (("92", None), ("0.92", "km/s"), ("101", "%")):
            with self.subTest(invalid_value=value, invalid_unit=unit):
                probability = measurement_value(
                    value=value,
                    error=None,
                    unit=unit,
                    direct_evidence=[
                        {
                            "part": "value",
                            "source": {**text_ref(), "raw_value": value},
                        }
                    ],
                )
                with self.assertRaises(ValidationError):
                    LiteratureHvsContributionsRecord.model_validate(
                        contributions_document(
                            object_contributions=[
                                object_contribution(
                                    quantities=[
                                        {
                                            "quantity": "bound_assessment.unbound_probability",
                                            "values": [probability],
                                        }
                                    ]
                                )
                            ]
                        )
                    )
        with self.assertRaises(ValidationError):
            LiteratureHvsContributionsRecord.model_validate(
                contributions_document(
                    object_contributions=[object_contribution(contribution_evidence=[])]
                )
            )

    def test_candidates_found_rejects_bound_and_not_assessed(self) -> None:
        for status in ("bound", "not_assessed"):
            with self.subTest(status=status):
                with self.assertRaises(ValidationError):
                    LiteratureHvsContributionsRecord.model_validate(
                        contributions_document(
                            object_contributions=[
                                object_contribution(
                                    paper_boundness={"status": status, "evidence": [text_ref()]}
                                )
                            ]
                        )
                    )

    def test_follow_up_accepts_all_five_statuses(self) -> None:
        for status in (
            "unbound",
            "possibly_unbound",
            "bound",
            "no_overall_conclusion",
            "not_assessed",
        ):
            with self.subTest(status=status):
                paper_boundness = {"status": status, "evidence": [text_ref()]}
                if status == "not_assessed":
                    paper_boundness["evidence"] = []
                record = LiteratureHvsContributionsRecord.model_validate(
                    contributions_document(
                        object_contributions=[
                            object_contribution(
                                contribution_type="follow_up",
                                paper_boundness=paper_boundness,
                            )
                        ]
                    )
                )
                self.assertEqual(
                    record.object_contributions[0].paper_boundness.status, status
                )

    def test_assessed_boundness_requires_evidence(self) -> None:
        for status in ("unbound", "possibly_unbound", "bound", "no_overall_conclusion"):
            with self.subTest(status=status):
                with self.assertRaises(ValidationError):
                    LiteratureHvsContributionsRecord.model_validate(
                        contributions_document(
                            object_contributions=[
                                object_contribution(
                                    contribution_type="follow_up",
                                    paper_boundness={"status": status, "evidence": []},
                                )
                            ]
                        )
                    )

    def test_duplicate_field_group_fails(self) -> None:
        group = {
            "quantity": "observed_phase_space.distance",
            "values": [measurement_value()],
        }
        other = {
            "quantity": "observed_phase_space.distance",
            "values": [prior_work_value()],
        }
        with self.assertRaises(ValidationError):
            LiteratureHvsContributionsRecord.model_validate(
                contributions_document(
                    object_contributions=[
                        object_contribution(quantities=[group, other])
                    ]
                )
            )

    def test_empty_values_list_fails(self) -> None:
        group = {"quantity": "observed_phase_space.distance", "values": []}
        with self.assertRaises(ValidationError):
            LiteratureHvsContributionsRecord.model_validate(
                contributions_document(
                    object_contributions=[object_contribution(quantities=[group])]
                )
            )

    def test_exact_duplicate_values_fail(self) -> None:
        with self.assertRaises(ValidationError):
            LiteratureHvsContributionsRecord.model_validate(
                contributions_document(
                    object_contributions=[
                        object_contribution(
                            quantities=[
                                {
                                    "quantity": "observed_phase_space.distance",
                                    "values": [measurement_value(), measurement_value()],
                                }
                            ]
                        )
                    ]
                )
            )

    def test_distinct_conditions_keep_both_values(self) -> None:
        variant = measurement_value(
            value="8.6",
            condition="Distance under the alternative potential.",
            paper_preferred=None,
        )
        record = LiteratureHvsContributionsRecord.model_validate(
            contributions_document(
                object_contributions=[
                    object_contribution(
                        quantities=[
                            {
                                "quantity": "observed_phase_space.distance",
                                "values": [measurement_value(), prior_work_value(), variant],
                            }
                        ]
                    )
                ]
            )
        )
        self.assertEqual(
            len(record.object_contributions[0].quantities[0].values), 3
        )

    def test_multiple_preferred_conditional_values_allowed(self) -> None:
        preferred_a = measurement_value(
            value="8.2", condition="Fiducial potential A.", paper_preferred=True
        )
        preferred_b = measurement_value(
            value="8.6", condition="Fiducial potential B.", paper_preferred=True
        )
        record = LiteratureHvsContributionsRecord.model_validate(
            contributions_document(
                object_contributions=[
                    object_contribution(
                        quantities=[
                            {
                                "quantity": "observed_phase_space.distance",
                                "values": [preferred_a, preferred_b],
                            }
                        ]
                    )
                ]
            )
        )
        values = record.object_contributions[0].quantities[0].values
        self.assertEqual([value.paper_preferred for value in values], [True, True])

    def test_paper_preferred_is_required_tri_state(self) -> None:
        value = measurement_value()
        del value["paper_preferred"]
        with self.assertRaises(ValidationError):
            LiteratureHvsContributionsRecord.model_validate(
                contributions_document(
                    object_contributions=[
                        object_contribution(
                            quantities=[
                                {
                                    "quantity": "observed_phase_space.distance",
                                    "values": [value],
                                }
                            ]
                        )
                    ]
                )
            )
        for allowed in (True, False, None):
            with self.subTest(paper_preferred=allowed):
                record = LiteratureHvsContributionsRecord.model_validate(
                    contributions_document(
                        object_contributions=[
                            object_contribution(
                                quantities=[
                                    {
                                        "quantity": "observed_phase_space.distance",
                                        "values": [
                                            measurement_value(paper_preferred=allowed)
                                        ],
                                    }
                                ]
                            )
                        ]
                    )
                )
                self.assertIs(
                    record.object_contributions[0].quantities[0].values[0].paper_preferred,
                    allowed,
                )
        with self.assertRaises(ValidationError):
            LiteratureHvsContributionsRecord.model_validate(
                contributions_document(
                    object_contributions=[
                        object_contribution(
                            quantities=[
                                {
                                    "quantity": "observed_phase_space.distance",
                                    "values": [measurement_value(paper_preferred="maybe")],
                                }
                            ]
                        )
                    ]
                )
            )

    def test_source_vocabulary(self) -> None:
        with self.assertRaises(ValidationError):
            LiteratureHvsContributionsRecord.model_validate(
                contributions_document(
                    object_contributions=[
                        object_contribution(
                            quantities=[
                                {
                                    "quantity": "observed_phase_space.distance",
                                    "values": [measurement_value(source="external")],
                                }
                            ]
                        )
                    ]
                )
            )

    def test_measurements_require_numeric_text_and_complete_direct_evidence(self) -> None:
        for invalid in (
            measurement_value(value="not-a-number"),
            measurement_value(direct_evidence=[]),
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValidationError):
                    LiteratureHvsContributionsRecord.model_validate(
                        contributions_document(
                            object_contributions=[
                                object_contribution(
                                    quantities=[
                                        {
                                            "quantity": "observed_phase_space.distance",
                                            "values": [invalid],
                                        }
                                    ]
                                )
                            ]
                        )
                    )

    def test_legacy_source_object_is_rejected(self) -> None:
        measurement = prior_work_value(source={"kind": "prior_work"})
        with self.assertRaises(ValidationError):
            LiteratureHvsContributionsRecord.model_validate(
                contributions_document(
                    object_contributions=[
                        object_contribution(
                            quantities=[
                                {
                                    "quantity": "observed_phase_space.distance",
                                    "values": [measurement],
                                }
                            ]
                        )
                    ]
                )
            )

    def test_measurement_ids_and_scenarios_are_rejected(self) -> None:
        for extra_key, extra_value in (
            ("measurement_id", "m-01"),
            ("scenario_ref", "scenario-fiducial"),
            ("scenario", "fiducial"),
        ):
            with self.subTest(extra=extra_key):
                value = measurement_value()
                value[extra_key] = extra_value
                with self.assertRaises(ValidationError):
                    LiteratureHvsContributionsRecord.model_validate(
                        contributions_document(
                            object_contributions=[
                                object_contribution(
                                    quantities=[
                                        {
                                            "quantity": "observed_phase_space.distance",
                                            "values": [value],
                                        }
                                    ]
                                )
                            ]
                        )
                    )

    def test_range_limit_semantics(self) -> None:
        with self.assertRaises(ValidationError):
            LiteratureHvsContributionsRecord.model_validate(
                contributions_document(
                    object_contributions=[
                        object_contribution(
                            quantities=[
                                {
                                    "quantity": "observed_phase_space.distance",
                                    "values": [
                                        measurement_value(
                                            limit_kind="range",
                                            value="8.2",
                                            range_lower="8.0",
                                            range_upper="8.4",
                                        )
                                    ],
                                }
                            ]
                        )
                    ]
                )
            )
        with self.assertRaises(ValidationError):
            LiteratureHvsContributionsRecord.model_validate(
                contributions_document(
                    object_contributions=[
                        object_contribution(
                            quantities=[
                                {
                                    "quantity": "observed_phase_space.distance",
                                    "values": [
                                        measurement_value(
                                            limit_kind="range",
                                            value=None,
                                            range_lower="8.0",
                                            range_upper=None,
                                        )
                                    ],
                                }
                            ]
                        )
                    ]
                )
            )
        record = LiteratureHvsContributionsRecord.model_validate(
            contributions_document(
                object_contributions=[
                    object_contribution(
                        quantities=[
                            {
                                "quantity": "observed_phase_space.distance",
                                "values": [
                                    measurement_value(
                                        limit_kind="range",
                                        value=None,
                                        error=None,
                                        range_lower="8.0",
                                        range_upper="8.4",
                                        condition="90% confidence interval.",
                                        paper_preferred=None,
                                        direct_evidence=[
                                            {
                                                "part": "range_lower",
                                                "source": {
                                                    **text_ref(),
                                                    "raw_value": "8.0",
                                                },
                                            },
                                            {
                                                "part": "range_upper",
                                                "source": {
                                                    **text_ref(),
                                                    "raw_value": "8.4",
                                                },
                                            },
                                        ],
                                    )
                                ],
                            }
                        ]
                    )
                ]
            )
        )
        self.assertEqual(
            record.object_contributions[0].quantities[0].values[0].limit_kind, "range"
        )

    def test_quantity_failure_must_match_status(self) -> None:
        failed = object_contribution(
            quantity_extraction_status="failed",
            quantities=[],
            failure={"code": "transport_failure", "detail": "transport exhausted retries"},
        )
        record = LiteratureHvsContributionsRecord.model_validate(
            contributions_document(object_contributions=[failed])
        )
        self.assertIsNotNone(record.object_contributions[0].failure)

        with self.assertRaises(ValidationError):
            LiteratureHvsContributionsRecord.model_validate(
                contributions_document(
                    object_contributions=[
                        object_contribution(
                            quantity_extraction_status="failed",
                            quantities=[],
                            failure=None,
                        )
                    ]
                )
            )
        with self.assertRaises(ValidationError):
            LiteratureHvsContributionsRecord.model_validate(
                contributions_document(
                    object_contributions=[
                        object_contribution(
                            quantity_extraction_status="complete",
                            failure={"code": "terminal", "detail": "x"},
                        )
                    ]
                )
            )
        with self.assertRaises(ValidationError):
            LiteratureHvsContributionsRecord.model_validate(
                contributions_document(
                    object_contributions=[
                        object_contribution(
                            quantity_extraction_status="failed",
                            quantities=[
                                {
                                    "quantity": "observed_phase_space.distance",
                                    "values": [measurement_value()],
                                }
                            ],
                            failure={"code": "terminal", "detail": "x"},
                        )
                    ]
                )
            )

    def test_complete_with_empty_measurements_is_valid(self) -> None:
        record = LiteratureHvsContributionsRecord.model_validate(
            contributions_document(
                object_contributions=[
                    object_contribution(
                        contribution_type="follow_up",
                        paper_boundness={"status": "not_assessed", "evidence": []},
                        quantities=[],
                    )
                ]
            )
        )
        self.assertEqual(record.object_contributions[0].quantities, [])

    def test_roster_status_consistency(self) -> None:
        with self.assertRaises(ValidationError):
            LiteratureHvsContributionsRecord.model_validate(
                contributions_document(
                    extraction={"status": "complete", "roster_status": "no_contributions"}
                )
            )
        with self.assertRaises(ValidationError):
            LiteratureHvsContributionsRecord.model_validate(
                contributions_document(
                    extraction={"status": "complete", "roster_status": None},
                    object_contributions=[],
                )
            )
        record = LiteratureHvsContributionsRecord.model_validate(
            contributions_document(
                extraction={"status": "complete", "roster_status": "no_contributions"},
                object_contributions=[],
            )
        )
        self.assertEqual(record.object_contributions, [])

    def test_duplicate_record_ids_fail(self) -> None:
        with self.assertRaises(ValidationError):
            LiteratureHvsContributionsRecord.model_validate(
                contributions_document(
                    object_contributions=[
                        object_contribution(),
                        object_contribution(),
                    ]
                )
            )


if __name__ == "__main__":
    unittest.main()
