from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

from stella.lit.indexing import rebuild_index  # noqa: E402
from stella.lit.markdown import render_index  # noqa: E402
from stella.lit.note_paths import month_dir  # noqa: E402


class IndexingTest(unittest.TestCase):
    def test_rebuild_index_groups_by_year_and_lists_data_related_papers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            notes_dir = Path(tmp) / "notes"

            month_2026 = month_dir(notes_dir, "2026-03")
            month_2026.mkdir(parents=True)
            (month_2026 / "2026-03.json").write_text(
                json.dumps(
                    {
                        "month": "2026-03",
                        "papers": [
                            {
                                "title": "A 2026 catalog paper",
                                "arxiv_id": "2603.00001",
                                "published_at": "2026-03-12",
                                "links": {
                                    "abs": "https://arxiv.org/abs/2603.00001",
                                    "pdf": "https://arxiv.org/pdf/2603.00001",
                                },
                                "catalog_assessment": {"has_observational_catalog": True},
                            },
                            {
                                "title": "A 2026 non-catalog paper",
                                "arxiv_id": "2603.00002",
                                "published_at": "2026-03-10",
                                "links": {},
                            },
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            month_2025 = month_dir(notes_dir, "2025-11")
            month_2025.mkdir(parents=True)
            (month_2025 / "2025-11.json").write_text(
                json.dumps(
                    {
                        "month": "2025-11",
                        "papers": [
                            {
                                "title": "A 2025 catalog paper",
                                "arxiv_id": "2511.00001",
                                "published_at": "2025-11-20",
                                "links": {
                                    "abs": "https://arxiv.org/abs/2511.00001",
                                    "pdf": "https://arxiv.org/pdf/2511.00001",
                                },
                                "catalog_assessment": {"has_observational_catalog": True},
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            index = rebuild_index(notes_dir)

            self.assertEqual(index["schema_version"], "stella.literature.index.v4")
            years = {item["year"]: item for item in index["years"]}
            self.assertEqual(years["2026"]["literature_count"], 2)
            self.assertEqual(years["2026"]["data_related_count"], 1)
            self.assertEqual(years["2025"]["literature_count"], 1)
            self.assertEqual(years["2025"]["data_related_count"], 1)
            self.assertEqual(
                years["2026"]["data_related_papers"][0]["navigation_path"],
                "2026/2026-03/2026-03.md",
            )
            self.assertEqual(len(index["papers"]), 3)
            self.assertEqual(index["papers"][0]["arxiv_id"], "2603.00001")
            self.assertTrue(index["papers"][0]["has_observational_catalog"])
            self.assertEqual(index["papers"][1]["arxiv_id"], "2603.00002")
            self.assertFalse(index["papers"][1]["has_observational_catalog"])

            markdown = render_index(index)
            self.assertIn("## Recent Literature", markdown)
            self.assertIn("Indexed papers available for sampling: 3 papers", markdown)
            self.assertIn("## Year Overview", markdown)
            self.assertIn("| 2026 | 2 | 1 |", markdown)
            self.assertIn(
                "[A 2026 catalog paper](2026/2026-03/2026-03.md) - 2026-03; 2026-03-12; data-related",
                markdown,
            )


if __name__ == "__main__":
    unittest.main()
