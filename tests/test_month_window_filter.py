from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]

from stella.lit import pipeline  # noqa: E402
from stella.lit.models import SearchConfig  # noqa: E402
from stella.lit.note_paths import month_json_path, month_markdown_path  # noqa: E402


class FakeArxivClient:
    pass


class MetadataBackfillArxivClient:
    def metadata(self, arxiv_id: str) -> dict[str, object]:
        if arxiv_id == "2501.00003":
            return {
                "arxiv_id": arxiv_id,
                "publish_at": "2025-01-12T00:00:00",
                "author_names": "C. Missing",
                "categories": ["astro-ph.GA"],
            }
        return {"arxiv_id": arxiv_id}


class TimeoutMetadataArxivClient:
    def metadata(self, arxiv_id: str) -> dict[str, object]:
        raise TimeoutError(f"timed out while fetching {arxiv_id}")


class FakeDeepXivClient:
    token = "fake-token"

    def __init__(self, token: str | None = None) -> None:
        pass

    def search(
        self,
        query: str,
        *,
        size: int,
        search_mode: str,
        date_from: str,
        date_to: str,
        categories: list[str] | None = None,
    ) -> dict[str, object]:
        return {
            "total": 3,
            "results": [
                {
                    "arxiv_id": "2501.00001",
                    "title": "Discovery of a hypervelocity star candidate",
                    "abstract": "In-window paper.",
                    "author_names": "A. In Window",
                    "categories": ["astro-ph.GA"],
                    "publish_at": "2025-01-10T00:00:00",
                    "score": 2.0,
                },
                {
                    "arxiv_id": "2502.00002",
                    "title": "Another hypervelocity star candidate",
                    "abstract": "Outside-window paper.",
                    "author_names": "B. Outside",
                    "categories": ["astro-ph.GA"],
                    "publish_at": "2025-02-10T00:00:00",
                    "score": 1.5,
                },
                {
                    "arxiv_id": "2501.00003",
                    "title": "Hypervelocity star with unavailable publication date",
                    "abstract": "Missing-date paper.",
                    "author_names": "C. Missing",
                    "categories": ["astro-ph.GA"],
                    "score": 1.0,
                },
            ],
        }

