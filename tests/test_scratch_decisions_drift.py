"""Anti-drift guard: scratch code must match the frozen decisions verbatim.

Compares the canonical scratch rule text (D054) and the frozen prompt
templates (D009, D024 as amended by D052, D033) in
``benchmark/hvs_extraction_scratch_decisions.yaml`` against the implemented
constants, so any transcription drift fails loudly instead of shipping.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import yaml

from stella.benchmark.scratch import field_prompts, roster_prompts
from stella.lit.extraction_rules import load_rule_catalog


ROOT = Path(__file__).resolve().parents[1]
DECISIONS = yaml.safe_load(
    (ROOT / "benchmark/hvs_extraction_scratch_decisions.yaml").read_text(
        encoding="utf-8"
    )
)
APPROVED = {item["id"]: item for item in DECISIONS["approved_decisions"]}


def norm(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().split("\n"))


class FrozenRuleTextTest(unittest.TestCase):
    def test_all_23_scratch_rules_match_approved_amendments(self) -> None:
        catalog = load_rule_catalog(ROOT)
        exact_rules = APPROVED["D054"]["exact_rules"]
        amendments = [
            APPROVED["D059"]["rule_amendments"],
            APPROVED["D065"]["rule_amendments"],
        ]
        self.assertEqual(len(exact_rules), 23)
        for frozen in exact_rules:
            with self.subTest(rule_id=frozen["id"]):
                rule = catalog.rules[frozen["id"]]
                self.assertEqual(rule.title, frozen["title"].strip())
                expected = frozen["text"]
                for amendment_set in amendments:
                    amendment = amendment_set.get(frozen["id"])
                    if amendment:
                        self.assertIn(amendment["replace"], expected)
                        expected = expected.replace(
                            amendment["replace"], amendment["with"]
                        )
                self.assertEqual(norm(rule.text), norm(expected))


class FrozenPromptTemplateTest(unittest.TestCase):
    def test_extractor_templates_match_d009(self) -> None:
        decision = APPROVED["D009"]
        self.assertEqual(
            norm(roster_prompts.EXTRACTOR_SYSTEM_TEMPLATE),
            norm(decision["system_prompt_template"]),
        )
        self.assertEqual(
            norm(roster_prompts.EXTRACTOR_USER_TEMPLATE),
            norm(decision["user_message_template"]),
        )

    def test_adjudicator_templates_match_d024_as_amended_by_d052(self) -> None:
        decision = APPROVED["D024"]
        # D052 replaces one sentence; in the D024 template it is line-wrapped,
        # so apply the amendment on the wrapped form and prove it happened.
        wrapped_old = (
            "Read the complete manuscript and the three anonymous "
            "candidate-roster proposals\nsupplied in the user message."
        )
        wrapped_new = (
            "Read the complete manuscript and the anonymous "
            "candidate-roster proposals\nsupplied in the user message."
        )
        template = decision["system_prompt_template"]
        self.assertIn(wrapped_old, template)
        expected_system = template.replace(wrapped_old, wrapped_new)
        self.assertEqual(
            norm(roster_prompts.ADJUDICATOR_SYSTEM_TEMPLATE),
            norm(expected_system),
        )

    def test_adjudicator_user_rendering_matches_d024_and_d052(self) -> None:
        """Three valid proposals render D024's exact template; two render A/B only (D052)."""

        template = APPROVED["D024"]["user_message_template"]
        proposals = [("Proposal A", {"x": 1}), ("Proposal B", {"y": 2}), ("Proposal C", {"z": 3})]
        built = roster_prompts.build_adjudicator_prompts(
            ROOT, "MANUSCRIPT", proposals
        )
        expected = template.replace(
            "<COMPLETE_MINIMALLY_CLEANED_TEX_FILE_BLOCKS>", "MANUSCRIPT"
        )
        for _label, payload in proposals:
            body = json.dumps(payload, ensure_ascii=False, indent=2)
            expected = expected.replace("<VALIDATED_EXTRACTOR_ROSTER>", body, 1)
        self.assertNotIn("<VALIDATED_EXTRACTOR_ROSTER>", expected)
        self.assertEqual(norm(built["user"]), norm(expected))
        # D052 count neutrality: two valid proposals leave no third placeholder.
        built_two = roster_prompts.build_adjudicator_prompts(
            ROOT, "MANUSCRIPT", proposals[:2]
        )
        self.assertIn("Proposal A", built_two["user"])
        self.assertIn("Proposal B", built_two["user"])
        self.assertNotIn("Proposal C", built_two["user"])

    def test_field_system_template_matches_d033(self) -> None:
        decision = APPROVED["D033"]
        self.assertEqual(
            norm(field_prompts.FIELD_SYSTEM_TEMPLATE),
            norm(decision["system_prompt_template"]),
        )

    def test_extractor_json_object_variant_matches_d057(self) -> None:
        """D057 amends D009 verbatim and embeds the schema in the user message."""

        decision = APPROVED["D057"]
        system_amendment = decision["system_prompt_amendment"]
        user_amendment = decision["user_prompt_amendment"]
        self.assertEqual(
            norm(roster_prompts.JSON_OBJECT_SYSTEM_AMENDMENT),
            norm(system_amendment["replace"]),
        )
        self.assertEqual(
            norm(roster_prompts.JSON_OBJECT_SYSTEM_REPLACEMENT),
            norm(system_amendment["with"]),
        )
        self.assertEqual(
            norm(roster_prompts.JSON_OBJECT_USER_AMENDMENT),
            norm(user_amendment["replace"]),
        )
        self.assertEqual(
            norm(roster_prompts.JSON_OBJECT_USER_REPLACEMENT),
            norm(user_amendment["with"]),
        )

        schema = {"type": "object", "properties": {"candidates": {"type": "array"}}}
        built = roster_prompts.build_extractor_prompts(
            ROOT, "MANUSCRIPT", mode="json_object", schema=schema
        )
        rules = roster_prompts.render_rule_profile(ROOT, "hvs_roster_scratch", "prompt")
        expected_system = roster_prompts.EXTRACTOR_SYSTEM_TEMPLATE.replace(
            system_amendment["replace"], system_amendment["with"]
        ).replace(
            "<HVS_ROSTER_RULES_RENDERED_FROM_CANONICAL_YAML>", rules.rstrip("\n")
        )
        self.assertEqual(norm(built["system"]), norm(expected_system))
        self.assertNotIn("submit_candidate_roster", built["system"])

        expected_user = roster_prompts.EXTRACTOR_USER_TEMPLATE.replace(
            "<COMPLETE_MINIMALLY_CLEANED_TEX_FILE_BLOCKS>", "MANUSCRIPT"
        ).replace(user_amendment["replace"], user_amendment["with"])
        expected_user = expected_user.replace(
            "<OUTPUT_CONTRACT_JSON_SCHEMA>",
            json.dumps(schema, ensure_ascii=False, indent=2),
        )
        self.assertEqual(norm(built["user"]), norm(expected_user))

    def test_field_user_rendering_matches_d033_structure(self) -> None:
        """The builder composes the D033 user template for one ECSV block."""

        template = APPROVED["D033"]["user_message_template"]
        start = template.index("----- ECSV SOURCE MAPPING -----")
        end = template.index("<REPEAT_MAPPING_AND_CONTENT_FOR_EACH_VALIDATED_ECSV>")
        end += len("<REPEAT_MAPPING_AND_CONTENT_FOR_EACH_VALIDATED_ECSV>")
        expected = (
            template[:start]
            + "ECSV-BLOCK"
            + template[end:]
        )
        expected = expected.replace("<COMPLETE_MINIMALLY_CLEANED_TEX>", "MANUSCRIPT")
        expected = expected.replace("<FROZEN_IDENTIFIERS_AND_QUALIFICATION>", "CANDIDATE")
        built = field_prompts.build_field_prompts(
            ROOT,
            manuscript_view="MANUSCRIPT",
            ecsv_blocks=["ECSV-BLOCK"],
            assigned_candidate_json="CANDIDATE",
        )
        self.assertEqual(norm(built["user"]), norm(expected))


if __name__ == "__main__":
    unittest.main()
