from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from high_velocity_lit.indexing import rebuild_index  # noqa: E402
from high_velocity_lit.markdown import render_index  # noqa: E402
from high_velocity_lit.note_paths import month_dir  # noqa: E402


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
                                "triage": {"level": "direct", "label": "rule-direct"},
                                "links": {
                                    "abs": "https://arxiv.org/abs/2603.00001",
                                    "pdf": "https://arxiv.org/pdf/2603.00001",
                                },
                                "catalog_assessment": {"has_observational_catalog": True},
                                "catalog_verification": {
                                    "verified": True,
                                    "verified_at": "2026-04-21T12:34:56",
                                    "has_catalog": True,
                                    "overall_verdict": "confirmed",
                                    "catalog_location": "mixed",
                                    "record_path": "literature/2603.00001/record.json",
                                    "summary_path": "literature/2603.00001/summary.md",
                                },
                            },
                            {
                                "title": "A 2026 non-catalog paper",
                                "arxiv_id": "2603.00002",
                                "published_at": "2026-03-10",
                                "triage": {"level": "weak", "label": "rule-weak"},
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
                                "triage": {"level": "direct", "label": "rule-direct"},
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
            self.assertEqual(years["2026"]["verified_count"], 1)
            self.assertEqual(years["2026"]["verified_catalog_count"], 1)
            self.assertEqual(years["2025"]["literature_count"], 1)
            self.assertEqual(years["2025"]["data_related_count"], 1)
            self.assertEqual(
                years["2026"]["data_related_papers"][0]["navigation_path"],
                "2026/2026-03/2026-03.md",
            )
            self.assertEqual(len(index["papers"]), 3)
            self.assertEqual(index["papers"][0]["arxiv_id"], "2603.00001")
            self.assertTrue(index["papers"][0]["has_observational_catalog"])
            self.assertTrue(index["papers"][0]["catalog_verification"]["has_catalog"])
            self.assertEqual(index["papers"][1]["arxiv_id"], "2603.00002")
            self.assertFalse(index["papers"][1]["has_observational_catalog"])
            self.assertEqual(index["summary"]["verified_count"], 1)
            self.assertEqual(index["summary"]["verified_catalog_count"], 1)

            markdown = render_index(index)
            self.assertIn("## Recent Literature", markdown)
            self.assertIn("Indexed papers available for sampling: 3 papers", markdown)
            self.assertIn("Paper-level verification: 1 paper checked; 1 paper with catalog confirmed", markdown)
            self.assertIn("Triage mix: 2 direct papers; 1 weak paper", markdown)
            self.assertIn("## Year Overview", markdown)
            self.assertIn("| 2026 | 2 | 1 | 1 | 1 |", markdown)
            self.assertIn(
                "[A 2026 catalog paper](2026/2026-03/2026-03.md) - 2026-03; 2026-03-12; direct; data-related; verified: catalog",
                markdown,
            )


if __name__ == "__main__":
    unittest.main()
