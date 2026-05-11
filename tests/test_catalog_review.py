from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from high_velocity_lit.catalog_review import (  # noqa: E402
    build_catalog_candidate_inventory,
    cleanup_catalog_workflow_outputs,
    rebuild_catalog_index,
    render_catalog_index,
    write_catalog_index_outputs,
)

INVENTORY_SCRIPT = ROOT / "scripts" / "inventory_catalog_candidates.py"
INVENTORY_SPEC = importlib.util.spec_from_file_location("inventory_catalog_candidates", INVENTORY_SCRIPT)
assert INVENTORY_SPEC is not None and INVENTORY_SPEC.loader is not None
inventory_cli = importlib.util.module_from_spec(INVENTORY_SPEC)
INVENTORY_SPEC.loader.exec_module(inventory_cli)

INDEX_SCRIPT = ROOT / "scripts" / "build_catalog_index.py"
INDEX_SPEC = importlib.util.spec_from_file_location("build_catalog_index", INDEX_SCRIPT)
assert INDEX_SPEC is not None and INDEX_SPEC.loader is not None
index_cli = importlib.util.module_from_spec(INDEX_SPEC)
INDEX_SPEC.loader.exec_module(index_cli)


def write_json_file(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_sample_archive(workspace: Path) -> Path:
    literature_dir = workspace / "literature"
    paper_dir = literature_dir / "2603.00001"
    source_dir = paper_dir / "arxiv_source"
    notes_dir = workspace / "notes" / "2026" / "2026-03"
    source_dir.mkdir(parents=True)
    notes_dir.mkdir(parents=True)
    write_json_file(
        notes_dir / "2026-03.json",
        {
            "month": "2026-03",
            "papers": [
                {
                    "arxiv_id": "2603.00001",
                    "title": "A paper with structured data assets",
                    "month": "2026-03",
                    "links": {
                        "abs": "https://arxiv.org/abs/2603.00001",
                        "pdf": "https://arxiv.org/pdf/2603.00001",
                    },
                }
            ],
        },
    )
    write_json_file(
        paper_dir / "audit.json",
        {
            "arxiv_id": "2603.00001",
            "title": "A paper with structured data assets",
            "month": "2026-03",
            "source_note_json": "notes/2026/2026-03/2026-03.json",
            "arxiv_source": {"extract_dir": "arxiv_source", "extracted": True},
        },
    )
    (source_dir / "main.tex").write_text(
        r"""
\documentclass{article}
\begin{document}
The machine-readable data assets are available at \url{https://vizier.cds.unistra.fr/example}.
\begin{table}
\caption{Candidate list}
\label{tab:candidates}
\begin{tabular}{cc}
Name & velocity \\
A & 700 \\
\end{tabular}
\end{table}
\begin{longtable}{cc}
\caption{Observation log}
\label{tab:obslog}\\
target & exposure \\
\end{longtable}
\end{document}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (source_dir / "data.tbl").write_text("name velocity\nA 700\n", encoding="utf-8")
    (source_dir / "data.ecsv").write_text("# %ECSV 1.0\n", encoding="utf-8")
    return literature_dir


class CatalogReviewTest(unittest.TestCase):
    def test_inventory_finds_tables_local_files_and_external_mentions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir = write_sample_archive(workspace)

            inventory = build_catalog_candidate_inventory(
                literature_dir=literature_dir,
                arxiv_id="2603.00001",
                workspace=workspace,
            )

            self.assertEqual(inventory["schema_version"], "stella.article_data_assets.inventory.v1")
            self.assertEqual(inventory["paper"]["title"], "A paper with structured data assets")
            self.assertEqual([table["environment"] for table in inventory["table_candidates"]], ["table", "longtable"])
            self.assertEqual(inventory["table_candidates"][0]["caption"], "Candidate list")
            self.assertEqual(inventory["table_candidates"][0]["label"], "tab:candidates")
            self.assertEqual(
                sorted(item["source_relative_path"] for item in inventory["local_machine_readable_files"]),
                ["data.ecsv", "data.tbl"],
            )
            self.assertEqual(inventory["external_resource_mentions"][0]["url"], "https://vizier.cds.unistra.fr/example")

    def test_rebuild_catalog_index_summarizes_data_asset_review_and_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir = workspace / "literature"
            paper_dir = literature_dir / "2603.00001"
            write_json_file(
                paper_dir / "catalog_review.json",
                {
                    "schema_version": "stella.article_data_assets.review.v1",
                    "paper": {"arxiv_id": "2603.00001", "title": "Reviewed assets", "month": "2026-03"},
                    "source": {"source_available": True},
                    "review": {"status": "reviewed", "reviewed_at": "2026-04-24T12:00:00"},
                    "internal_tables": [{"id": "table-1", "asset_type": "object_measurement_table"}],
                    "external_resources": [{"id": "resource-1", "url": "https://example.test/readme"}],
                },
            )
            write_json_file(
                paper_dir / "catalog_extraction.json",
                {
                    "schema_version": "stella.article_data_assets.extraction.v2",
                    "generated_at": "2026-04-25T12:00:00",
                    "paper": {"arxiv_id": "2603.00001", "title": "Reviewed assets", "month": "2026-03"},
                    "run": {"status": "success", "summary": {"success_count": 1, "failed_count": 0}},
                    "tables": [{"id": "table-1", "status": "success", "ecsv_path": "literature/2603.00001/catalog_tables/table-1.ecsv"}],
                    "files": [{"id": "table-1", "status": "written", "excerpt_path": "literature/2603.00001/catalog_sources/table-1/excerpt.tex"}],
                },
            )
            needs_dir = literature_dir / "2603.00002"
            write_json_file(
                needs_dir / "catalog_review.json",
                {
                    "schema_version": "stella.article_data_assets.review.v1",
                    "paper": {"arxiv_id": "2603.00002", "title": "Needs review", "month": "2026-03"},
                    "review": {"status": "needs_review"},
                    "internal_tables": [],
                    "external_resources": [],
                },
            )
            external_only_dir = literature_dir / "2603.00003"
            write_json_file(
                external_only_dir / "catalog_review.json",
                {
                    "schema_version": "stella.article_data_assets.review.v1",
                    "paper": {"arxiv_id": "2603.00003", "title": "External only", "month": "2026-03"},
                    "review": {"status": "reviewed", "reviewed_at": "2026-04-24T13:00:00"},
                    "internal_tables": [],
                    "external_resources": [{"id": "resource-2", "description": "External archive described by the paper."}],
                },
            )

            index = rebuild_catalog_index(literature_dir, workspace=workspace)

            self.assertEqual(index["schema_version"], "stella.article_data_assets.index.v1")
            self.assertEqual(index["summary"]["paper_count"], 3)
            self.assertEqual(index["summary"]["reviewed_count"], 2)
            self.assertEqual(index["summary"]["has_data_asset_count"], 2)
            self.assertEqual(index["summary"]["has_internal_table_count"], 1)
            self.assertEqual(index["summary"]["internal_table_count"], 1)
            self.assertEqual(index["summary"]["external_resource_count"], 2)
            self.assertEqual(index["summary"]["extraction_success_count"], 1)
            self.assertEqual(index["summary"]["extraction_not_applicable_count"], 2)
            self.assertEqual(index["summary"]["table_success_count"], 1)
            self.assertEqual(index["summary"]["file_success_count"], 1)

            markdown = render_catalog_index(index)
            self.assertIn("Article Data Asset Workflow Index", markdown)
            self.assertIn("Reviewed assets (2603.00001)", markdown)
            self.assertIn("1 table, 1 external", markdown)
            self.assertIn("1 files, 0 failed", markdown)

    def test_write_catalog_index_outputs_writes_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir = workspace / "literature"
            paper_dir = literature_dir / "2603.00001"
            write_json_file(
                paper_dir / "catalog_review.json",
                {
                    "paper": {"arxiv_id": "2603.00001", "title": "Reviewed", "month": "2026-03"},
                    "review": {"status": "reviewed"},
                    "internal_tables": [],
                    "external_resources": [],
                },
            )

            result = write_catalog_index_outputs(literature_dir, workspace=workspace)

            self.assertTrue(Path(result["index_json_path"]).exists())
            self.assertTrue(Path(result["index_markdown_path"]).exists())
            self.assertIn("Reviewed", Path(result["index_markdown_path"]).read_text(encoding="utf-8"))

    def test_cleanup_catalog_workflow_outputs_preserves_archived_paper_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            literature_dir = Path(tmp) / "literature"
            paper_dir = literature_dir / "2603.00001"
            (paper_dir / "arxiv_source").mkdir(parents=True)
            (paper_dir / "catalog_sources" / "table-1").mkdir(parents=True)
            (paper_dir / "catalog_tables").mkdir()
            for path in (
                paper_dir / "catalog_review.json",
                paper_dir / "catalog_extraction.json",
                literature_dir / "catalog_workflow_index.json",
                literature_dir / "catalog_workflow_index.md",
                paper_dir / "audit.json",
                paper_dir / "arxiv_source" / "main.tex",
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}", encoding="utf-8")

            payload = cleanup_catalog_workflow_outputs(literature_dir)

            self.assertEqual(payload["removed_count"], 6)
            self.assertFalse((paper_dir / "catalog_review.json").exists())
            self.assertFalse((paper_dir / "catalog_extraction.json").exists())
            self.assertFalse((paper_dir / "catalog_sources").exists())
            self.assertFalse((paper_dir / "catalog_tables").exists())
            self.assertTrue((paper_dir / "audit.json").exists())
            self.assertTrue((paper_dir / "arxiv_source" / "main.tex").exists())

    def test_inventory_cli_prints_candidates_without_writing_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir = write_sample_archive(workspace)

            with patch.object(
                sys,
                "argv",
                [
                    "inventory_catalog_candidates.py",
                    "--arxiv-id",
                    "2603.00001",
                    "--literature-dir",
                    str(literature_dir),
                ],
            ):
                with patch("builtins.print") as fake_print:
                    exit_code = inventory_cli.main()

            self.assertEqual(exit_code, 0)
            payload = json.loads(fake_print.call_args.args[0])
            self.assertEqual(len(payload["table_candidates"]), 2)
            self.assertFalse((literature_dir / "2603.00001" / "catalog_review.json").exists())

    def test_build_catalog_index_cli_writes_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            literature_dir = Path(tmp) / "literature"
            paper_dir = literature_dir / "2603.00001"
            write_json_file(
                paper_dir / "catalog_review.json",
                {
                    "paper": {"arxiv_id": "2603.00001", "title": "Reviewed", "month": "2026-03"},
                    "review": {"status": "reviewed"},
                    "internal_tables": [{"id": "table-1"}],
                    "external_resources": [],
                },
            )

            with patch.object(
                sys,
                "argv",
                [
                    "build_catalog_index.py",
                    "--literature-dir",
                    str(literature_dir),
                ],
            ):
                with patch("builtins.print"):
                    exit_code = index_cli.main()

            self.assertEqual(exit_code, 0)
            self.assertTrue((literature_dir / "catalog_workflow_index.json").exists())
            self.assertTrue((literature_dir / "catalog_workflow_index.md").exists())


if __name__ == "__main__":
    unittest.main()
