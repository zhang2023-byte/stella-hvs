from __future__ import annotations

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
    Path("benchmark/SCORE_SPEC.md"),
    Path("benchmark/README.md"),
    Path("benchmark/benchmark_implementation.md"),
    Path("docs/data-contract.md"),
    Path("docs/decisions.md"),
    Path("docs/guide.md"),
    Path("docs/versions.md"),
    Path("docs/vision.md"),
}


class DocumentationContractTest(unittest.TestCase):
    def test_retired_method_interfaces_do_not_reappear(self) -> None:
        forbidden = (
            re.compile(r"\bMethod\s+[ABC]\b"),
            re.compile(r"\bcore_" + r"prov\b"),
            re.compile(r"\bFU" + r"LL\b"),
            re.compile("Dev " + "Console"),
            re.compile("benchmark_" + "scratch_dev_run"),
            re.compile("run_hvs_extraction_" + "scratch"),
            re.compile("src/stella/benchmark/" + "scratch"),
        )
        candidates = [
            ROOT / "AGENTS.md",
            ROOT / "README.md",
            ROOT / ".env.example",
            *sorted((ROOT / "src").rglob("*.py")),
            *sorted((ROOT / "scripts").glob("*.py")),
            *sorted((ROOT / "workflows").rglob("*.yaml")),
            *sorted((ROOT / "docs").glob("*.md")),
            *sorted((ROOT / "benchmark").glob("*.md")),
            *sorted((ROOT / "benchmark").glob("*.yaml")),
        ]
        allowed = {
            ROOT / "src/stella/schema_registry.py",
            Path(__file__).resolve(),
        }
        hits: list[str] = []
        for path in candidates:
            if path in allowed or "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for pattern in forbidden:
                if pattern.search(text):
                    hits.append(
                        f"{path.relative_to(ROOT)}: {pattern.pattern}"
                    )
        self.assertEqual(hits, [])

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

    def test_current_benchmark_docs_have_distinct_owners(self) -> None:
        readme = (ROOT / "benchmark" / "README.md").read_text(encoding="utf-8")
        implementation = (
            ROOT / "benchmark" / "benchmark_implementation.md"
        ).read_text(encoding="utf-8")
        guideline = (ROOT / "benchmark" / "GUIDELINE.md").read_text(encoding="utf-8")
        score_spec = (ROOT / "benchmark" / "SCORE_SPEC.md").read_text(encoding="utf-8")

        self.assertIn("Route map", readme)
        self.assertNotIn("Latest development evidence", readme)
        self.assertIn("Decision-relevant evidence", implementation)
        self.assertIn("Open risks", implementation)
        self.assertIn("Next gate", implementation)
        self.assertIn("evaluation_ready", implementation)
        self.assertIn("0.780 to 0.982", implementation)
        self.assertNotIn("### 2026-", implementation)
        self.assertNotIn("Resolved on", implementation)
        self.assertLess(len(implementation.split()), 1800)
        self.assertNotIn('"draft_schema":', guideline)
        self.assertIn("Contribution-First Gold Annotation Guideline", guideline)
        self.assertIn("contribution_migration_ai_assisted_v1", guideline)
        self.assertIn("paper-level expert approval", guideline)
        self.assertNotIn("hvs.roster.final_treatment", guideline)
        self.assertIn("APPROVED v2.0.0", score_spec)
        self.assertIn("L0 format validation", score_spec)
        self.assertIn("no composite score", score_spec)
        self.assertNotIn("L" + "3", score_spec)

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
