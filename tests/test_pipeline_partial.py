from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from high_velocity_lit.models import SearchConfig  # noqa: E402
from high_velocity_lit import pipeline  # noqa: E402
from high_velocity_lit.note_paths import month_json_path, month_markdown_path  # noqa: E402


class RateLimitError(Exception):
    pass


class FakeArxivClient:
    pass


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
        if date_from == "2025-02-01":
            raise RateLimitError("Daily limit reached. Email tommy@chien.io for higher limits.")
        return {
            "total": 1,
            "results": [
                {
                    "arxiv_id": "2501.00001",
                    "title": "Discovery of a hypervelocity star candidate",
                    "abstract": "A test paper.",
                    "author_names": "A. Author",
                    "categories": ["astro-ph.GA"],
                    "publish_at": "2025-01-10T00:00:00",
                    "score": 1.0,
                }
            ],
        }

    def brief(self, arxiv_id: str) -> dict[str, object]:
        return {"tldr": "Brief text."}


class PipelinePartialRunTest(unittest.TestCase):
    def test_rate_limit_writes_partial_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = SearchConfig(
                workspace=root,
                notes_dir=root / "notes",
                logs_dir=root / "logs",
                start_date=date(2025, 1, 1),
                end_date=date(2025, 2, 28),
                source="deepxiv",
                queries=["hypervelocity stars"],
                categories=["astro-ph.GA"],
                max_results=1,
                search_mode="hybrid",
                min_score=None,
                classifier="rules",
                llm_api_key=None,
                llm_base_url="https://api.openai.com/v1",
                llm_model="gpt-4o-mini",
                llm_batch_size=25,
                llm_review=False,
                search_sleep_seconds=0,
                brief_sleep_seconds=0,
                use_brief=True,
                progress=False,
                token=None,
            )

            with (
                patch.object(pipeline, "ArxivClient", FakeArxivClient),
                patch.object(pipeline, "DeepXivClient", FakeDeepXivClient),
            ):
                with self.assertRaises(pipeline.PartialRunError) as captured:
                    pipeline.run_pipeline(config)

            summary = captured.exception.summary
            self.assertEqual(summary["status"], "partial")
            self.assertEqual(summary["completed_months"], ["2025-01"])
            self.assertEqual(summary["failed_month"], "2025-02")
            self.assertEqual(summary["resume_from"], "2025-02")
            self.assertIn("--from 2025-02", summary["resume_command"])
            self.assertEqual(summary["arxiv_metadata"]["requested_count"], 0)
            self.assertEqual(summary["arxiv_metadata"]["reported_count"], 0)

            partial_path = Path(str(summary["partial_summary_path"]))
            self.assertTrue(partial_path.exists())
            saved = json.loads(partial_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "partial")

            report_path = Path(str(summary["arxiv_metadata_report_path"]))
            self.assertTrue(report_path.exists())
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["requested_count"], 0)
            self.assertEqual(report["summary"]["reported_count"], 0)

            self.assertTrue(month_markdown_path(config.notes_dir, "2025-01").exists())
            self.assertFalse(month_markdown_path(config.notes_dir, "2025-02").exists())
            self.assertTrue(month_json_path(config.notes_dir, "2025-01").exists())
            self.assertFalse(month_json_path(config.notes_dir, "2025-02").exists())
            self.assertEqual(summary["index_json"], str(config.notes_dir / "index.json"))

            runs = [
                json.loads(line)
                for line in (config.logs_dir / "runs.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(runs[-1]["status"], "partial")


if __name__ == "__main__":
    unittest.main()
