from __future__ import annotations

import re
import unittest
from pathlib import Path

from stella.workflows import (
    load_workflow_definition,
    load_workflow_index,
    load_workflow_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
DEFINITIONS_DIR = ROOT / "workflows" / "definitions"
REQUIRED_FIELDS = {
    "id",
    "human_intents",
    "required_inputs",
    "optional_inputs",
    "clarify_if_missing",
    "agent_prompt_template",
    "prerequisite_checks",
    "commands",
    "outputs",
    "validators",
    "risk_level",
    "network_policy",
    "generated_files_policy",
}


class WorkflowManifestTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = load_workflow_index(ROOT)
        cls.manifest = load_workflow_manifest(ROOT)
        cls.workflows = cls.manifest["workflows"]
        cls.by_id = {workflow["id"]: workflow for workflow in cls.workflows}

    def test_index_and_definitions_are_one_to_one(self) -> None:
        ids = [workflow["id"] for workflow in self.workflows]
        self.assertEqual(len(ids), len(set(ids)))
        indexed_files = set()
        for entry in self.index["workflows"]:
            workflow_id = entry["id"]
            definition = load_workflow_definition(workflow_id, ROOT)
            self.assertEqual(definition["id"], workflow_id)
            self.assertEqual(definition["human_intents"], entry["human_intents"])
            self.assertEqual(definition["risk_level"], entry["risk_level"])
            self.assertTrue(REQUIRED_FIELDS.issubset(definition))
            indexed_files.add(DEFINITIONS_DIR / entry["file"].split("/", 1)[1])
        self.assertEqual(indexed_files, set(DEFINITIONS_DIR.glob("*.yaml")))

    def test_referenced_paths_and_command_scripts_exist(self) -> None:
        for workflow in self.workflows:
            for relative in workflow.get("referenced_paths", []):
                with self.subTest(workflow=workflow["id"], path=relative):
                    self.assertTrue((ROOT / relative).exists(), relative)
            for command in workflow["commands"]:
                for script in re.findall(r"\bscripts/[^\s]+\.py\b", command):
                    with self.subTest(workflow=workflow["id"], script=script):
                        self.assertTrue((ROOT / script).exists(), script)

    def test_canonical_extraction_contract_is_v5_core_first(self) -> None:
        workflow = self.by_id["hvs_candidate_extraction"]
        rendered = "\n".join(
            [
                workflow["agent_prompt_template"],
                *workflow["outputs"],
                *workflow["referenced_paths"],
            ]
        )
        self.assertIn("V5", rendered)
        self.assertIn("three-request field budget", rendered)
        self.assertIn("v3 core artifacts only", rendered)
        self.assertIn("roster-success/field-failure", rendered)
        self.assertIn("scripts/run_hvs_candidate_extraction.py", rendered)

    def test_benchmark_semantic_routes_are_present(self) -> None:
        self.assertTrue(
            {
                "benchmark_extraction_run",
                "benchmark_coding_agent_baseline",
                "benchmark_run_finalize",
                "benchmark_gold_assignment_prepare",
                "benchmark_gold_annotation_queue",
                "benchmark_gold_selection_prepare",
                "benchmark_score_report",
            }.issubset(self.by_id)
        )
        baseline = self.by_id["benchmark_coding_agent_baseline"]
        self.assertIn(
            "must not reuse staged intermediate artifacts",
            baseline["agent_prompt_template"],
        )
        scorer = self.by_id["benchmark_score_report"]
        self.assertIn("SCORE_SPEC.md", "\n".join(scorer["referenced_paths"]))
        self.assertIn("composite score", scorer["agent_prompt_template"])
        self.assertIn("gold_selection_id", scorer["required_inputs"])
        self.assertIn("without fallback", scorer["agent_prompt_template"])
        assignment = self.by_id["benchmark_gold_assignment_prepare"]
        self.assertIn("additional annotators", assignment["agent_prompt_template"])
        queue = self.by_id["benchmark_gold_annotation_queue"]
        self.assertIn("new, resume, or completed", queue["agent_prompt_template"])
        selection = self.by_id["benchmark_gold_selection_prepare"]
        self.assertIn("assignment_id", selection["required_inputs"])

    def test_all_current_benchmark_execution_targets_v5(self) -> None:
        for workflow_id in (
            "benchmark_extraction_run",
            "benchmark_coding_agent_baseline",
            "benchmark_run_finalize",
            "benchmark_score_report",
        ):
            rendered = "\n".join(
                [
                    self.by_id[workflow_id]["agent_prompt_template"],
                    *self.by_id[workflow_id]["commands"],
                    *self.by_id[workflow_id]["outputs"],
                ]
            )
            with self.subTest(workflow=workflow_id):
                self.assertIn("v5", rendered.lower())

    def test_benchmark_workflows_load_local_agent_rules(self) -> None:
        for workflow in self.workflows:
            if workflow["id"].startswith("benchmark_"):
                with self.subTest(workflow=workflow["id"]):
                    self.assertIn(
                        "benchmark/AGENTS.md",
                        workflow.get("referenced_paths", []),
                    )

    def test_console_and_experiment_route_are_retired(self) -> None:
        self.assertNotIn("benchmark_dev_console", self.by_id)
        old_id = "benchmark_" + "scratch_dev_run"
        self.assertNotIn(old_id, self.by_id)
        for relative in (
            "benchmark/console",
            "src/stella/web/assets/benchmark-console",
            "scripts/serve_benchmark_dev_console.py",
            "workflows/definitions/benchmark_dev_console.yaml",
        ):
            self.assertFalse((ROOT / relative).exists(), relative)

    def test_batch_routes_never_reuse_workers(self) -> None:
        expected = {
            "catalog_review_batch": "catalog_review",
            "hvs_candidate_extraction_batch": "hvs_candidate_extraction",
        }
        for workflow_id, worker in expected.items():
            routing = self.by_id[workflow_id]["orchestration"]
            self.assertEqual(routing["unit"], "arxiv_id")
            self.assertEqual(routing["worker_workflow"], worker)
            self.assertEqual(routing["worker_reuse_policy"], "never")


if __name__ == "__main__":
    unittest.main()
