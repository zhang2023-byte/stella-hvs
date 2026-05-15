from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from astropy.io import ascii

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from high_velocity_lit.catalog_extraction import (  # noqa: E402
    auto_catalog_jobs,
    conversion_attempt_record,
    extract_all_reviewed_catalog_tables,
    extract_catalog_tables,
    parse_latex_table_excerpt,
)

SCRIPT = ROOT / "scripts" / "extract_catalog_tables.py"
SPEC = importlib.util.spec_from_file_location("extract_catalog_tables", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
extract_cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(extract_cli)

VALIDATE_SCRIPT = ROOT / "scripts" / "validate_catalog_extraction.py"
VALIDATE_SPEC = importlib.util.spec_from_file_location("validate_catalog_extraction", VALIDATE_SCRIPT)
assert VALIDATE_SPEC is not None and VALIDATE_SPEC.loader is not None
validate_cli = importlib.util.module_from_spec(VALIDATE_SPEC)
VALIDATE_SPEC.loader.exec_module(validate_cli)


def write_json_file(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ecsv_rows(path: Path) -> list[list[str]]:
    table = ascii.read(path, format="ecsv")
    return [[str(row[name]) for name in table.colnames] for row in table]


def write_review_fixture(workspace: Path, *, external_resources: list[dict[str, object]] | None = None) -> tuple[Path, Path]:
    literature_dir = workspace / "literature"
    paper_dir = literature_dir / "2603.00001"
    source_dir = paper_dir / "arxiv_source"
    source_dir.mkdir(parents=True)
    tex_path = source_dir / "main.tex"
    tex_path.write_text(
        r"""
\begin{table}
\caption{Structured data table}
\label{tab:data}
\begin{tabular}{cc}
Name & velocity \\
HVS1 & 700 \\
HVS2 & 710 \\
\end{tabular}
\end{table}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    write_json_file(
        paper_dir / "catalog_review.json",
        {
            "schema_version": "stella.article_data_assets.review.v1",
            "paper": {"arxiv_id": "2603.00001", "title": "Structured data", "month": "2026-03"},
            "source": {"paper_dir": "literature/2603.00001", "source_available": True},
            "review": {"status": "reviewed"},
            "internal_tables": [
                {
                    "id": "table-data",
                    "kind": "latex_table",
                    "asset_type": "object_measurement_table",
                    "role_in_paper": "Example structured table.",
                    "source_refs": [
                        {
                            "path": str(tex_path.relative_to(workspace)),
                            "start_line": 1,
                            "end_line": 9,
                            "caption": "Structured data table",
                            "label": "tab:data",
                        }
                    ],
                    "columns": [
                        {"name": "Name", "meaning": "Object identifier."},
                        {"name": "velocity", "meaning": "Velocity value."},
                    ],
                }
            ],
            "external_resources": external_resources or [],
        },
    )
    return literature_dir, paper_dir


class CatalogExtractionTest(unittest.TestCase):
    def test_cli_exposes_internal_table_extraction_options(self) -> None:
        parser = extract_cli.build_parser()
        args = parser.parse_args(["--arxiv-id", "2603.00001", "--internal-table-id", "table-data"])

        self.assertEqual(args.internal_table_id, "table-data")
        self.assertFalse(hasattr(args, "external_resource_id"))
        self.assertFalse(hasattr(args, "fetch_external"))
        self.assertFalse(hasattr(args, "agent_locator"))

    def test_cli_accepts_auto_jobs(self) -> None:
        parser = extract_cli.build_parser()
        args = parser.parse_args(["--all-reviewed", "--jobs", "Auto"])

        self.assertEqual(args.jobs, "Auto")

    def test_auto_catalog_jobs_scales_with_paper_count(self) -> None:
        self.assertEqual(auto_catalog_jobs(1), 1)
        self.assertEqual(auto_catalog_jobs(8), 2)
        self.assertEqual(auto_catalog_jobs(30), 4)
        self.assertEqual(auto_catalog_jobs(80), 8)
        self.assertEqual(auto_catalog_jobs(120), 12)

    def test_parse_simple_latex_table_to_generic_columns(self) -> None:
        parsed = parse_latex_table_excerpt(
            r"""
\begin{tabular}{cc}
Name & v \\
HVS1 & 700 \\
\end{tabular}
"""
        )

        self.assertEqual(parsed["status"], "success")
        self.assertEqual([column["name"] for column in parsed["columns"]], ["col_001", "col_002"])
        self.assertEqual(parsed["columns"][0]["original_header"], "Name")
        self.assertNotIn("physical_quantity", parsed["columns"][0])
        self.assertEqual(parsed["data_rows"], [["HVS1", "700"]])

    def test_conversion_attempt_records_artifact_paths_not_log_tails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            attempt = conversion_attempt_record(
                method="latexml",
                status="success",
                command=["latexmlc"],
                error="",
                artifacts={
                    "stdout": str(workspace / "literature/2603.00001/catalog_sources/table-data/latexml.stdout.txt"),
                    "stderr": str(workspace / "literature/2603.00001/catalog_sources/table-data/latexml.stderr.txt"),
                },
                workspace=workspace,
            )

            self.assertEqual(attempt["artifacts"]["stdout"], "literature/2603.00001/catalog_sources/table-data/latexml.stdout.txt")
            self.assertEqual(attempt["artifacts"]["stderr"], "literature/2603.00001/catalog_sources/table-data/latexml.stderr.txt")
            self.assertNotIn("stdout_tail", attempt)
            self.assertNotIn("stderr_tail", attempt)

    def test_extract_internal_latex_table_writes_ecsv_single_run_and_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir, paper_dir = write_review_fixture(workspace)

            result = extract_catalog_tables(
                literature_dir=literature_dir,
                arxiv_id="2603.00001",
                workspace=workspace,
            )

            manifest = result["manifest"]
            ecsv_path = paper_dir / "catalog_tables" / "table-data.ecsv"
            self.assertTrue(ecsv_path.exists())
            self.assertEqual(ecsv_rows(ecsv_path), [["HVS1", "700"], ["HVS2", "710"]])
            self.assertIn("run", manifest)
            self.assertNotIn("runs", manifest)
            self.assertEqual(manifest["run"]["status"], "success")
            self.assertEqual(manifest["tables"][0]["ecsv_path"], "literature/2603.00001/catalog_tables/table-data.ecsv")
            self.assertEqual(manifest["files"][0]["excerpt_path"], "literature/2603.00001/catalog_sources/table-data/excerpt.tex")
            self.assertNotIn("stdout_tail", manifest["tables"][0]["conversion_attempts"][0])
            self.assertNotIn("stderr_tail", manifest["tables"][0]["conversion_attempts"][0])
            self.assertEqual(validate_cli.validate_catalog_extraction(manifest, workspace=workspace), [])
            self.assertEqual(
                validate_cli.validate_catalog_extraction(
                    manifest,
                    workspace=workspace,
                    require_reviewed=True,
                ),
                [],
            )

            extract_catalog_tables(
                literature_dir=literature_dir,
                arxiv_id="2603.00001",
                workspace=workspace,
                internal_table_id="table-data",
            )
            updated = json.loads((paper_dir / "catalog_extraction.json").read_text(encoding="utf-8"))
            self.assertIn("run", updated)
            self.assertNotIn("runs", updated)
            self.assertEqual(updated["run"]["options"]["internal_table_id"], "table-data")
            self.assertNotIn("external_resources", updated)

    def test_all_reviewed_processes_reviewed_data_asset_papers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir, _ = write_review_fixture(workspace)
            write_json_file(
                literature_dir / "2603.00003" / "catalog_review.json",
                {
                    "schema_version": "stella.article_data_assets.review.v1",
                    "paper": {"arxiv_id": "2603.00003", "title": "External only", "month": "2026-03"},
                    "review": {"status": "reviewed"},
                    "internal_tables": [],
                    "external_resources": [{"id": "resource-readme", "description": "ReadMe described by the paper."}],
                },
            )
            write_json_file(
                literature_dir / "2603.00002" / "catalog_review.json",
                {
                    "schema_version": "stella.article_data_assets.review.v1",
                    "paper": {"arxiv_id": "2603.00002", "title": "No data", "month": "2026-03"},
                    "review": {"status": "reviewed"},
                    "internal_tables": [],
                    "external_resources": [],
                },
            )

            result = extract_all_reviewed_catalog_tables(
                literature_dir=literature_dir,
                workspace=workspace,
            )

            self.assertEqual(result["paper_count"], 1)
            self.assertEqual(result["summary"]["internal_table_count"], 1)
            self.assertEqual(result["summary"]["file_success_count"], 1)


if __name__ == "__main__":
    unittest.main()
