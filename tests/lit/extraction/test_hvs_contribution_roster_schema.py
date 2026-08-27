"""Submission-schema and prompt contract tests for the contribution roster."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from stella.lit.extraction.roster_prompts import (
    build_contribution_roster_prompts,
)
from stella.lit.extraction.submission_schema import (
    SUBMIT_CONTRIBUTION_ROSTER,
    build_contribution_roster_submission_schema,
)

ROOT = Path(__file__).resolve().parents[3]
VIEW = "main.tex\n1|\\documentclass{article}\n2|\\begin{document}\n3|manuscript\n"


class ContributionRosterSchemaTest(unittest.TestCase):
    def test_top_level_contract(self) -> None:
        schema = build_contribution_roster_submission_schema(["main.tex"])
        self.assertEqual(SUBMIT_CONTRIBUTION_ROSTER, "submit_contribution_roster")
        self.assertFalse(schema.get("additionalProperties"))
        self.assertEqual(
            set(schema["required"]),
            {"object_contributions", "reviewed_exclusions", "range_groups"},
        )
        properties = schema["properties"]
        self.assertEqual(
            set(properties), {"object_contributions", "reviewed_exclusions", "range_groups"}
        )

    def test_contribution_item_contract(self) -> None:
        schema = build_contribution_roster_submission_schema(["main.tex"])
        item = schema["properties"]["object_contributions"]["items"]
        self.assertFalse(item.get("additionalProperties"))
        self.assertEqual(
            set(item["required"]),
            {
                "identifiers",
                "contribution_type",
                "contribution_summary",
                "contribution_evidence",
                "paper_boundness",
            },
        )
        props = item["properties"]
        self.assertEqual(
            props["contribution_type"]["enum"],
            ["candidates_found", "follow_up"],
        )
        self.assertEqual(props["contribution_summary"].get("minLength"), 1)
        self.assertEqual(props["contribution_evidence"].get("minItems"), 1)
        boundness = props["paper_boundness"]
        self.assertEqual(
            set(boundness["required"]), {"status", "evidence"}
        )
        self.assertEqual(
            boundness["properties"]["status"]["enum"],
            [
                "unbound",
                "possibly_unbound",
                "bound",
                "no_overall_conclusion",
                "not_assessed",
            ],
        )
        identifier = props["identifiers"]["items"]
        self.assertEqual(
            set(identifier["required"]), {"value", "source_refs"}
        )
        self.assertEqual(identifier["properties"]["value"].get("minLength"), 1)
        self.assertEqual(identifier["properties"]["source_refs"].get("minItems"), 1)
        exclusion = schema["properties"]["reviewed_exclusions"]["items"]
        self.assertEqual(set(exclusion["required"]), {"reason", "source_refs"})
        self.assertEqual(exclusion["properties"]["source_refs"].get("minItems"), 1)

    def test_range_group_contract_is_transient_contribution_shape(self) -> None:
        schema = build_contribution_roster_submission_schema(["main.tex"])
        group = schema["properties"]["range_groups"]["items"]
        self.assertFalse(group.get("additionalProperties"))
        self.assertEqual(
            set(group["required"]),
            {
                "range_notation",
                "source_refs",
                "contribution_type",
                "contribution_summary",
                "contribution_evidence",
                "paper_boundness",
            },
        )
        self.assertEqual(group["properties"]["range_notation"].get("minLength"), 1)
        self.assertEqual(group["properties"]["source_refs"].get("minItems"), 1)
        self.assertNotIn("identifiers", group["properties"])

    def test_source_ref_path_enum_is_runtime_value(self) -> None:
        schema = build_contribution_roster_submission_schema(["main.tex", "extra.tex"])
        ref = schema["properties"]["object_contributions"]["items"]["properties"][
            "identifiers"
        ]["items"]["properties"]["source_refs"]["items"]
        self.assertEqual(ref["properties"]["path"]["enum"], ["main.tex", "extra.tex"])


class ContributionRosterPromptTest(unittest.TestCase):
    def test_prompts_render_contribution_rules_not_v6_roster_rules(self) -> None:
        prompts = build_contribution_roster_prompts(
            ROOT, VIEW, mode="tool_submission", schema=None
        )
        system = prompts["system"]
        self.assertIn("[hvs.contrib.follow_up]", system)
        self.assertIn("[hvs.contrib.paper_boundness]", system)
        self.assertIn("[hvs.contrib.deterministic_range_groups]", system)
        self.assertNotIn("HVS-related object contributions", system)
        # Roster-stage prompts exclude the measurement-stage rules.
        self.assertNotIn("[hvs.contrib.grouped_multivalue]", system)
        self.assertNotIn("[hvs.contrib.paper_preferred]", system)
        # V6 roster rules never enter the contribution prompt.
        self.assertNotIn("hvs.roster.final_treatment", system)
        self.assertNotIn("hvs.roster.prior_reassessment", system)
        self.assertNotIn("fewest additional model assumptions", system)
        self.assertIn(SUBMIT_CONTRIBUTION_ROSTER, system)
        self.assertIn(VIEW, prompts["user"])
        self.assertEqual(len(prompts["system_sha256"]), 64)
        self.assertEqual(len(prompts["user_sha256"]), 64)

    def test_json_object_mode_embeds_schema(self) -> None:
        schema = build_contribution_roster_submission_schema(["main.tex"])
        prompts = build_contribution_roster_prompts(
            ROOT, VIEW, mode="json_object", schema=schema
        )
        self.assertNotIn(SUBMIT_CONTRIBUTION_ROSTER, prompts["system"].split("===== SUBMISSION =====")[0])
        self.assertIn("JSON schema", prompts["user"])
        self.assertIn(json.dumps(schema, ensure_ascii=False, indent=2), prompts["user"])


if __name__ == "__main__":
    unittest.main()
