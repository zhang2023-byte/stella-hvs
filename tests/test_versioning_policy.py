from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class VersioningPolicyTest(unittest.TestCase):
    def test_policy_declares_all_three_axes_and_required_rules(self) -> None:
        text = (ROOT / "docs" / "versioning-policy.md").read_text(encoding="utf-8")
        for phrase in (
            "Stella release",
            "Artifact schema",
            "Benchmark campaign ID",
            "not contain breaking changes",
            "A campaign is immutable after freeze",
            "all normal writers emit only `N+1`",
            "Do not silently overwrite a published scorecard",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_policy_is_linked_from_human_and_agent_entrypoints(self) -> None:
        for relative in ("README.md", "AGENTS.md"):
            with self.subTest(path=relative):
                text = (ROOT / relative).read_text(encoding="utf-8")
                self.assertIn("docs/versioning-policy.md", text)

    def test_current_benchmark_docs_do_not_present_legacy_writers_as_current(self) -> None:
        plan = (ROOT / "docs" / "benchmark-plan.md").read_text(encoding="utf-8")
        guideline = (ROOT / "benchmark" / "GUIDELINE.md").read_text(encoding="utf-8")
        l2 = (ROOT / "docs" / "benchmark-l2-spec.md").read_text(encoding="utf-8")
        self.assertIn("`hvs-extraction-v4` 是", plan)
        self.assertIn("唯一 canonical private gold", plan)
        self.assertNotIn('"draft_schema":', guideline)
        self.assertIn('"name": "benchmark.gold_form_draft"', guideline)
        self.assertIn("`benchmark.scorecard` version 4", l2)
        self.assertIn("`benchmark.scoring_details` version 3", l2)


if __name__ == "__main__":
    unittest.main()
