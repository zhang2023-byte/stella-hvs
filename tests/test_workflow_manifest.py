from __future__ import annotations

import re
import unittest
from pathlib import Path

from stella.workflows import load_workflow_definition, load_workflow_index, load_workflow_manifest


ROOT = Path(__file__).resolve().parents[1]
DEFINITIONS_DIR = ROOT / "workflows" / "definitions"
REQUIRED_WORKFLOW_FIELDS = {
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
        cls.workflow_ids = {workflow["id"] for workflow in cls.workflows}
        cls.workflow_by_id = {workflow["id"]: workflow for workflow in cls.workflows}

    def test_manifest_is_parseable_and_workflow_ids_are_unique(self) -> None:
        self.assertEqual(self.manifest["version"], 1)
        self.assertIn("temporary_artifacts_policy", self.manifest)
        self.assertIn("Temporary helper scripts", self.manifest["temporary_artifacts_policy"])
        ids = [workflow["id"] for workflow in self.workflows]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_workflow_has_required_contract_fields(self) -> None:
        for workflow in self.workflows:
            with self.subTest(workflow=workflow.get("id")):
                self.assertTrue(REQUIRED_WORKFLOW_FIELDS.issubset(workflow))
                self.assertTrue(workflow["agent_prompt_template"].strip())
                self.assertTrue(workflow["outputs"])
                self.assertTrue(workflow["validators"])

    def test_index_references_one_definition_per_workflow(self) -> None:
        indexed_files = set()
        for workflow in self.index["workflows"]:
            with self.subTest(workflow=workflow.get("id")):
                workflow_id = workflow["id"]
                self.assertEqual(workflow["file"], f"definitions/{workflow_id}.yaml")
                self.assertIn("human_intents", workflow)
                self.assertIn("risk_level", workflow)
                definition = load_workflow_definition(workflow_id, ROOT)
                self.assertEqual(definition["id"], workflow_id)
                self.assertEqual(definition["human_intents"], workflow["human_intents"])
                self.assertEqual(definition["risk_level"], workflow["risk_level"])
                indexed_files.add(DEFINITIONS_DIR / f"{workflow_id}.yaml")

        definition_files = set(DEFINITIONS_DIR.glob("*.yaml"))
        self.assertEqual(definition_files, indexed_files)

    def test_referenced_paths_exist(self) -> None:
        for workflow in self.workflows:
            for relative_path in workflow.get("referenced_paths", []):
                with self.subTest(workflow=workflow["id"], path=relative_path):
                    self.assertTrue((ROOT / relative_path).exists(), relative_path)

    def test_benchmark_extraction_declares_rule_bearing_dependencies(self) -> None:
        workflow = self.workflow_by_id["benchmark_extraction_run"]
        referenced = set(workflow.get("referenced_paths", []))
        self.assertTrue(
            {
                "skills/hvs-candidates-extraction/SKILL.md",
                "skills/hvs-candidates-extraction/rules/profiles.yaml",
                "src/stella/lit/extraction_rules.py",
                "scripts/generate_extraction_rule_views.py",
                "scripts/validate_hvs_candidates.py",
                "src/stella/benchmark/extraction_run.py",
                "src/stella/benchmark/agentic_run.py",
                "src/stella/benchmark/context_pack.py",
            }.issubset(referenced)
        )
        prompt = workflow["agent_prompt_template"]
        self.assertIn("Method A is the hvs-candidates-extraction skill", prompt)
        self.assertIn(
            "Methods B and C render the same canonical hvs_extractor YAML profile",
            prompt,
        )

    def test_expected_workflows_are_declared(self) -> None:
        expected = {
            "monthly_literature_fetch",
            "catalog_assessment",
            "literature_asset_archive",
            "ads_metadata_repair",
            "catalog_review",
            "catalog_review_batch",
            "catalog_table_extraction",
            "hvs_candidate_extraction",
            "hvs_candidate_extraction_batch",
            "object_catalog_merge",
            "hvs_dynamics_calculate",
            "hvs_catalog_web_build",
            "hvs_catalog_pages_prepare",
            "benchmark_gold_annotation_form",
            "benchmark_campaign_prepare",
            "benchmark_extraction_run",
            "benchmark_run_finalize",
            "benchmark_score_report",
            "index_or_markdown_regeneration",
        }
        self.assertEqual(self.workflow_ids, expected)

    def test_batch_workflows_declare_subagent_orchestration_contract(self) -> None:
        expected_workers = {
            "catalog_review_batch": "catalog_review",
            "hvs_candidate_extraction_batch": "hvs_candidate_extraction",
        }
        required_status_fields = {
            "arxiv_id",
            "status",
            "outputs",
            "validator_result",
            "warnings",
            "blockers",
            "next_action",
        }
        for workflow_id, worker_workflow in expected_workers.items():
            with self.subTest(workflow=workflow_id):
                workflow = self.workflow_by_id[workflow_id]
                orchestration = workflow.get("orchestration")
                self.assertIsInstance(orchestration, dict)
                self.assertEqual(orchestration["unit"], "arxiv_id")
                self.assertEqual(orchestration["worker_workflow"], worker_workflow)
                self.assertIn(worker_workflow, self.workflow_ids)
                self.assertEqual(orchestration["worker_reuse_policy"], "never")
                self.assertEqual(orchestration["concurrency_strategy"], "adaptive_probe")
                self.assertEqual(orchestration["parent_role"], "dispatch_monitor_summarize")
                self.assertEqual(set(orchestration["worker_status_fields"]), required_status_fields)

    def test_command_script_references_exist(self) -> None:
        for workflow in self.workflows:
            for command in workflow["commands"]:
                for script in re.findall(r"\bscripts/[^\s]+\.py\b", command):
                    with self.subTest(workflow=workflow["id"], script=script):
                        self.assertTrue((ROOT / script).exists(), script)

    def test_deleted_human_workflow_guide_is_not_referenced(self) -> None:
        deleted_basename = "workflows" + "." + "md"
        deleted_guide = "docs/" + deleted_basename
        ignored_parts = {
            ".git",
            ".mypy_cache",
            ".pytest_cache",
            "__pycache__",
            "catalog",
            "literature",
            "notes",
        }
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if ignored_parts.intersection(path.relative_to(ROOT).parts):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertNotIn(deleted_guide, text)
                self.assertNotIn(deleted_basename, text)

    def test_root_todo_is_not_referenced_by_agent_or_readme(self) -> None:
        for relative_path in ("AGENTS.md", "README.md"):
            text = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"\bTODO\.md\b", text), relative_path)


if __name__ == "__main__":
    unittest.main()
