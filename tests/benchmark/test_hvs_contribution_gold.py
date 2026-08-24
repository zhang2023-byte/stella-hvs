"""Contribution gold schema, canary twin, and tooling guard tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml
from pydantic import ValidationError

from stella.benchmark.hvs_contribution_gold import (
    HvsContributionGoldAnnotation,
    contribution_annotation_canary,
    contribution_gold_json_document,
    lint_contribution_annotation,
    upgrade_contribution_annotation,
)

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_PATH = ROOT / "benchmark/templates/hvs_contribution_annotation_example.yaml"
TEMPLATE_PATH = ROOT / "benchmark/templates/hvs_contribution_annotation_template.yaml"


def fictional_annotation_payload(**overrides) -> dict:
    payload = {
        "schema": {"name": "benchmark.hvs_contribution_annotation", "version": 1},
        "arxiv_id": "2601.00001",
        "annotator": "expert-a",
        "annotated_at": "2026-08-22",
        "guideline_version": "abc1234",
        "evidence_basis": "pdf",
        "annotation_process": {
            "protocol": "contribution_migration_ai_assisted_v1",
            "preannotation_agent": "codex",
            "preannotation_model": "pre-model",
            "reconciliation_agent": "codex",
            "reconciliation_model": "reconcile-model",
            "expert_review_scope": "paper_level",
        },
        "status": "contributions_found",
        "contributions": [
            {
                "identifiers": [
                    {"value": "FIC-1", "evidence": [{"location": "Section 4.1"}]}
                ],
                "contribution_type": "candidates_found",
                "contribution_summary": "The paper's search retains FIC-1 as an unbound candidate.",
                "contribution_evidence": [{"location": "Section 4.1"}],
                "paper_boundness": {
                    "status": "unbound",
                    "evidence": [{"location": "Section 5"}],
                },
                "quantities": [
                    {
                        "quantity": "observed_phase_space.distance",
                        "values": [
                            {
                                "value": "8.2",
                                "error": "0.3",
                                "unit": "kpc",
                                "limit_kind": "none",
                                "condition": "Fiducial model distance.",
                                "paper_preferred": True,
                                "source": "this_paper",
                                "evidence": [{"location": "Table 2"}],
                            }
                        ],
                    }
                ],
            }
        ],
        "reviewed_exclusions": [
            {"reason": "FIC-99 is background only.", "evidence": [{"location": "Intro"}]}
        ],
    }
    payload.update(overrides)
    return payload


class ContributionGoldSchemaTest(unittest.TestCase):
    def test_migration_process_metadata_is_required_and_complete(self) -> None:
        payload = fictional_annotation_payload()
        del payload["annotation_process"]
        with self.assertRaises(ValidationError):
            HvsContributionGoldAnnotation.model_validate(payload)

        payload = fictional_annotation_payload()
        payload["annotation_process"]["preannotation_model"] = ""
        with self.assertRaises(ValidationError):
            HvsContributionGoldAnnotation.model_validate(payload)

        payload = fictional_annotation_payload()
        payload["annotation_process"]["expert_review_scope"] = "item_level"
        with self.assertRaises(ValidationError):
            HvsContributionGoldAnnotation.model_validate(payload)

    def test_fictional_example_template_validates(self) -> None:
        payload = yaml.safe_load(EXAMPLE_PATH.read_text(encoding="utf-8"))
        annotation = HvsContributionGoldAnnotation.model_validate(payload)
        self.assertEqual(annotation.status, "contributions_found")
        self.assertEqual(len(annotation.contributions), 2)
        self.assertEqual(annotation.contributions[1].paper_boundness.status, "not_assessed")

    def test_template_yaml_is_a_mapping_with_schema_header(self) -> None:
        payload = yaml.safe_load(TEMPLATE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            payload["schema"],
            {"name": "benchmark.hvs_contribution_annotation", "version": 1},
        )

    def test_legacy_split_identity_fields_are_rejected(self) -> None:
        payload = fictional_annotation_payload()
        contribution = payload["contributions"][0]
        contribution["paper_candidate_id"] = "FIC-1"
        with self.assertRaises(ValidationError):
            HvsContributionGoldAnnotation.model_validate(payload)

    def test_canary_is_deterministic_and_content_sensitive(self) -> None:
        annotation = HvsContributionGoldAnnotation.model_validate(
            fictional_annotation_payload()
        )
        first = contribution_gold_json_document(annotation)
        second = contribution_gold_json_document(annotation)
        self.assertEqual(first["canary"], second["canary"])
        self.assertTrue(first["canary"].startswith("stella-contribution-gold-canary-v0.1-"))
        changed_payload = fictional_annotation_payload()
        changed_payload["annotation_process"]["process_note"] = "different"
        changed = contribution_gold_json_document(
            HvsContributionGoldAnnotation.model_validate(changed_payload)
        )
        self.assertNotEqual(first["canary"], changed["canary"])
        # Canary verification: recomputation from the twin without the canary matches.
        twin = dict(first)
        canary = twin.pop("canary")
        self.assertEqual(contribution_annotation_canary(twin), canary)

    def test_upgrade_annotation_returns_twin(self) -> None:
        document = upgrade_contribution_annotation(fictional_annotation_payload())
        self.assertEqual(document["arxiv_id"], "2601.00001")
        self.assertIn("canary", document)

    def test_paper_preferred_is_required_and_explicit_null_survives_twin(self) -> None:
        payload = fictional_annotation_payload()
        value = payload["contributions"][0]["quantities"][0]["values"][0]
        value["paper_preferred"] = None
        document = upgrade_contribution_annotation(payload)
        twin_value = document["contributions"][0]["quantities"][0]["values"][0]
        self.assertIn("paper_preferred", twin_value)
        self.assertIsNone(twin_value["paper_preferred"])

        del value["paper_preferred"]
        with self.assertRaises(ValidationError):
            HvsContributionGoldAnnotation.model_validate(payload)

    def test_legacy_source_object_is_rejected(self) -> None:
        payload = fictional_annotation_payload()
        payload["contributions"][0]["quantities"][0]["values"][0]["source"] = {
            "kind": "this_paper"
        }
        with self.assertRaises(ValidationError):
            HvsContributionGoldAnnotation.model_validate(payload)

    def test_gold_measurements_reject_non_numeric_or_unsupported_values(self) -> None:
        for mutation in ("non_numeric", "missing_evidence"):
            payload = fictional_annotation_payload()
            value = payload["contributions"][0]["quantities"][0]["values"][0]
            if mutation == "non_numeric":
                value["value"] = "not-a-number"
            else:
                value["evidence"] = []
            with self.subTest(mutation=mutation):
                with self.assertRaises(ValidationError):
                    HvsContributionGoldAnnotation.model_validate(payload)

    def test_probability_formats_and_not_assessed_lint(self) -> None:
        payload = fictional_annotation_payload()
        for value, unit in (("0.92", ""), ("92", "%")):
            candidate = fictional_annotation_payload()
            candidate["contributions"][0]["quantities"].append(
                {
                    "quantity": "bound_assessment.unbound_probability",
                    "values": [
                        {
                            "value": value,
                            "unit": unit,
                            "limit_kind": "none",
                            "condition": "",
                            "paper_preferred": None,
                            "source": "this_paper",
                            "evidence": [{"location": "Table 3"}],
                        }
                    ],
                }
            )
            with self.subTest(value=value, unit=unit):
                HvsContributionGoldAnnotation.model_validate(candidate)

        for value, unit in (("92", ""), ("0.92", "km/s"), ("101", "%")):
            candidate = fictional_annotation_payload()
            candidate["contributions"][0]["quantities"].append(
                {
                    "quantity": "bound_assessment.unbound_probability",
                    "values": [
                        {
                            "value": value,
                            "unit": unit,
                            "limit_kind": "none",
                            "condition": "",
                            "paper_preferred": None,
                            "source": "this_paper",
                            "evidence": [{"location": "Table 3"}],
                        }
                    ],
                }
            )
            with self.subTest(invalid_value=value, invalid_unit=unit):
                with self.assertRaises(ValidationError):
                    HvsContributionGoldAnnotation.model_validate(candidate)

        payload["contributions"].append(
            {
                "identifiers": [
                    {"value": "FIC-7", "evidence": [{"location": "Section 6"}]}
                ],
                "contribution_type": "follow_up",
                "contribution_summary": "New spectroscopy only.",
                "contribution_evidence": [{"location": "Section 6"}],
                "paper_boundness": {"status": "not_assessed", "evidence": []},
            }
        )
        annotation = HvsContributionGoldAnnotation.model_validate(payload)
        warnings = lint_contribution_annotation(annotation)
        self.assertTrue(any("no new boundness" in item for item in warnings))

    def test_reviewed_exclusion_requires_evidence(self) -> None:
        payload = fictional_annotation_payload()
        payload["reviewed_exclusions"][0]["evidence"] = []
        with self.assertRaises(ValidationError):
            HvsContributionGoldAnnotation.model_validate(payload)

    def test_no_migrate_script_exists(self) -> None:
        self.assertFalse(
            (ROOT / "scripts/migrate_hvs_contribution_gold.py").exists(),
            "mechanical V6-to-contribution gold migration is forbidden",
        )


if __name__ == "__main__":
    unittest.main()
