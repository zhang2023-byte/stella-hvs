from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from high_velocity_lit.schema_models import CatalogReviewRecord, LiteratureHvsCandidatesRecord  # noqa: E402
from high_velocity_lit.schema_templates import (  # noqa: E402
    build_catalog_review_template,
    build_hvs_candidates_template,
    empty_candidate_core,
)

REVIEW_VALIDATOR_SCRIPT = ROOT / "scripts" / "validate_catalog_review.py"
REVIEW_VALIDATOR_SPEC = importlib.util.spec_from_file_location("validate_catalog_review", REVIEW_VALIDATOR_SCRIPT)
assert REVIEW_VALIDATOR_SPEC is not None and REVIEW_VALIDATOR_SPEC.loader is not None
review_validator = importlib.util.module_from_spec(REVIEW_VALIDATOR_SPEC)
REVIEW_VALIDATOR_SPEC.loader.exec_module(review_validator)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_archive_fixture(workspace: Path) -> Path:
    literature_dir = workspace / "literature"
    paper_dir = literature_dir / "2603.00001"
    source_dir = paper_dir / "arxiv_source"
    source_dir.mkdir(parents=True)
    write_json(
        workspace / "notes" / "2026" / "2026-03" / "2026-03.json",
        {
            "papers": [
                {
                    "arxiv_id": "2603.00001",
                    "title": "Schema template paper",
                    "month": "2026-03",
                    "links": {"abs": "https://arxiv.org/abs/2603.00001", "pdf": "https://arxiv.org/pdf/2603.00001"},
                }
            ]
        },
    )
    write_json(
        paper_dir / "audit.json",
        {
            "arxiv_id": "2603.00001",
            "title": "Schema template paper",
            "month": "2026-03",
            "source_note_json": "notes/2026/2026-03/2026-03.json",
            "arxiv_source": {"extract_dir": "arxiv_source", "extracted": True},
            "ads_metadata": {"local_path": "literature/2603.00001/ads_metadata.json"},
        },
    )
    write_json(
        paper_dir / "ads_metadata.json",
        {"response": {"docs": [{"bibcode": "2026MNRAS.123..456S"}]}},
    )
    (source_dir / "main.tex").write_text(
        "\n".join(
            [
                r"\documentclass{article}",
                r"\begin{document}",
                r"Data are available at \url{https://example.test/catalog}.",
                r"\begin{table}",
                r"\caption{Candidate list}",
                r"\label{tab:candidates}",
                r"\begin{tabular}{cc}",
                r"Name & velocity \\",
                r"HVS1 & 701 \\",
                r"\end{tabular}",
                r"\end{table}",
                r"\end{document}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return literature_dir


class SchemaTemplateTest(unittest.TestCase):
    def test_catalog_review_template_is_schema_valid_and_source_checkable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir = write_archive_fixture(workspace)

            payload = build_catalog_review_template(
                literature_dir=literature_dir,
                arxiv_id="2603.00001",
                workspace=workspace,
            )

            CatalogReviewRecord.model_validate(payload)
            self.assertEqual(payload["review"]["status"], "needs_review")
            self.assertEqual(payload["internal_tables"][0]["source_refs"][0]["label"], "tab:candidates")
            self.assertEqual([column["name"] for column in payload["internal_tables"][0]["columns"]], ["Name", "velocity"])
            self.assertEqual(payload["external_resources"][0]["url"], "https://example.test/catalog")
            self.assertEqual(review_validator.validate_catalog_review(payload, workspace=workspace), [])
            self.assertTrue(
                any(
                    "needs_review" in error
                    for error in review_validator.validate_catalog_review(
                        payload,
                        workspace=workspace,
                        require_complete=True,
                    )
                )
            )

    def test_hvs_candidates_template_is_schema_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir = write_archive_fixture(workspace)
            paper_dir = literature_dir / "2603.00001"
            write_json(paper_dir / "catalog_review.json", build_catalog_review_template(literature_dir=literature_dir, arxiv_id="2603.00001", workspace=workspace))
            write_json(
                paper_dir / "catalog_extraction.json",
                {
                    "schema_version": "stella.article_data_assets.extraction.v2",
                    "generated_at": "2026-05-12T12:00:00",
                    "paper": {"arxiv_id": "2603.00001", "title": "Schema template paper", "month": "2026-03"},
                    "review": {
                        "path": "literature/2603.00001/catalog_review.json",
                        "schema_version": "stella.article_data_assets.review.v1",
                        "review_status": "reviewed",
                    },
                    "run": {
                        "run_id": "catalog-extraction-20260512120000",
                        "started_at": "2026-05-12T12:00:00",
                        "tool": "scripts/extract_catalog_tables.py",
                        "options": {"arxiv_id": "2603.00001", "internal_table_id": None, "dry_run": False, "overwrite": False},
                        "summary": {
                            "internal_table_count": 1,
                            "work_count": 1,
                            "table_count": 1,
                            "success_count": 1,
                            "failed_count": 0,
                            "deferred_count": 0,
                            "file_count": 1,
                            "file_success_count": 1,
                            "file_failed_count": 0,
                        },
                        "status": "success",
                    },
                    "files": [],
                    "tables": [
                        {
                            "id": "table-tab-candidates",
                            "internal_table_id": "table-tab-candidates",
                            "status": "success",
                            "ecsv_path": "literature/2603.00001/catalog_tables/table-tab-candidates.ecsv",
                            "caption": "Candidate list",
                            "label": "tab:candidates",
                            "row_count": 1,
                            "column_count": 2,
                            "environment": "tabular",
                            "header_rows": [["Name", "velocity"]],
                            "columns": [],
                            "warnings": [],
                            "error": "",
                            "extraction_method": "internal",
                            "conversion_attempts": [],
                            "source_sha256": "",
                        }
                    ],
                },
            )

            payload = build_hvs_candidates_template(
                literature_dir=literature_dir,
                arxiv_id="2603.00001",
                workspace=workspace,
            )

            LiteratureHvsCandidatesRecord.model_validate(payload)
            self.assertEqual(payload["extraction"]["status"], "needs_review")
            self.assertEqual(payload["inputs"]["ecsv_paths"], ["literature/2603.00001/catalog_tables/table-tab-candidates.ecsv"])
            self.assertEqual(set(empty_candidate_core()), {"observed_phase_space", "derived_kinematics", "probabilities"})


if __name__ == "__main__":
    unittest.main()
