from __future__ import annotations

import importlib.util
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PERMANENT_MARKDOWN = {
    Path("AGENTS.md"),
    Path("CHANGELOG.md"),
    Path("README.md"),
    Path("benchmark/AGENTS.md"),
    Path("benchmark/GUIDELINE.md"),
    Path("benchmark/L2_SPEC.md"),
    Path("benchmark/README.md"),
    Path("docs/data-contract.md"),
    Path("docs/decisions.md"),
    Path("docs/guide.md"),
    Path("docs/versions.md"),
    Path("docs/vision.md"),
}


class DocumentationContractTest(unittest.TestCase):
    def test_data_contract_declares_version_axes_and_required_rules(self) -> None:
        text = (ROOT / "docs" / "data-contract.md").read_text(encoding="utf-8")
        for phrase in (
            "Stella release",
            "Artifact schema",
            "Benchmark campaign ID",
            "PATCH",
            "normal writer emit N+1 only",
            "frozen campaign accepts no new formal runs",
            "Never overwrite a published scorecard",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_human_and_agent_entrypoints_have_distinct_routes(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        for path in (
            "docs/guide.md",
            "docs/data-contract.md",
            "docs/vision.md",
            "benchmark/README.md",
        ):
            self.assertIn(path, readme)
        self.assertIn("workflows/stella_workflows.yaml", agents)
        self.assertIn("benchmark/AGENTS.md", agents)
        self.assertIn("Documentation budget", agents)
        self.assertIn("documentation in English", agents)
        self.assertNotIn("docs/usage.md", agents)
        self.assertNotIn("docs/outputs.md", agents)

    def test_current_benchmark_docs_match_public_scorecards(self) -> None:
        readme = (ROOT / "benchmark" / "README.md").read_text(encoding="utf-8")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        guideline = (ROOT / "benchmark" / "GUIDELINE.md").read_text(encoding="utf-8")
        l2 = (ROOT / "benchmark" / "L2_SPEC.md").read_text(encoding="utf-8")

        self.assertIn("`hvs-extraction-v4` is the only writable campaign", readme)
        self.assertIn("one canonical private gold store", readme)
        self.assertIn("`benchmark.run_manifest` version 4", readme)
        self.assertIn("`benchmark.roster_bundle` version 3", readme)
        self.assertIn("first engineering batch failed the end-to-end improvement gate", readme)
        self.assertIn("forced typed `tool_submission`", changelog)
        self.assertIn("establish an end-to-end improvement", changelog)
        self.assertNotIn('"draft_schema":', guideline)
        self.assertIn('"name": "benchmark.gold_form_draft"', guideline)
        self.assertIn("`benchmark.scorecard` version 4", l2)
        self.assertIn("`benchmark.scoring_details` version 3", l2)
        self.assertIn("same campaign hash, split, and gold snapshot", l2)

        spec = importlib.util.spec_from_file_location(
            "generate_benchmark_status", ROOT / "scripts" / "generate_benchmark_status.py"
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(readme, module.updated_readme())

    def test_permanent_markdown_is_allowlisted(self) -> None:
        actual = {
            Path("AGENTS.md"),
            Path("CHANGELOG.md"),
            Path("README.md"),
            *(
                path.relative_to(ROOT)
                for path in (ROOT / "docs").rglob("*.md")
            ),
            *(
                path.relative_to(ROOT)
                for path in (ROOT / "benchmark").glob("*.md")
            ),
        }
        self.assertEqual(actual, PERMANENT_MARKDOWN)

    def test_permanent_documentation_is_english(self) -> None:
        for relative_path in sorted(PERMANENT_MARKDOWN):
            with self.subTest(path=relative_path):
                text = (ROOT / relative_path).read_text(encoding="utf-8")
                self.assertIsNone(re.search(r"[\u3400-\u9fff]", text))

    def test_permanent_document_links_resolve(self) -> None:
        missing: list[str] = []
        for relative_path in sorted(PERMANENT_MARKDOWN):
            path = ROOT / relative_path
            text = path.read_text(encoding="utf-8")
            for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
                target = target.strip()
                if (
                    not target
                    or "://" in target
                    or target.startswith(("#", "mailto:"))
                ):
                    continue
                relative = target.split("#", 1)[0]
                if relative and not (path.parent / relative).resolve().exists():
                    missing.append(f"{relative_path} -> {target}")
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
