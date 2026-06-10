from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "workflows" / "stella_workflows.yaml"

FORBIDDEN_FOR_EXTRACTION = (
    "benchmark/gold/",
    "benchmark/adjudication/",
    "benchmark/alignment/",
    "benchmark/manifest/",
)


class BenchmarkIsolationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.workflow_by_id = {workflow["id"]: workflow for workflow in manifest["workflows"]}

    def test_production_extraction_prompt_carries_isolation_rule(self) -> None:
        prompt = self.workflow_by_id["hvs_candidate_extraction"]["agent_prompt_template"]
        for path in FORBIDDEN_FOR_EXTRACTION:
            self.assertIn(path, prompt)

    def test_variant_extraction_prompt_carries_contamination_rule(self) -> None:
        prompt = self.workflow_by_id["hvs_benchmark_variant_extraction"]["agent_prompt_template"]
        self.assertIn("CONTAMINATION RULE", prompt)
        self.assertIn("literature/<arxiv_id>/literature_hvs_candidates.json", prompt)
        for path in FORBIDDEN_FOR_EXTRACTION:
            self.assertIn(path, prompt)

    def test_variant_batch_does_not_leak_parent_context(self) -> None:
        prompt = self.workflow_by_id["hvs_benchmark_variant_extraction_batch"][
            "agent_prompt_template"
        ]
        self.assertIn("passing only arxiv_id and variant_id", prompt)
        orchestration = self.workflow_by_id["hvs_benchmark_variant_extraction_batch"]["orchestration"]
        self.assertEqual(orchestration["worker_reuse_policy"], "never")

    def test_benchmark_workflows_write_only_under_benchmark(self) -> None:
        for workflow_id, workflow in self.workflow_by_id.items():
            if not workflow_id.startswith("hvs_benchmark_"):
                continue
            for output in workflow["outputs"]:
                with self.subTest(workflow=workflow_id, output=output):
                    self.assertTrue(output.startswith("benchmark/"), output)

    def test_agents_md_documents_isolation(self) -> None:
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("## Benchmark Data Isolation", text)
        for path in ("benchmark/gold/", "benchmark/adjudication/", "benchmark/alignment/"):
            self.assertIn(path, text)

    def test_skill_documents_isolation(self) -> None:
        text = (ROOT / "skills" / "hvs-benchmark" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Data Isolation", text)
        self.assertIn("benchmark/gold/", text)

    def test_readme_contamination_notices(self) -> None:
        for relative in ("benchmark/README.md", "benchmark/gold/README.md"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(path=relative):
                self.assertIn("CONTAMINATION NOTICE", text)


if __name__ == "__main__":
    unittest.main()
