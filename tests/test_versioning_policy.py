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
        self.assertIn("There is no trusted current", implementation)
        self.assertIn("62ce3d9", implementation)
        self.assertNotIn("### 2026-", implementation)
        self.assertNotIn("Resolved on", implementation)
        self.assertNotIn("field-low", implementation)
        self.assertNotIn("peer-consistency", implementation)
        self.assertLess(len(implementation.split()), 1800)
        self.assertNotIn('"draft_schema":', guideline)
        self.assertIn("Contribution-First Gold Annotation Guideline", guideline)
        self.assertIn("contribution_migration_ai_assisted_v1", guideline)
        self.assertIn("paper-level expert approval", guideline)
        self.assertNotIn("hvs.roster.final_treatment", guideline)
        self.assertNotIn("skills/hvs-candidates-extraction", guideline)
        self.assertNotIn("scripts/generate_extraction_rule_views.py", guideline)
        self.assertIn("contracts/hvs-contributions/rules/*.yaml", guideline)
        self.assertIn("The final Gold schema has no `range_groups` field", guideline)
        self.assertIn("source_note", guideline)
        self.assertIn("contribution_summary", guideline)
        self.assertIn("for Gold, the PDF is authoritative", guideline)
        self.assertIn("APPROVED v3.0.0", score_spec)
        for layer in ("L0", "L1", "L2"):
            self.assertIn(layer, score_spec)
        for retired_layer in ("L1a", "L1b", "L2a", "L2b"):
            self.assertNotIn(retired_layer, score_spec)
        self.assertIn("diagnostic", score_spec.lower())
        self.assertIn("no composite score", score_spec)
        self.assertNotIn("YAML/JSON twin", score_spec)
        self.assertNotIn("candidate sets per paper", score_spec)
        self.assertNotIn("L" + "3", score_spec)

    def test_gold_guideline_covers_the_current_rule_and_quantity_contract(self) -> None:
        from stella.lit.extraction_rules import (
            CONTRIBUTION_PROFILE_ID,
            load_contribution_rule_catalog,
        )
        from stella.lit.schema_specs import HVS_CONTRIBUTION_QUANTITIES

        guideline = (ROOT / "benchmark" / "GUIDELINE.md").read_text(
            encoding="utf-8"
        )
        catalog = load_contribution_rule_catalog(ROOT)
        for rule in catalog.profile_rules(CONTRIBUTION_PROFILE_ID):
            with self.subTest(rule=rule.id):
                self.assertIn(f"`{rule.id}`", guideline)
        for quantity in HVS_CONTRIBUTION_QUANTITIES:
            with self.subTest(quantity=quantity):
                self.assertIn(f"`{quantity}`", guideline)
        self.assertIn("eighteen allowed quantity paths", guideline)
        self.assertNotIn(
            "`derived_kinematics.galactocentric_tangential_velocity`",
            guideline,
        )
        self.assertIn("benchmark.hvs_contribution_annotation` v2", guideline)

    def test_current_data_contract_uses_current_contribution_paths(self) -> None:
        text = (ROOT / "docs" / "data-contract.md").read_text(encoding="utf-8")
        for path in (
            "literature/hvs_contributions_index.json",
            "literature/hvs_contribution_catalog/",
            "pages/contributions/",
            "benchmark/" + "gold_selections/<selection_id>.json",
            "runs/benchmark/<run_id>/",
        ):
            with self.subTest(path=path):
                self.assertIn(path, text)
        self.assertNotIn("catalog/web-contributions/", text)
        self.assertNotIn("report builder", text)
        self.assertNotIn("contribution-history", text)

    def test_current_gold_docs_use_active_only_git_backed_revisions(self) -> None:
        for path in (
            "benchmark/AGENTS.md",
            "benchmark/GUIDELINE.md",
            "benchmark/benchmark_implementation.md",
            "docs/data-contract.md",
            "docs/decisions.md",
        ):
            with self.subTest(path=path):
                text = (ROOT / path).read_text(encoding="utf-8")
                self.assertNotIn("contribution-history", text)
                self.assertNotIn("active-or-history", text)

    def test_current_decisions_name_only_current_owners(self) -> None:
        text = (ROOT / "docs" / "decisions.md").read_text(encoding="utf-8")
        for owner in (
            "workflows/stella_workflows.yaml",
            "workflows/operations.yaml",
            "src/stella/schema_registry.py",
            "contracts/hvs-contributions/rules/*.yaml",
        ):
            with self.subTest(owner=owner):
                self.assertIn(owner, text)
        self.assertNotIn("per-workflow definition", text)
        self.assertNotIn("peer review stage", text)

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

    def test_versions_view_matches_the_schema_registry(self) -> None:
        from stella.schema_registry import render_versions_markdown

        self.assertEqual(
            (ROOT / "docs" / "versions.md").read_text(encoding="utf-8"),
            render_versions_markdown(),
        )

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
