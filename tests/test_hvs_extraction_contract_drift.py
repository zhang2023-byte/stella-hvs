"""Anti-drift checks for the canonical HVS extraction rules and prompts."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from stella.hvs_extraction import field_prompts, roster_prompts
from stella.lit.extraction_rules import load_rule_catalog, render_rule_profile


ROOT = Path(__file__).resolve().parents[1]


class CanonicalExtractionContractTest(unittest.TestCase):
    def test_explicit_group_wide_probability_can_propagate(self) -> None:
        rule = load_rule_catalog(ROOT).rules["hvs.field.bound_probability"].text
        self.assertIn("complete table or named object group", rule)
        self.assertIn("every individually identifiable member", rule)
        self.assertIn("multiple members may cite the same group-level direct evidence", rule)
        self.assertIn("A bare table", rule)
        self.assertIn("Do not derive the complementary probability", rule)

    def test_unidentifiable_remainder_becomes_reviewed_group(self) -> None:
        rule = load_rule_catalog(ROOT).rules[
            "hvs.roster.complete_identifiable_set"
        ].text
        self.assertIn("return the identifiable subset", rule)
        self.assertIn("record the unidentifiable remainder as a reviewed group", rule)
        self.assertIn("never invent identities", rule)

    def test_prompt_profiles_render_from_canonical_yaml(self) -> None:
        roster = roster_prompts.build_extractor_prompts(
            ROOT,
            "MANUSCRIPT",
            mode="json_object",
            schema={"type": "object", "properties": {"candidates": {"type": "array"}}},
        )
        roster_rules = render_rule_profile(ROOT, "hvs_candidate_roster", "prompt")
        self.assertIn(roster_rules.strip(), roster["system"])
        self.assertIn("MANUSCRIPT", roster["user"])
        self.assertIn('"candidates"', roster["user"])

        fields = field_prompts.build_field_prompts(
            ROOT,
            manuscript_view="MANUSCRIPT",
            ecsv_blocks=[],
            assigned_candidate_json=json.dumps({"record_id": "paper:cand-001"}),
        )
        field_rules = render_rule_profile(
            ROOT, "hvs_candidate_core_fields_tex", "prompt"
        )
        self.assertIn(field_rules.strip(), fields["system"])
        self.assertIn("paper:cand-001", fields["user"])

    def test_profiles_have_only_current_semantic_roles(self) -> None:
        profiles = load_rule_catalog(ROOT).profiles
        self.assertEqual(
            set(profiles),
            {
                "hvs_candidate_roster",
                "hvs_candidate_core_fields_tex",
                "hvs_candidate_core_fields_tex_ecsv",
                "coding_agent_baseline",
                "hvs_contribution_v1",
            },
        )


if __name__ == "__main__":
    unittest.main()