class MonthWindowFilterTest(unittest.TestCase):
    def test_pipeline_filters_out_of_window_and_missing_date_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = SearchConfig(
                workspace=root,
                notes_dir=root / "notes",
                logs_dir=root / "logs",
                start_date=date(2025, 1, 1),
                end_date=date(2025, 1, 31),
                source="deepxiv",
                queries=["hypervelocity stars"],
                categories=["astro-ph.GA"],
                max_results=3,
                search_mode="hybrid",
                min_score=None,
                llm_api_key=None,
                llm_base_url="https://api.openai.com/v1",
                llm_model="gpt-4o-mini",
                llm_batch_size=25,
                llm_review=False,
                search_sleep_seconds=0,
                progress=False,
                token=None,
            )

            with (
                patch.object(pipeline, "ArxivClient", FakeArxivClient),
                patch.object(pipeline, "DeepXivClient", FakeDeepXivClient),
            ):
                summary = pipeline.run_pipeline(config)

            self.assertEqual(summary["status"], "complete")
            self.assertEqual(summary["arxiv_metadata"]["requested_count"], 1)
            self.assertEqual(summary["arxiv_metadata"]["error_count"], 1)
            self.assertEqual(summary["arxiv_metadata"]["timeout_count"], 0)
            self.assertEqual(summary["arxiv_metadata"]["reported_count"], 1)

            record = json.loads(month_json_path(config.notes_dir, "2025-01").read_text(encoding="utf-8"))
            self.assertEqual([paper["arxiv_id"] for paper in record["papers"]], ["2501.00001"])
            self.assertEqual(record["stats"]["raw_unique"], 3)
            self.assertEqual(record["stats"]["date_window_filtered"], 1)
            self.assertEqual(record["stats"]["missing_publication_date"], 1)
            self.assertEqual(record["stats"]["arxiv_metadata_requested_count"], 1)
            self.assertEqual(record["stats"]["arxiv_metadata_error_count"], 1)
            self.assertEqual(record["stats"]["relevant_count"], 1)

            note = month_markdown_path(config.notes_dir, "2025-01").read_text(encoding="utf-8")
            self.assertIn("date-window-filtered 1 paper", note)
            self.assertIn("missing publication date 1 paper", note)
            self.assertIn("arXiv metadata backfill: attempted 1 paper missing dates", note)
            self.assertIn("other errors 1 paper", note)

            report = json.loads(Path(str(summary["arxiv_metadata_report_path"])).read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["requested_count"], 1)
            self.assertEqual(report["summary"]["error_count"], 1)
            self.assertEqual(report["summary"]["reported_count"], 1)
            self.assertEqual(report["entries"][0]["status"], "error")

            index = json.loads((config.notes_dir / "00_literature_notes_index.json").read_text(encoding="utf-8"))
            years = {item["year"]: item for item in index["years"]}
            self.assertEqual(years["2025"]["literature_count"], 1)

    def test_pipeline_backfills_missing_deepxiv_publication_dates_from_arxiv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = SearchConfig(
                workspace=root,
                notes_dir=root / "notes",
                logs_dir=root / "logs",
                start_date=date(2025, 1, 1),
                end_date=date(2025, 1, 31),
                source="deepxiv",
                queries=["hypervelocity stars"],
                categories=["astro-ph.GA"],
                max_results=3,
                search_mode="hybrid",
                min_score=None,
                llm_api_key=None,
                llm_base_url="https://api.openai.com/v1",
                llm_model="gpt-4o-mini",
                llm_batch_size=25,
                llm_review=False,
                search_sleep_seconds=0,
                progress=False,
                token=None,
            )

            with (
                patch.object(pipeline, "ArxivClient", MetadataBackfillArxivClient),
                patch.object(pipeline, "DeepXivClient", FakeDeepXivClient),
            ):
                summary = pipeline.run_pipeline(config)

            self.assertEqual(summary["status"], "complete")
            self.assertEqual(summary["arxiv_metadata"]["requested_count"], 1)
            self.assertEqual(summary["arxiv_metadata"]["publication_date_backfilled_count"], 1)
            self.assertEqual(summary["arxiv_metadata"]["reported_count"], 0)
            record = json.loads(month_json_path(config.notes_dir, "2025-01").read_text(encoding="utf-8"))
            self.assertEqual([paper["arxiv_id"] for paper in record["papers"]], ["2501.00003", "2501.00001"])
            self.assertEqual(record["stats"]["date_window_filtered"], 1)
            self.assertEqual(record["stats"]["missing_publication_date"], 0)
            self.assertEqual(record["stats"]["arxiv_publication_date_backfilled_count"], 1)

            report = json.loads(Path(str(summary["arxiv_metadata_report_path"])).read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["publication_date_backfilled_count"], 1)
            self.assertEqual(report["summary"]["reported_count"], 0)
            self.assertEqual(report["entries"], [])

    def test_pipeline_skips_timed_out_arxiv_metadata_and_writes_timeout_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = SearchConfig(
                workspace=root,
                notes_dir=root / "notes",
                logs_dir=root / "logs",
                start_date=date(2025, 1, 1),
                end_date=date(2025, 1, 31),
                source="deepxiv",
                queries=["hypervelocity stars"],
                categories=["astro-ph.GA"],
                max_results=3,
                search_mode="hybrid",
                min_score=None,
                llm_api_key=None,
                llm_base_url="https://api.openai.com/v1",
                llm_model="gpt-4o-mini",
                llm_batch_size=25,
                llm_review=False,
                search_sleep_seconds=0,
                progress=False,
                token=None,
            )

            with (
                patch.object(pipeline, "ArxivClient", TimeoutMetadataArxivClient),
                patch.object(pipeline, "DeepXivClient", FakeDeepXivClient),
            ):
                summary = pipeline.run_pipeline(config)

            self.assertEqual(summary["status"], "complete")
            self.assertEqual(summary["arxiv_metadata"]["requested_count"], 1)
            self.assertEqual(summary["arxiv_metadata"]["timeout_count"], 1)
            self.assertEqual(summary["arxiv_metadata"]["error_count"], 0)
            self.assertEqual(summary["arxiv_metadata"]["reported_count"], 1)

            record = json.loads(month_json_path(config.notes_dir, "2025-01").read_text(encoding="utf-8"))
            self.assertEqual([paper["arxiv_id"] for paper in record["papers"]], ["2501.00001"])
            self.assertEqual(record["stats"]["missing_publication_date"], 1)
            self.assertEqual(record["stats"]["arxiv_metadata_requested_count"], 1)
            self.assertEqual(record["stats"]["arxiv_metadata_timeout_count"], 1)
            self.assertEqual(record["stats"]["arxiv_metadata_error_count"], 0)

            note = month_markdown_path(config.notes_dir, "2025-01").read_text(encoding="utf-8")
            self.assertIn("timed out 1 paper", note)

            report = json.loads(Path(str(summary["arxiv_metadata_report_path"])).read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["timeout_count"], 1)
            self.assertEqual(report["summary"]["reported_count"], 1)
            self.assertEqual(report["entries"][0]["status"], "timeout")
            self.assertTrue(report["entries"][0]["timed_out"])


if __name__ == "__main__":
    unittest.main()
