"""The catalog review template builds a schema-valid record.

Restored from the base suite with the retired scripts/ validator and the
candidate-era template dropped: the maintained Pydantic record is the
validator, and source-refs remain checkable against the workspace.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from stella.lit.schema_models import CatalogReviewRecord
from stella.lit.schema_templates import build_catalog_review_template


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


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
                    "links": {
                        "abs": "https://arxiv.org/abs/2603.00001",
                        "pdf": "https://arxiv.org/pdf/2603.00001",
                    },
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
            "ads_metadata": {
                "local_path": "literature/2603.00001/ads_metadata.json"
            },
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
            self.assertEqual(
                payload["internal_tables"][0]["source_refs"][0]["label"],
                "tab:candidates",
            )
            self.assertEqual(
                [column["name"] for column in payload["internal_tables"][0]["columns"]],
                ["Name", "velocity"],
            )
            self.assertEqual(
                payload["external_resources"][0]["url"],
                "https://example.test/catalog",
            )
            # Every declared source ref points at a real file and line.
            for table in payload["internal_tables"]:
                for ref in table["source_refs"]:
                    source = workspace / ref["path"]
                    self.assertTrue(source.is_file(), ref["path"])
                    lines = source.read_text(encoding="utf-8").splitlines()
                    self.assertGreaterEqual(len(lines), ref["start_line"])
            for resource in payload["external_resources"]:
                for ref in resource["source_refs"]:
                    source = workspace / ref["path"]
                    self.assertTrue(source.is_file(), ref["path"])


if __name__ == "__main__":
    unittest.main()
