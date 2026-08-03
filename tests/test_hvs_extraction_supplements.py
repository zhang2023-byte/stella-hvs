from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from stella.benchmark.campaign import sha256_file
from stella.hvs_extraction.core_document import build_core_document
from stella.hvs_extraction.supplements import (
    fake_supplement_adapter,
    run_supplement,
)
from tests.hvs_extraction_fixtures import (
    complete_fields,
    paper_result,
)

ARXIV_ID = "2406.99994"
SOURCE_RUN_ID = "core-source"


def make_source_run(tmp: str) -> tuple[Path, Path]:
    workspace = Path(tmp)
    paper_dir = (
        workspace
        / "benchmark/campaigns/hvs-extraction-v6/runs"
        / SOURCE_RUN_ID
        / "papers"
        / ARXIV_ID
    )
    paper_dir.mkdir(parents=True)
    config = {
        "schema": {"name": "benchmark.run_config", "version": 4},
        "run_id": SOURCE_RUN_ID,
        "campaign": {"campaign_id": "hvs-extraction-v6"},
        "papers": [ARXIV_ID],
    }
    (paper_dir.parents[1] / "run_config.json").write_text(
        json.dumps(config), encoding="utf-8"
    )
    result = paper_result(
        candidates=[{"record_id": "candidate-001", "status": "fields_complete"}],
        fields=complete_fields(),
    )
    result.update(
        {
            "generated_at": "2026-07-26T00:00:00+00:00",
            "paper": {"arxiv_id": ARXIV_ID},
            "run_id": SOURCE_RUN_ID,
        }
    )
    core = build_core_document(
        result,
        campaign_id="hvs-extraction-v6",
        method_fingerprint="f" * 64,
    )
    core_path = paper_dir / "literature_hvs_candidates.json"
    core_path.write_text(json.dumps(core), encoding="utf-8")
    return workspace, core_path


class SupplementContractTest(unittest.TestCase):
    def test_unregistered_adapter_refuses_before_creating_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, _ = make_source_run(tmp)
            with self.assertRaisesRegex(ValueError, "no real supplement"):
                run_supplement(
                    workspace,
                    run_id="supplement-none",
                    source_run_id=SOURCE_RUN_ID,
                    arxiv_ids=[ARXIV_ID],
                    supplement_type="full_fields",
                    adapter=None,
                )
            self.assertFalse(
                (
                    workspace
                    / "benchmark/campaigns/hvs-extraction-v6/supplements"
                    / "supplement-none"
                ).exists()
            )

    def test_preflight_only_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, core_path = make_source_run(tmp)
            result = run_supplement(
                workspace,
                run_id="supplement-preflight",
                source_run_id=SOURCE_RUN_ID,
                arxiv_ids=[ARXIV_ID],
                supplement_type="method_chain",
                adapter=None,
                preflight_only=True,
            )
            self.assertFalse(result["run_created"])
            self.assertEqual(
                result["core_artifact_sha256"][ARXIV_ID],
                sha256_file(core_path),
            )

    def test_fake_full_fields_adapter_binds_without_modifying_core(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, core_path = make_source_run(tmp)
            before = core_path.read_bytes()
            summary = run_supplement(
                workspace,
                run_id="supplement-full",
                source_run_id=SOURCE_RUN_ID,
                arxiv_ids=[ARXIV_ID],
                supplement_type="full_fields",
                adapter=fake_supplement_adapter,
            )
            output = (
                workspace
                / "benchmark/campaigns/hvs-extraction-v6/supplements"
                / "supplement-full"
                / summary["outputs"][ARXIV_ID]
            )
            artifact = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                artifact["schema"],
                {"name": "full_fields_supplement", "version": 1},
            )
            self.assertEqual(
                artifact["core_artifact_sha256"], sha256_file(core_path)
            )
            self.assertEqual(
                artifact["records"][0]["record_id"], "candidate-001"
            )
            self.assertNotIn("core", artifact["records"][0])
            self.assertEqual(core_path.read_bytes(), before)

    def test_fake_method_chain_adapter_has_separate_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, _ = make_source_run(tmp)
            summary = run_supplement(
                workspace,
                run_id="supplement-method",
                source_run_id=SOURCE_RUN_ID,
                arxiv_ids=[ARXIV_ID],
                supplement_type="method_chain",
                adapter=fake_supplement_adapter,
            )
            output = (
                workspace
                / "benchmark/campaigns/hvs-extraction-v6/supplements"
                / "supplement-method"
                / summary["outputs"][ARXIV_ID]
            )
            artifact = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(
                artifact["schema"],
                {"name": "method_chain_supplement", "version": 1},
            )
            self.assertEqual(artifact["steps"], [])
            self.assertEqual(artifact["field_links"], [])
            self.assertNotIn("candidates", artifact)

    def test_method_chain_rejects_cycles_and_unknown_core_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, _ = make_source_run(tmp)

            def cyclic(_kind, _core):
                return {
                    "steps": [
                        {"id": "a", "depends_on": ["b"]},
                        {"id": "b", "depends_on": ["a"]},
                    ],
                    "field_links": [],
                }

            with self.assertRaisesRegex(ValueError, "DAG"):
                run_supplement(
                    workspace,
                    run_id="supplement-cycle",
                    source_run_id=SOURCE_RUN_ID,
                    arxiv_ids=[ARXIV_ID],
                    supplement_type="method_chain",
                    adapter=cyclic,
                )

        with tempfile.TemporaryDirectory() as tmp:
            workspace, _ = make_source_run(tmp)

            def unknown_field(_kind, _core):
                return {
                    "steps": [{"id": "a", "depends_on": []}],
                    "field_links": [
                        {
                            "record_id": "candidate-001",
                            "core_field_path": "unknown.value",
                            "step_id": "a",
                        }
                    ],
                }

            with self.assertRaisesRegex(ValueError, "unknown core field"):
                run_supplement(
                    workspace,
                    run_id="supplement-field",
                    source_run_id=SOURCE_RUN_ID,
                    arxiv_ids=[ARXIV_ID],
                    supplement_type="method_chain",
                    adapter=unknown_field,
                )


if __name__ == "__main__":
    unittest.main()
