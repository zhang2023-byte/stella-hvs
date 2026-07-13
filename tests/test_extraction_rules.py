from __future__ import annotations

import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path

from stella.benchmark.agentic_run import (
    build_agentic_system_prompt,
)
from stella.benchmark.extraction_review import build_reviewer_system_prompt
from stella.benchmark.extraction_run import build_system_prompt
from stella.benchmark.run_contract import build_method_fingerprint, canonical_sha256
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
SKILL_REL = Path("skills/hvs-candidates-extraction")


def copy_rule_workspace(destination: Path) -> Path:
    shutil.copytree(ROOT / SKILL_REL / "rules", destination / SKILL_REL / "rules")
    for relative in (SKILL_REL / "SKILL.md", Path("benchmark/GUIDELINE.md")):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    return destination


def tree_hash(workspace: Path) -> str:
    root = workspace / SKILL_REL
    return canonical_sha256(
        {
            str(path.relative_to(workspace)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }
    )


class ExtractionRuleCatalogTest(unittest.TestCase):
    def test_required_profiles_are_ordered_extractor_subsets(self) -> None:
        catalog = load_rule_catalog(ROOT)
        self.assertEqual(
            set(catalog.profiles),
            {"hvs_extractor", "hvs_roster", "hvs_reviewer", "hvs_expert_shared"},
        )
        extractor = catalog.profiles["hvs_extractor"]
        self.assertEqual(len(extractor), len(set(extractor)))
        for profile_id in ("hvs_roster", "hvs_reviewer", "hvs_expert_shared"):
            self.assertLess(len(catalog.profiles[profile_id]), len(extractor))
            self.assertTrue(set(catalog.profiles[profile_id]) < set(extractor))

    def test_generated_views_are_current(self) -> None:
        assert_generated_rule_views_current(ROOT)
        for relative, expected in generated_rule_views(ROOT).items():
            self.assertEqual((ROOT / relative).read_text(encoding="utf-8"), expected)

    def test_a_b_c_extractors_render_the_same_profile(self) -> None:
        rendered = render_rule_profile(ROOT, "hvs_extractor", "prompt")
        skill_rendered = render_rule_profile(ROOT, "hvs_extractor", "markdown")
        skill = (ROOT / SKILL_REL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(skill_rendered, skill)
        self.assertEqual(build_system_prompt(ROOT).count(rendered), 1)
        self.assertEqual(build_agentic_system_prompt(ROOT).count(rendered), 1)

    def test_reviewer_uses_only_declared_subset(self) -> None:
        catalog = load_rule_catalog(ROOT)
        rendered = render_rule_profile(ROOT, "hvs_reviewer", "prompt")
        prompt = build_reviewer_system_prompt(ROOT)
        self.assertEqual(prompt.count(rendered), 1)
        self.assertTrue(
            set(catalog.profiles["hvs_reviewer"])
            < set(catalog.profiles["hvs_extractor"])
        )

    def test_b_and_c_call_the_shared_reviewer_stage(self) -> None:
        for relative in (
            Path("src/stella/benchmark/extraction_run.py"),
            Path("src/stella/benchmark/agentic_run.py"),
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("run_independent_review(", source)

    def test_regression_rules_live_in_yaml_profiles(self) -> None:
        extractor = render_rule_profile(ROOT, "hvs_extractor", "prompt")
        roster = render_rule_profile(ROOT, "hvs_roster", "prompt")
        expert = render_rule_profile(ROOT, "hvs_expert_shared", "prompt")
        for fragment in (
            "final treatment",
            "cite-in-passing",
            "fewest extra model assumptions",
            "inaccessible remainder",
        ):
            self.assertIn(fragment, extractor)
            self.assertIn(fragment, expert)
        self.assertIn("final treatment", roster)
        self.assertIn("cite-in-passing", roster)
        self.assertIn("inaccessible remainder", roster)
        for profile_id in (
            "hvs_extractor",
            "hvs_roster",
            "hvs_reviewer",
            "hvs_expert_shared",
        ):
            rendered = render_rule_profile(ROOT, profile_id, "prompt")
            self.assertIn("without using it to re-evaluate Galactic boundness", rendered)
            self.assertIn("does not count as a candidate found", rendered)

    def test_runner_sources_do_not_embed_scientific_rule_blocks(self) -> None:
        for relative in (
            Path("src/stella/benchmark/extraction_run.py"),
            Path("src/stella/benchmark/agentic_run.py"),
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("TASK_CLARIFICATIONS", source)
            self.assertNotIn("Inclusion boundary: an object belongs", source)

    def test_invalid_catalogs_fail_closed(self) -> None:
        mutations = {
            "duplicate": (
                SKILL_REL / "rules/generic-candidate.yaml",
                "generic.candidate.identity",
                "generic.claims.paper_not_truth",
                "duplicate extraction rule id",
            ),
            "unknown": (
                SKILL_REL / "rules/profiles.yaml",
                "agent.output.validate",
                "agent.output.does_not_exist",
                "unknown rule id",
            ),
            "empty": (
                SKILL_REL / "rules/generic-candidate.yaml",
                "title: Record the paper's claim",
                "title: ''",
                "expected non-empty text",
            ),
        }
        for name, (relative, old, new, expected) in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                workspace = copy_rule_workspace(Path(tmp))
                path = workspace / relative
                path.write_text(
                    path.read_text(encoding="utf-8").replace(old, new, 1),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(ValueError, expected):
                    load_rule_catalog(workspace)

        with tempfile.TemporaryDirectory() as tmp:
            workspace = copy_rule_workspace(Path(tmp))
            path = workspace / SKILL_REL / "rules/generic-candidate.yaml"
            path.write_text("!!python/object:builtins.object {}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid YAML"):
                load_rule_catalog(workspace)

    def test_generation_detects_stale_and_bad_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = copy_rule_workspace(Path(tmp))
            guideline = workspace / "benchmark/GUIDELINE.md"
            marker = "<!-- BEGIN GENERATED RULE PROFILE: hvs_expert_shared -->"
            prefix_before = guideline.read_text(encoding="utf-8").split(marker, 1)[0]
            rule_file = workspace / SKILL_REL / "rules/generic-candidate.yaml"
            rule_file.write_text(
                rule_file.read_text(encoding="utf-8").replace(
                    "Record what the paper claims,",
                    "Record exactly what the paper claims,",
                    1,
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                set(stale_generated_rule_views(workspace)),
                {SKILL_REL / "SKILL.md", Path("benchmark/GUIDELINE.md")},
            )
            write_generated_rule_views(workspace)
            self.assertEqual(
                guideline.read_text(encoding="utf-8").split(marker, 1)[0],
                prefix_before,
            )
            assert_generated_rule_views_current(workspace)

            skill = workspace / SKILL_REL / "SKILL.md"
            skill.write_text(
                skill.read_text(encoding="utf-8").replace(
                    "<!-- END GENERATED RULE PROFILE: hvs_extractor -->", "", 1
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "exactly one marker pair"):
                generated_rule_views(workspace)

    def test_yaml_change_updates_profile_tree_and_method_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = copy_rule_workspace(Path(tmp))
            profile_before = rule_profile_sha256(workspace, "hvs_extractor")
            tree_before = tree_hash(workspace)
            method_before = build_method_fingerprint(
                {"producer": "test", "provenance": {"components": {"skill": tree_before}}}
            )

            rule_file = workspace / SKILL_REL / "rules/hvs-science.yaml"
            rule_file.write_text(
                rule_file.read_text(encoding="utf-8").replace(
                    "final treatment still leaves",
                    "final scientific treatment still leaves",
                    1,
                ),
                encoding="utf-8",
            )
            profile_after = rule_profile_sha256(workspace, "hvs_extractor")
            tree_after = tree_hash(workspace)
            method_after = build_method_fingerprint(
                {"producer": "test", "provenance": {"components": {"skill": tree_after}}}
            )
            self.assertNotEqual(profile_before, profile_after)
            self.assertNotEqual(tree_before, tree_after)
            self.assertNotEqual(method_before, method_after)


if __name__ == "__main__":
    unittest.main()
