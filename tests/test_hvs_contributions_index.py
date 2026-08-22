"""Paper-level contribution index tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.test_hvs_contribution_scoring import ai_document
from stella.lit.hvs_contributions_index import (
    build_hvs_contributions_index,
    write_hvs_contributions_index_outputs,
)


def write_paper(literature_dir: Path, arxiv_id: str, document: dict) -> Path:
    paper_dir = literature_dir / arxiv_id
    paper_dir.mkdir(parents=True)
    path = paper_dir / "literature_hvs_contributions.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


class HvsContributionsIndexTest(unittest.TestCase):
    def test_index_counts_and_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            literature_dir = Path(tmp)
            document = ai_document()
            write_paper(literature_dir, "2601.00001", document)
            failed = ai_document()
            failed["extraction"]["status"] = "failed"
            failed["extraction"]["roster_status"] = None
            failed["object_contributions"] = []
            write_paper(literature_dir, "2601.00002", failed)
            record = build_hvs_contributions_index(literature_dir)
            self.assertEqual(
                record["schema"],
                {"name": "literature_hvs_contributions.index", "version": 1},
            )
            summary = record["summary"]
            self.assertEqual(summary["paper_count"], 2)
            self.assertEqual(summary["total_contributions"], 1)
            self.assertEqual(summary["status_counts"]["complete"], 1)
            self.assertEqual(summary["status_counts"]["failed"], 1)
            self.assertEqual(summary["measurement_counts"]["measurements_complete"], 1)
            papers = record["papers"]
            self.assertEqual(papers[0]["arxiv_id"], "2601.00001")
            self.assertEqual(papers[0]["contribution_types"], {"candidates_found": 1})
            self.assertEqual(len(papers[0]["contributions_sha256"]), 64)

    def test_malformed_documents_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            literature_dir = Path(tmp)
            write_paper(literature_dir, "2601.00001", ai_document())
            bad_dir = literature_dir / "2601.00003"
            bad_dir.mkdir()
            (bad_dir / "literature_hvs_contributions.json").write_text(
                '{"schema": {"name": "literature_hvs_contributions", "version": 9}}',
                encoding="utf-8",
            )
            record = build_hvs_contributions_index(literature_dir)
            self.assertEqual(record["summary"]["paper_count"], 1)
            self.assertEqual(record["summary"]["skipped_count"], 1)

    def test_write_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            literature_dir = Path(tmp)
            write_paper(literature_dir, "2601.00001", ai_document())
            result = write_hvs_contributions_index_outputs(literature_dir)
            self.assertTrue(Path(result["index_json_path"]).is_file())
            markdown = Path(result["index_markdown_path"]).read_text(encoding="utf-8")
            self.assertIn("2601.00001", markdown)
            self.assertIn("contribution-first", markdown)


if __name__ == "__main__":
    unittest.main()
