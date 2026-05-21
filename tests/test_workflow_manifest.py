from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "workflows" / "stella_workflows.yaml"
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
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.workflows = cls.manifest["workflows"]
        cls.workflow_ids = {workflow["id"] for workflow in cls.workflows}

    def test_manifest_is_parseable_and_workflow_ids_are_unique(self) -> None:
        self.assertEqual(self.manifest["version"], 1)
        ids = [workflow["id"] for workflow in self.workflows]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_workflow_has_required_contract_fields(self) -> None:
        for workflow in self.workflows:
            with self.subTest(workflow=workflow.get("id")):
                self.assertTrue(REQUIRED_WORKFLOW_FIELDS.issubset(workflow))
                self.assertTrue(workflow["agent_prompt_template"].strip())
                self.assertTrue(workflow["outputs"])
                self.assertTrue(workflow["validators"])

    def test_referenced_paths_exist(self) -> None:
        for workflow in self.workflows:
            for relative_path in workflow.get("referenced_paths", []):
                with self.subTest(workflow=workflow["id"], path=relative_path):
                    self.assertTrue((ROOT / relative_path).exists(), relative_path)

    def test_expected_workflows_are_declared(self) -> None:
        expected = {
            "monthly_literature_fetch",
            "catalog_assessment",
            "literature_asset_archive",
            "ads_metadata_repair",
            "catalog_review",
            "catalog_table_extraction",
            "hvs_candidate_extraction",
            "object_catalog_merge",
            "hvs_catalog_html_build",
            "index_or_markdown_regeneration",
        }
        self.assertEqual(self.workflow_ids, expected)

    def test_command_script_references_exist(self) -> None:
        for workflow in self.workflows:
            for command in workflow["commands"]:
                for script in re.findall(r"\bscripts/[^\s]+\.py\b", command):
                    with self.subTest(workflow=workflow["id"], script=script):
                        self.assertTrue((ROOT / script).exists(), script)

    def test_workflow_ids_are_documented_in_human_and_agent_guides(self) -> None:
        human_text = (ROOT / "docs" / "human-workflows.md").read_text(encoding="utf-8")
        agent_text = (ROOT / "docs" / "agent-workflows.md").read_text(encoding="utf-8")
        for workflow_id in self.workflow_ids:
            with self.subTest(workflow=workflow_id, doc="human"):
                self.assertIn(workflow_id, human_text)
            with self.subTest(workflow=workflow_id, doc="agent"):
                self.assertIn(workflow_id, agent_text)

    def test_root_todo_is_not_referenced_by_agent_or_readme(self) -> None:
        for relative_path in ("AGENTS.md", "README.md"):
            text = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"\bTODO\.md\b", text), relative_path)


if __name__ == "__main__":
    unittest.main()
