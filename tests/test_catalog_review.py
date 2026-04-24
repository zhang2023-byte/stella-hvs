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
    return literature_dir


class CatalogReviewTest(unittest.TestCase):
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
            self.assertEqual(inventory["local_machine_readable_files"][0]["source_relative_path"], "catalog_table.tbl")
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
            (paper_dir / "catalog_review.json").write_text(
                json.dumps(
                    {
                        "schema_version": "stella.hvs_catalog.review.v1",
                        "paper": {
                            "arxiv_id": "2603.00001",
                            "title": "A catalog of hypervelocity stars",
                            "month": "2026-03",
                        },
                        "review": {
                            "status": "reviewed",
                            "reviewed_at": "2026-04-24T12:00:00",
                        },
                        "catalog_candidates": [{"confidence": 0.9}],
                        "external_resources": [{"url": "https://vizier.example/catalog"}],
                        "rejected_candidates": [{"reason": "observing log"}],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            needs_dir = literature_dir / "2603.00002"
            needs_dir.mkdir(parents=True)
            (needs_dir / "catalog_review.json").write_text(
                json.dumps(
                    {
                        "schema_version": "stella.hvs_catalog.review.v1",
                        "paper": {
                            "arxiv_id": "2603.00002",
                            "title": "A paper needing review",
                            "month": "2026-03",
                        },
                        "review": {"status": "needs_review"},
                        "catalog_candidates": [],
                        "external_resources": [],
                        "rejected_candidates": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            index = rebuild_catalog_index(literature_dir, workspace=workspace)

            self.assertEqual(index["schema_version"], "stella.hvs_catalog.index.v1")
            self.assertEqual(index["summary"]["paper_count"], 2)
            self.assertEqual(index["summary"]["reviewed_count"], 1)
            self.assertEqual(index["summary"]["has_catalog_count"], 1)
            self.assertEqual(index["summary"]["needs_review_count"], 1)
            self.assertEqual(index["years"][0]["year"], "2026")
            self.assertEqual(index["years"][0]["has_catalog_count"], 1)

            markdown = render_catalog_index(index)
            self.assertIn("High-Velocity Star Catalog Review Index", markdown)
            self.assertIn("A catalog of hypervelocity stars (2603.00001)", markdown)
            self.assertIn("| 2026 | 2 | 1 | 1 | 1 |", markdown)

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
                        "catalog_candidates": [],
                        "external_resources": [],
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
                        "catalog_candidates": [{"confidence": 1.0}],
                        "external_resources": [],
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
            self.assertTrue((literature_dir / "catalog_index.json").exists())
            self.assertTrue((literature_dir / "catalog_index.md").exists())


if __name__ == "__main__":
    unittest.main()
