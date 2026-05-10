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
    migrate_catalog_extraction_schema,
    migrate_external_resource_source_refs_in_review,
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
    (notes_dir / "2026-03.json").write_text(
        json.dumps(
            {
                "month": "2026-03",
                "papers": [
                    {
                        "arxiv_id": "2603.00001",
                        "title": "A catalog of hypervelocity stars",
                        "month": "2026-03",
                        "links": {
                            "abs": "https://arxiv.org/abs/2603.00001",
                            "pdf": "https://arxiv.org/pdf/2603.00001",
                        },
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (paper_dir / "audit.json").write_text(
        json.dumps(
            {
                "arxiv_id": "2603.00001",
                "title": "A catalog of hypervelocity stars",
                "month": "2026-03",
                "source_note_json": "notes/2026/2026-03/2026-03.json",
                "arxiv_source": {"extract_dir": "arxiv_source", "extracted": True},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (source_dir / "main.tex").write_text(
        r"""
\documentclass{article}
\begin{document}
\section{Catalog}
The full machine-readable catalog is available at \url{https://vizier.cds.unistra.fr/example}.
\begin{table}
\caption{Candidate hypervelocity stars}
\label{tab:hvs}
\begin{tabular}{cc}
Gaia DR3 source ID & v \\
1 & 700 \\
\end{tabular}
\end{table}
\begin{longtable}{cc}
\caption{Rejected foreground stars}
\label{tab:foreground}\\
source & reason \\
\end{longtable}
\begin{deluxetable}{cc}
\tablecaption{Spectroscopic follow-up targets}
\label{tab:followup}
\startdata
A & B
\enddata
\end{deluxetable}
\end{document}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (source_dir / "catalog_table.tbl").write_text("source_id velocity\n1 700\n", encoding="utf-8")
    (source_dir / "catalog_table.mrt").write_text("source_id velocity\n1 700\n", encoding="utf-8")
    (source_dir / "catalog_table.ecsv").write_text("# %ECSV 1.0\n", encoding="utf-8")
    return literature_dir


class CatalogReviewTest(unittest.TestCase):
    def test_migrate_external_tex_local_path_to_source_refs(self) -> None:
        review = {
            "external_catalog_sources": [
                {
                    "id": "resource-tex",
                    "kind": "external_url",
                    "url": "https://example.test/catalog.csv",
                    "local_path": "literature/2603.00001/arxiv_source/main.tex",
                    "evidence": "In main.tex line 42: machine-readable catalog is available.",
                },
                {
                    "id": "resource-local-table",
                    "kind": "local_machine_readable_file",
                    "local_path": "literature/2603.00001/arxiv_source/table.mrt",
                },
            ]
        }

        migrated, summary = migrate_external_resource_source_refs_in_review(review)

        self.assertEqual(summary["migrated_count"], 1)
        self.assertEqual(migrated["external_catalog_sources"][0]["local_path"], "")
        self.assertEqual(
            migrated["external_catalog_sources"][0]["source_refs"],
            [
                {
                    "path": "literature/2603.00001/arxiv_source/main.tex",
                    "start_line": 42,
                    "end_line": 42,
                    "context": "In main.tex line 42: machine-readable catalog is available.",
                    "source": "migrated_from_external_catalog_sources.local_path",
                }
            ],
        )
        self.assertEqual(
            migrated["external_catalog_sources"][1]["local_path"],
            "literature/2603.00001/arxiv_source/table.mrt",
        )

    def test_migrate_legacy_catalog_source_fields(self) -> None:
        review = {
            "schema_version": "stella.hvs_catalog.review.v1",
            "catalog_candidates": [{"id": "table-1", "kind": "latex_table"}],
            "external_resources": [{"id": "resource-1", "kind": "external_url"}],
        }

        migrated, summary = migrate_external_resource_source_refs_in_review(review)

        self.assertEqual(migrated["schema_version"], "stella.hvs_catalog.review.v2")
        self.assertEqual(migrated["internal_tables"], [{"id": "table-1", "kind": "latex_table"}])
        self.assertEqual(migrated["external_catalog_sources"], [{"id": "resource-1", "kind": "external_url"}])
        self.assertNotIn("catalog_candidates", migrated)
        self.assertNotIn("external_resources", migrated)
        self.assertEqual(summary["schema_migrated_count"], 1)

    def test_migrate_legacy_extraction_fields(self) -> None:
        manifest = {
            "schema_version": "stella.hvs_catalog.extraction.v2",
            "runs": [{"options": {"candidate_id": "table-1", "resource_id": ""}}],
            "sources": [{"id": "table-1", "candidate_id": "table-1"}],
            "tables": [{"id": "resource-1", "resource_id": "resource-1"}],
            "external_resources": [{"id": "resource-1", "resource_id": "resource-1"}],
        }

        migrated, summary = migrate_catalog_extraction_schema(manifest)

        self.assertEqual(migrated["schema_version"], "stella.hvs_catalog.extraction.v3")
        self.assertIn("external_catalog_sources", migrated)
        self.assertNotIn("external_resources", migrated)
        self.assertEqual(migrated["sources"][0]["internal_table_id"], "table-1")
        self.assertNotIn("candidate_id", migrated["sources"][0])
        self.assertEqual(migrated["tables"][0]["external_source_id"], "resource-1")
        self.assertNotIn("resource_id", migrated["tables"][0])
        self.assertEqual(migrated["external_catalog_sources"][0]["external_source_id"], "resource-1")
        self.assertNotIn("resource_id", migrated["external_catalog_sources"][0])
        self.assertEqual(migrated["runs"][0]["options"]["internal_table_id"], "table-1")
        self.assertNotIn("candidate_id", migrated["runs"][0]["options"])
        self.assertNotIn("resource_id", migrated["runs"][0]["options"])
        self.assertEqual(summary["id_field_migrated_count"], 3)

    def test_inventory_finds_tex_tables_local_files_and_external_mentions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir = write_sample_archive(workspace)

            inventory = build_catalog_candidate_inventory(
                literature_dir=literature_dir,
                arxiv_id="2603.00001",
                workspace=workspace,
            )

            self.assertEqual(inventory["schema_version"], "stella.hvs_catalog.inventory.v1")
            self.assertEqual(inventory["paper"]["title"], "A catalog of hypervelocity stars")
            self.assertEqual(inventory["source"]["tex_file_count"], 1)
            tables = inventory["table_candidates"]
            self.assertEqual([table["environment"] for table in tables], ["table", "longtable", "deluxetable"])
            self.assertEqual(tables[0]["caption"], "Candidate hypervelocity stars")
            self.assertEqual(tables[0]["label"], "tab:hvs")
            self.assertGreaterEqual(tables[0]["start_line"], 4)
            self.assertGreater(tables[0]["end_line"], tables[0]["start_line"])
            local_paths = sorted(item["source_relative_path"] for item in inventory["local_machine_readable_files"])
            self.assertEqual(local_paths, ["catalog_table.ecsv", "catalog_table.mrt", "catalog_table.tbl"])
            self.assertEqual(
                inventory["external_resource_mentions"][0]["url"],
                "https://vizier.cds.unistra.fr/example",
            )

    def test_rebuild_catalog_index_summarizes_review_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir = workspace / "literature"
            paper_dir = literature_dir / "2603.00001"
            paper_dir.mkdir(parents=True)
            write_json_file(
                paper_dir / "catalog_review.json",
                {
                    "schema_version": "stella.hvs_catalog.review.v2",
                    "paper": {
                        "arxiv_id": "2603.00001",
                        "title": "A catalog of hypervelocity stars",
                        "month": "2026-03",
                    },
                    "review": {
                        "status": "reviewed",
                        "reviewed_at": "2026-04-24T12:00:00",
                    },
                    "internal_tables": [{"confidence": 0.9}],
                    "external_catalog_sources": [{"url": "https://vizier.example/catalog"}],
                    "rejected_candidates": [{"reason": "observing log"}],
                },
            )
            needs_dir = literature_dir / "2603.00002"
            needs_dir.mkdir(parents=True)
            write_json_file(
                needs_dir / "catalog_review.json",
                {
                    "schema_version": "stella.hvs_catalog.review.v2",
                    "paper": {
                        "arxiv_id": "2603.00002",
                        "title": "A paper needing review",
                        "month": "2026-03",
                    },
                    "review": {"status": "needs_review"},
                    "internal_tables": [],
                    "external_catalog_sources": [],
                    "rejected_candidates": [],
                },
            )

            index = rebuild_catalog_index(literature_dir, workspace=workspace)

            self.assertEqual(index["schema_version"], "stella.hvs_catalog.index.v2")
            self.assertEqual(index["summary"]["paper_count"], 2)
            self.assertEqual(index["summary"]["reviewed_count"], 1)
            self.assertEqual(index["summary"]["has_catalog_count"], 1)
            self.assertEqual(index["summary"]["has_catalog_source_count"], 1)
            self.assertEqual(index["summary"]["internal_table_count"], 1)
            self.assertEqual(index["summary"]["external_catalog_source_count"], 1)
            self.assertEqual(index["summary"]["needs_review_count"], 1)
            self.assertEqual(index["summary"]["extraction_not_started_count"], 1)
            self.assertEqual(index["summary"]["extraction_not_applicable_count"], 1)
            self.assertEqual(index["years"][0]["year"], "2026")
            self.assertEqual(index["years"][0]["has_catalog_count"], 1)
            self.assertEqual(index["years"][0]["has_catalog_source_count"], 1)
            with_catalog = next(item for item in index["papers"] if item["arxiv_id"] == "2603.00001")
            needs_review = next(item for item in index["papers"] if item["arxiv_id"] == "2603.00002")
            self.assertEqual(with_catalog["extraction_status"], "not_started")
            self.assertEqual(needs_review["extraction_status"], "not_applicable")

            markdown = render_catalog_index(index)
            self.assertIn("High-Velocity Star Catalog Workflow Index", markdown)
            self.assertIn("## Status Legend", markdown)
            self.assertIn("A catalog of hypervelocity stars (2603.00001)", markdown)
            self.assertIn(
                "| 2026 | 2 | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 1 | 1 |",
                markdown,
            )

    def test_rebuild_catalog_index_merges_extraction_manifest_and_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir = workspace / "literature"
            paper_dir = literature_dir / "2603.00001"
            write_json_file(
                paper_dir / "catalog_review.json",
                {
                    "schema_version": "stella.hvs_catalog.review.v2",
                    "paper": {
                        "arxiv_id": "2603.00001",
                        "title": "A partly extracted catalog",
                        "month": "2026-03",
                    },
                    "source": {"source_available": True},
                    "review": {"status": "reviewed"},
                    "internal_tables": [{"confidence": 0.8}],
                    "external_catalog_sources": [],
                    "rejected_candidates": [],
                },
            )
            write_json_file(
                paper_dir / "catalog_extraction.json",
                {
                    "schema_version": "stella.hvs_catalog.extraction.v3",
                    "generated_at": "2026-04-25T12:00:00",
                    "paper": {"arxiv_id": "2603.00001", "title": "A partly extracted catalog", "month": "2026-03"},
                    "runs": [{"status": "partial", "summary": {"success_count": 1, "failed_count": 1}}],
                    "tables": [
                        {
                            "id": "table-1",
                            "status": "success",
                            "usage": {"semantic_status": "reviewed"},
                            "columns": [
                                {"semantic_status": "reviewed"},
                                {"semantic_status": "reviewed"},
                                {"semantic_status": "needs_agent_review"},
                            ],
                        },
                        {
                            "id": "table-2",
                            "status": "failed",
                            "usage": {"semantic_status": "needs_agent_review"},
                            "columns": [],
                        },
                    ],
                    "external_catalog_sources": [
                        {"id": "resource-1", "status": "success"},
                        {"id": "resource-2", "status": "failed"},
                    ],
                },
            )
            external_dir = literature_dir / "2603.00002"
            write_json_file(
                external_dir / "catalog_review.json",
                {
                    "schema_version": "stella.hvs_catalog.review.v2",
                    "paper": {
                        "arxiv_id": "2603.00002",
                        "title": "External only catalog",
                        "month": "2026-03",
                    },
                    "source": {"source_available": True},
                    "review": {"status": "reviewed"},
                    "internal_tables": [],
                    "external_catalog_sources": [{"id": "resource-1", "url": "https://example.test/catalog.csv"}],
                    "rejected_candidates": [],
                },
            )
            inconsistent_dir = literature_dir / "2603.00003"
            write_json_file(
                inconsistent_dir / "catalog_review.json",
                {
                    "schema_version": "stella.hvs_catalog.review.v2",
                    "paper": {
                        "arxiv_id": "2603.00003",
                        "title": "Mislabelled source status",
                        "month": "2026-03",
                    },
                    "source": {"source_available": True},
                    "review": {"status": "source_missing"},
                    "internal_tables": [],
                    "external_catalog_sources": [],
                    "rejected_candidates": [],
                },
            )

            index = rebuild_catalog_index(literature_dir, workspace=workspace)

            self.assertEqual(index["summary"]["paper_count"], 3)
            self.assertEqual(index["summary"]["has_catalog_count"], 1)
            self.assertEqual(index["summary"]["has_catalog_source_count"], 2)
            self.assertEqual(index["summary"]["extraction_manifest_count"], 1)
            self.assertEqual(index["summary"]["extraction_partial_count"], 1)
            self.assertEqual(index["summary"]["extraction_not_started_count"], 1)
            self.assertEqual(index["summary"]["extraction_not_applicable_count"], 1)
            self.assertEqual(index["summary"]["table_success_count"], 1)
            self.assertEqual(index["summary"]["table_failed_count"], 1)
            self.assertEqual(index["summary"]["external_success_count"], 1)
            self.assertEqual(index["summary"]["external_failed_count"], 1)
            self.assertEqual(index["summary"]["semantic_usage_reviewed_count"], 1)
            self.assertEqual(index["summary"]["semantic_column_reviewed_count"], 2)
            self.assertEqual(index["summary"]["semantic_column_count"], 3)
            self.assertEqual(index["summary"]["review_status_warning_count"], 1)

            extracted = next(item for item in index["papers"] if item["arxiv_id"] == "2603.00001")
            self.assertEqual(extracted["extraction_status"], "partial")
            self.assertEqual(extracted["last_extraction_run_status"], "partial")
            self.assertEqual(extracted["extraction_json_path"], "literature/2603.00001/catalog_extraction.json")
            self.assertEqual(extracted["semantic_column_reviewed_count"], 2)
            self.assertEqual(extracted["semantic_column_count"], 3)

            external_only = next(item for item in index["papers"] if item["arxiv_id"] == "2603.00002")
            self.assertFalse(external_only["has_catalog"])
            self.assertTrue(external_only["has_catalog_source"])
            self.assertEqual(external_only["extraction_status"], "not_started")

            inconsistent = next(item for item in index["papers"] if item["arxiv_id"] == "2603.00003")
            self.assertEqual(inconsistent["extraction_status"], "not_applicable")
            self.assertIn("source_available=true", inconsistent["review_status_warning"])

            markdown = render_catalog_index(index)
            self.assertIn("source_missing", markdown)
            self.assertIn("[JSON](literature/2603.00001/catalog_extraction.json)", markdown)
            self.assertIn("1 usage, 2/3 cols", markdown)

    def test_write_catalog_index_outputs_writes_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir = workspace / "literature"
            paper_dir = literature_dir / "2603.00001"
            paper_dir.mkdir(parents=True)
            (paper_dir / "catalog_review.json").write_text(
                json.dumps(
                    {
                        "paper": {"arxiv_id": "2603.00001", "title": "Reviewed", "month": "2026-03"},
                        "review": {"status": "reviewed"},
                        "internal_tables": [],
                        "external_catalog_sources": [],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = write_catalog_index_outputs(literature_dir, workspace=workspace)

            self.assertTrue(Path(result["index_json_path"]).exists())
            self.assertTrue(Path(result["index_markdown_path"]).exists())
            self.assertIn("Reviewed", Path(result["index_markdown_path"]).read_text(encoding="utf-8"))

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
            self.assertEqual(len(payload["table_candidates"]), 3)
            self.assertFalse((literature_dir / "2603.00001" / "catalog_review.json").exists())

    def test_build_catalog_index_cli_writes_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            literature_dir = Path(tmp) / "literature"
            paper_dir = literature_dir / "2603.00001"
            paper_dir.mkdir(parents=True)
            (paper_dir / "catalog_review.json").write_text(
                json.dumps(
                    {
                        "paper": {"arxiv_id": "2603.00001", "title": "Reviewed", "month": "2026-03"},
                        "review": {"status": "reviewed"},
                        "internal_tables": [{"confidence": 1.0}],
                        "external_catalog_sources": [],
                    }
                )
                + "\n",
                encoding="utf-8",
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
