from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from high_velocity_lit import pipeline  # noqa: E402
from high_velocity_lit.models import MonthWindow, SearchConfig  # noqa: E402


class HistoricalCategoryResolutionTest(unittest.TestCase):
    def make_config(self) -> SearchConfig:
        root = ROOT
        return SearchConfig(
            workspace=root,
            notes_dir=root / "notes",
            logs_dir=root / "logs",
            start_date=date(2005, 1, 1),
            end_date=date(2009, 1, 31),
            source="deepxiv",
            queries=[
                "hypervelocity stars",
                "high-velocity stars",
                "high radial velocity stars",
                "runaway stars",
                "unbound stars",
                "escaping stars",
            ],
            categories=["astro-ph.GA", "astro-ph.SR", "astro-ph.IM"],
            max_results=20,
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

    def test_resolved_categories_follow_historical_cutoff(self) -> None:
        config = self.make_config()
        self.assertEqual(
            pipeline.resolved_categories_for_month(
                config,
                MonthWindow(year=2008, month=11, start=date(2008, 11, 1), end=date(2008, 11, 30)),
            ),
            ["astro-ph"],
        )
        self.assertEqual(
            pipeline.resolved_categories_for_month(
                config,
                MonthWindow(year=2008, month=12, start=date(2008, 12, 1), end=date(2008, 12, 31)),
            ),
            ["astro-ph", "astro-ph.GA", "astro-ph.SR", "astro-ph.IM"],
        )
        self.assertEqual(
            pipeline.resolved_categories_for_month(
                config,
                MonthWindow(year=2009, month=1, start=date(2009, 1, 1), end=date(2009, 1, 31)),
            ),
            ["astro-ph.GA", "astro-ph.SR", "astro-ph.IM"],
        )

    def test_resolved_queries_add_legacy_variant_through_2008_12(self) -> None:
        config = self.make_config()
        legacy_queries = pipeline.resolved_queries_for_month(
            config,
            MonthWindow(year=2005, month=1, start=date(2005, 1, 1), end=date(2005, 1, 31)),
        )
        modern_queries = pipeline.resolved_queries_for_month(
            config,
            MonthWindow(year=2009, month=1, start=date(2009, 1, 1), end=date(2009, 1, 31)),
        )
        self.assertIn("hyper-velocity star", legacy_queries)
        self.assertNotIn("hyper-velocity star", modern_queries)


if __name__ == "__main__":
    unittest.main()
