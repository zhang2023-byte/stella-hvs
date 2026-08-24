"""Guard the canonical extraction rule library and profile composition."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from stella.lit.extraction_rules import (
    assert_generated_rule_views_current,
    generated_rule_views,
    load_rule_catalog,
    render_rule_profile,
    rule_profile_sha256,
    stale_generated_rule_views,
    write_generated_rule_views,
)


ROOT = Path(__file__).resolve().parents[1]
RULES_REL = Path("skills/hvs-candidates-extraction/rules")

ROSTER_RULES = (
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

CORE_FIELD_TEX_RULES = (
    "paper.claims.reported_not_truth",
    "hvs.field.fixed_candidate",
    "hvs.field.reported_values_only",
    "hvs.field.multiple_estimates",
    "hvs.field.uncertainty_limits",
    "hvs.field.coordinates",
    "hvs.field.galactic_rest_frame_velocity",
    "hvs.field.bound_probability",
    "hvs.field.null_reconciliation",
    "hvs.field.candidate_origin",
    "hvs.field.tex_evidence",
    "hvs.field.component_evidence",
    "hvs.field.source_relevance",
)

CORE_FIELD_TEX_ECSV_RULES = (
    "paper.claims.reported_not_truth",
    "hvs.field.fixed_candidate",
    "hvs.field.reported_values_only",
    "hvs.field.multiple_estimates",
    "hvs.field.uncertainty_limits",
    "hvs.field.coordinates",
    "hvs.field.galactic_rest_frame_velocity",
    "hvs.field.bound_probability",
    "hvs.field.null_reconciliation",
    "hvs.field.candidate_origin",
    "hvs.field.source_authority",
    "hvs.field.ecsv_evidence",
    "hvs.field.tex_evidence",
    "hvs.field.component_evidence",
    "hvs.field.source_relevance",
    "hvs.field.provenance_conflicts",
)

CONTRIBUTION_PROFILE_RULES = (
    "paper.claims.reported_not_truth",
    "hvs.contrib.paper_local_boundary",
    "hvs.contrib.candidates_found",
    "hvs.contrib.follow_up",
    "hvs.contrib.paper_boundness",
    "hvs.contrib.background_exclusion",
    "hvs.contrib.required_summary_evidence",
    "hvs.contrib.complete_identifiable_set",
    "hvs.contrib.paper_visible_identity",
    "hvs.contrib.all_values_after_l1",
    "hvs.contrib.nineteen_quantities",
    "hvs.contrib.grouped_multivalue",
    "hvs.contrib.value_evidence",
    "hvs.contrib.no_derivation",
    "hvs.contrib.paper_preferred",
    "hvs.contrib.source_provenance",
)

# Pinned before the contribution profile was added; these must never change
# without an explicit V6 rule decision.
V6_PROFILE_SHA256 = {
    "hvs_candidate_roster": "d660a2de983ba7dd9dfffdbaa85bb01fa7016fdf4060e2f6be600ac18e24cea3",
    "hvs_candidate_core_fields_tex": "6796461a0b93eb747e265028e535eaf4be255619c701ad268e281a70aa441722",
    "hvs_candidate_core_fields_tex_ecsv": "f164d6ed3fbd2b2920058cef3788d6603cd931b2ab32d28cc21411470c4a02fb",
    "coding_agent_baseline": "00dc97d18c6e4e213649d266eb69f9b4040c5ea552ea74df149f2377e8c0e111",
}

CANONICAL_MODULES = {
    "paper-claims.yaml": 1,
    "hvs-roster.yaml": 8,
    "hvs-core-fields.yaml": 15,
}


def copy_rules(destination: Path) -> Path:
    shutil.copytree(ROOT / RULES_REL, destination / RULES_REL)
    return destination


class CanonicalRuleLibraryTest(unittest.TestCase):
    def test_profiles_match_approved_ordered_membership(self) -> None:
        catalog = load_rule_catalog(ROOT)
        self.assertEqual(
            set(catalog.profiles),
            {
                "hvs_candidate_roster",
                "hvs_candidate_core_fields_tex",
                "hvs_candidate_core_fields_tex_ecsv",
                "coding_agent_baseline",
                "hvs_contribution_v1",
            },
        )
        self.assertEqual(catalog.profiles["hvs_candidate_roster"], ROSTER_RULES)
        self.assertEqual(
            catalog.profiles["hvs_candidate_core_fields_tex"], CORE_FIELD_TEX_RULES
        )
        self.assertEqual(
            catalog.profiles["hvs_candidate_core_fields_tex_ecsv"],
            CORE_FIELD_TEX_ECSV_RULES,
        )
        self.assertEqual(
            catalog.profiles["hvs_contribution_v1"], CONTRIBUTION_PROFILE_RULES
        )

    def test_library_has_exactly_24_rules_in_three_modules(self) -> None:
        catalog = load_rule_catalog(ROOT)
        canonical_ids = {
            rule_id
            for rule_id in catalog.rules
            if rule_id.startswith(("paper.", "hvs.roster.", "hvs.field."))
        }
        expected = (
            set(ROSTER_RULES)
            | set(CORE_FIELD_TEX_RULES)
            | set(CORE_FIELD_TEX_ECSV_RULES)
        )
        self.assertEqual(canonical_ids, expected)
        self.assertEqual(len(expected), 24)
        self.assertEqual(sum(CANONICAL_MODULES.values()), 24)

    def test_tex_profile_is_strict_subset_of_tex_ecsv(self) -> None:
        catalog = load_rule_catalog(ROOT)
        tex = set(catalog.profiles["hvs_candidate_core_fields_tex"])
        tex_ecsv = set(catalog.profiles["hvs_candidate_core_fields_tex_ecsv"])
        self.assertTrue(tex < tex_ecsv)
        self.assertEqual(
            tex_ecsv - tex,
            {
                "hvs.field.source_authority",
                "hvs.field.ecsv_evidence",
                "hvs.field.provenance_conflicts",
            },
        )

    def test_render_names_no_hidden_sources_or_other_stage_fields(self) -> None:
        roster = render_rule_profile(ROOT, "hvs_candidate_roster", "prompt")
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
        tex_only = render_rule_profile(ROOT, "hvs_candidate_core_fields_tex", "prompt")
        self.assertNotIn("ECSV", tex_only)
        self.assertNotIn("ecsv", tex_only)
        tex_ecsv = render_rule_profile(ROOT, "hvs_candidate_core_fields_tex_ecsv", "prompt")
        self.assertIn("ECSV", tex_ecsv)

    def test_render_and_hash_are_deterministic(self) -> None:
        for profile_id in (
            "hvs_candidate_roster",
            "hvs_candidate_core_fields_tex",
            "hvs_candidate_core_fields_tex_ecsv",
            "hvs_contribution_v1",
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

    def test_v6_profile_hashes_are_pinned_and_unchanged(self) -> None:
        for profile_id, expected in V6_PROFILE_SHA256.items():
            with self.subTest(profile_id=profile_id):
                self.assertEqual(rule_profile_sha256(ROOT, profile_id), expected)

    def test_contribution_profile_hash_differs_from_v6(self) -> None:
        contribution_hash = rule_profile_sha256(ROOT, "hvs_contribution_v1")
        self.assertNotIn(contribution_hash, set(V6_PROFILE_SHA256.values()))

    def test_rule_text_change_updates_profile_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = copy_rules(Path(tmp))
            before = rule_profile_sha256(workspace, "hvs_candidate_roster")
            rule_file = workspace / RULES_REL / "hvs-roster.yaml"
            rule_file.write_text(
                rule_file.read_text(encoding="utf-8").replace(
                    "Return every qualifying object",
                    "Return each qualifying object",
                    1,
                ),
                encoding="utf-8",
            )
            after = rule_profile_sha256(workspace, "hvs_candidate_roster")
            self.assertNotEqual(before, after)

    def test_coding_agent_profile_is_exact_staged_rule_union(self) -> None:
        catalog = load_rule_catalog(ROOT)
        baseline = set(catalog.profiles["coding_agent_baseline"])
        staged = set(catalog.profiles["hvs_candidate_roster"]) | set(
            catalog.profiles["hvs_candidate_core_fields_tex_ecsv"]
        )
        self.assertEqual(baseline, staged)
        self.assertEqual(len(baseline), 24)

    def test_generated_views_are_current(self) -> None:
        assert_generated_rule_views_current(ROOT)
        for relative, expected in generated_rule_views(ROOT).items():
            self.assertEqual((ROOT / relative).read_text(encoding="utf-8"), expected)

    def test_invalid_profile_rule_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = copy_rules(Path(tmp))
            profiles = workspace / RULES_REL / "profiles.yaml"
            profiles.write_text(
                profiles.read_text(encoding="utf-8").replace(
                    "hvs.roster.final_treatment",
                    "hvs.roster.does_not_exist",
                    1,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "unknown rule id"):
                load_rule_catalog(workspace)

    def test_generation_detects_stale_rule_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            shutil.copytree(ROOT / RULES_REL, workspace / RULES_REL)
            for relative in (
                Path("skills/hvs-candidates-extraction/SKILL.md"),
                Path("benchmark/GUIDELINE.md"),
                Path("skills/hvs-candidates-extraction/references/contribution-rules.md"),
            ):
                target = workspace / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, target)
            rule_file = workspace / RULES_REL / "hvs-roster.yaml"
            rule_file.write_text(
                rule_file.read_text(encoding="utf-8").replace(
                    "Return every qualifying object",
                    "Return each qualifying object",
                    1,
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                set(stale_generated_rule_views(workspace)),
                {Path("skills/hvs-candidates-extraction/SKILL.md")},
            )
            write_generated_rule_views(workspace)
            self.assertEqual(stale_generated_rule_views(workspace), [])

    def test_contribution_rule_change_updates_guideline_and_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            shutil.copytree(ROOT / RULES_REL, workspace / RULES_REL)
            for relative in (
                Path("skills/hvs-candidates-extraction/SKILL.md"),
                Path("benchmark/GUIDELINE.md"),
                Path("skills/hvs-candidates-extraction/references/contribution-rules.md"),
            ):
                target = workspace / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, target)
            rule_file = workspace / RULES_REL / "hvs-contributions-roster.yaml"
            rule_file.write_text(
                rule_file.read_text(encoding="utf-8").replace(
                    "Include any substantive current-paper research",
                    "Include substantive current-paper research",
                    1,
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                set(stale_generated_rule_views(workspace)),
                {
                    Path("benchmark/GUIDELINE.md"),
                    Path("skills/hvs-candidates-extraction/references/contribution-rules.md"),
                },
            )


class ContributionProfileTest(unittest.TestCase):
    def test_profile_excludes_v6_roster_and_field_rules(self) -> None:
        catalog = load_rule_catalog(ROOT)
        rule_ids = set(catalog.profiles["hvs_contribution_v1"])
        self.assertNotIn("hvs.roster.final_treatment", rule_ids)
        self.assertNotIn("hvs.roster.prior_reassessment", rule_ids)
        self.assertFalse([rule_id for rule_id in rule_ids if rule_id.startswith(("hvs.roster.", "hvs.field."))])

    def test_generated_view_includes_every_new_rule_exactly_once(self) -> None:
        view_path = ROOT / "skills/hvs-candidates-extraction/references/contribution-rules.md"
        text = view_path.read_text(encoding="utf-8")
        catalog = load_rule_catalog(ROOT)
        for rule in catalog.profile_rules("hvs_contribution_v1"):
            with self.subTest(rule=rule.id):
                self.assertEqual(text.count(f"`{rule.id}`"), 1)
                self.assertEqual(text.count(rule.title), 1)

    def test_generated_view_matches_render(self) -> None:
        from stella.lit.extraction_rules import render_contribution_rules_view

        view_path = ROOT / "skills/hvs-candidates-extraction/references/contribution-rules.md"
        self.assertEqual(
            view_path.read_text(encoding="utf-8"),
            render_contribution_rules_view(ROOT),
        )

    def test_no_rule_instructs_inference_of_status_or_scenarios(self) -> None:
        render = render_rule_profile(ROOT, "hvs_contribution_v1", "prompt")
        prohibitions = (
            "Never derive a status from a probability",
            "do not derive the complementary bound or unbound probability",
            "no cross-quantity scenario join",
            "Never use a fewest-assumptions or final-treatment fallback",
        )
        for phrase in prohibitions:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, render)
        affirmative = (
            "guess the bibkey",
            "infer the bibkey",
            "you may infer",
            "choose a status threshold",
            "compute the complementary",
            "combine conditions across quantities when",
            "compute the average of",
        )
        for phrase in affirmative:
            with self.subTest(forbidden=phrase):
                self.assertNotIn(phrase, render)
        self.assertNotIn("bibkey", render.lower())

    def test_profile_covers_the_exact_nineteen_quantities(self) -> None:
        render = render_rule_profile(ROOT, "hvs_contribution_v1", "prompt")
        from stella.lit.schema_specs import HVS_CONTRIBUTION_QUANTITIES

        for quantity in HVS_CONTRIBUTION_QUANTITIES:
            with self.subTest(quantity=quantity):
                self.assertIn(quantity, render)
        self.assertNotIn("derived_kinematics.total_velocity", render)
        self.assertNotIn("spectroscopy.teff", render)


if __name__ == "__main__":
    unittest.main()
