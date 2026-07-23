"""Guard the frozen D054 scratch rule library and profile composition."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from stella.lit.extraction_rules import (
    load_rule_catalog,
    render_rule_profile,
    rule_profile_sha256,
)


ROOT = Path(__file__).resolve().parents[1]
RULES_REL = Path("skills/hvs-candidates-extraction/rules")

ROSTER_SCRATCH_RULES = (
    "paper.claims.reported_not_truth",
    "hvs.roster.final_treatment",
    "hvs.roster.textual_anchor",
    "hvs.roster.prior_reassessment",
    "hvs.roster.galaxy_bound_exclusions",
    "hvs.roster.complete_identifiable_set",
    "hvs.roster.paper_visible_identity",
    "hvs.roster.decision_evidence",
    "hvs.roster.reviewed_exclusions",
)

FIELD_SCRATCH_TEX_RULES = (
    "paper.claims.reported_not_truth",
    "hvs.field.fixed_candidate",
    "hvs.field.reported_values_only",
    "hvs.field.multiple_estimates",
    "hvs.field.uncertainty_limits",
    "hvs.field.coordinates",
    "hvs.field.galactic_rest_frame_velocity",
    "hvs.field.bound_probability",
    "hvs.field.candidate_origin",
    "hvs.field.tex_evidence",
    "hvs.field.component_evidence",
    "hvs.field.source_relevance",
)

FIELD_SCRATCH_TEX_ECSV_RULES = (
    "paper.claims.reported_not_truth",
    "hvs.field.fixed_candidate",
    "hvs.field.reported_values_only",
    "hvs.field.multiple_estimates",
    "hvs.field.uncertainty_limits",
    "hvs.field.coordinates",
    "hvs.field.galactic_rest_frame_velocity",
    "hvs.field.bound_probability",
    "hvs.field.candidate_origin",
    "hvs.field.source_authority",
    "hvs.field.ecsv_evidence",
    "hvs.field.tex_evidence",
    "hvs.field.component_evidence",
    "hvs.field.source_relevance",
    "hvs.field.provenance_conflicts",
)

SCRATCH_MODULES = {
    "paper-claims.yaml": 1,
    "hvs-roster-scratch.yaml": 8,
    "hvs-field-scratch.yaml": 14,
}


def copy_rules(destination: Path) -> Path:
    shutil.copytree(ROOT / RULES_REL, destination / RULES_REL)
    return destination


class ScratchRuleLibraryTest(unittest.TestCase):
    def test_scratch_profiles_match_d054_ordered_membership(self) -> None:
        catalog = load_rule_catalog(ROOT)
        self.assertEqual(catalog.profiles["hvs_roster_scratch"], ROSTER_SCRATCH_RULES)
        self.assertEqual(
            catalog.profiles["hvs_field_extractor_scratch_tex"], FIELD_SCRATCH_TEX_RULES
        )
        self.assertEqual(
            catalog.profiles["hvs_field_extractor_scratch_tex_ecsv"],
            FIELD_SCRATCH_TEX_ECSV_RULES,
        )

    def test_scratch_library_has_exactly_23_rules_in_three_modules(self) -> None:
        catalog = load_rule_catalog(ROOT)
        scratch_ids = {
            rule_id
            for rule_id in catalog.rules
            if rule_id.startswith(("paper.", "hvs.roster.", "hvs.field."))
        }
        expected = (
            set(ROSTER_SCRATCH_RULES)
            | set(FIELD_SCRATCH_TEX_RULES)
            | set(FIELD_SCRATCH_TEX_ECSV_RULES)
        )
        self.assertEqual(scratch_ids, expected)
        self.assertEqual(len(expected), 23)
        self.assertEqual(sum(SCRATCH_MODULES.values()), 23)

    def test_scratch_tex_profile_is_strict_subset_of_tex_ecsv(self) -> None:
        catalog = load_rule_catalog(ROOT)
        tex = set(catalog.profiles["hvs_field_extractor_scratch_tex"])
        tex_ecsv = set(catalog.profiles["hvs_field_extractor_scratch_tex_ecsv"])
        self.assertTrue(tex < tex_ecsv)
        self.assertEqual(
            tex_ecsv - tex,
            {
                "hvs.field.source_authority",
                "hvs.field.ecsv_evidence",
                "hvs.field.provenance_conflicts",
            },
        )

    def test_scratch_render_names_no_hidden_sources_or_other_stage_fields(self) -> None:
        roster = render_rule_profile(ROOT, "hvs_roster_scratch", "prompt")
        for forbidden in (
            "ECSV",
            "ecsv",
            "submit_candidate_fields",
            "method_chain",
            "record_id",
            "scorecard",
            "structured_input_preparation_failure",
        ):
            self.assertNotIn(forbidden, roster)
        tex_only = render_rule_profile(ROOT, "hvs_field_extractor_scratch_tex", "prompt")
        self.assertNotIn("ECSV", tex_only)
        self.assertNotIn("ecsv", tex_only)
        tex_ecsv = render_rule_profile(ROOT, "hvs_field_extractor_scratch_tex_ecsv", "prompt")
        self.assertIn("ECSV", tex_ecsv)

    def test_scratch_render_and_hash_are_deterministic(self) -> None:
        for profile_id in (
            "hvs_roster_scratch",
            "hvs_field_extractor_scratch_tex",
            "hvs_field_extractor_scratch_tex_ecsv",
        ):
            with self.subTest(profile_id=profile_id):
                self.assertEqual(
                    render_rule_profile(ROOT, profile_id, "prompt"),
                    render_rule_profile(ROOT, profile_id, "prompt"),
                )
                self.assertEqual(
                    rule_profile_sha256(ROOT, profile_id),
                    rule_profile_sha256(ROOT, profile_id),
                )

    def test_scratch_rule_text_change_updates_profile_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = copy_rules(Path(tmp))
            before = rule_profile_sha256(workspace, "hvs_roster_scratch")
            rule_file = workspace / RULES_REL / "hvs-roster-scratch.yaml"
            rule_file.write_text(
                rule_file.read_text(encoding="utf-8").replace(
                    "Return every qualifying object",
                    "Return each qualifying object",
                    1,
                ),
                encoding="utf-8",
            )
            after = rule_profile_sha256(workspace, "hvs_roster_scratch")
            self.assertNotEqual(before, after)

    def test_legacy_profile_hashes_are_untouched_by_scratch_rules(self) -> None:
        for profile_id in ("hvs_extractor", "hvs_roster", "hvs_reviewer", "hvs_expert_shared"):
            with self.subTest(profile_id=profile_id):
                catalog = load_rule_catalog(ROOT)
                for rule in catalog.profile_rules(profile_id):
                    self.assertFalse(
                        rule.id.startswith(("paper.", "hvs.roster.", "hvs.field.")),
                        f"legacy profile {profile_id} must not reference scratch rules",
                    )


if __name__ == "__main__":
    unittest.main()
