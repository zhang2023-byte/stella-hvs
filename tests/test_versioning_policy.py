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


if __name__ == "__main__":
    unittest.main()
