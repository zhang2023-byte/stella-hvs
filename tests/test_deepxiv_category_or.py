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

from high_velocity_lit import pipeline  # noqa: E402
from high_velocity_lit.models import SearchConfig  # noqa: E402
from high_velocity_lit.note_paths import month_json_path  # noqa: E402


class FakeArxivClient:
    calls: list[tuple[str, list[str] | None]] = []

    def __init__(self) -> None:
        self.__class__.calls = []

    def search(
        self,
        query: str,
        *,
        size: int,
        date_from: str,
        date_to: str,
        categories: list[str] | None = None,
    ) -> dict[str, object]:
        del size, date_from, date_to
        self.__class__.calls.append((query, categories))
        return {
            "total": 1,
            "results": [
                {
                    "arxiv_id": "2501.99999",
                    "title": "Discovery of a hypervelocity star after fallback",
                    "abstract": "A fallback arXiv paper.",
                    "author_names": "Fallback Author",
                    "categories": ["astro-ph.GA"],
                    "published_at": "2025-01-20T00:00:00",
                }
            ],
        }


class CategoryFanoutDeepXivClient:
    token = "fake-token"
    calls: list[list[str] | None] = []

    def __init__(self, token: str | None = None) -> None:
        del token
        self.__class__.calls = []

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
        del query, size, search_mode, date_from, date_to
        self.__class__.calls.append(categories)
        category = (categories or [""])[0]
        by_category = {
            "astro-ph.GA": [
                {
                    "arxiv_id": "2501.00001",
                    "title": "Discovery of a Galactic hypervelocity star",
                    "abstract": "A Galactic high-velocity star result.",
                    "author_names": "A. Galactic",
                    "categories": ["astro-ph.GA"],
                    "publish_at": "2025-01-10T00:00:00",
                    "score": 1.0,
                }
            ],
            "astro-ph.SR": [
                {
                    "arxiv_id": "2501.00002",
                    "title": "Gaia DR3 high radial velocity stars",
                    "abstract": "A stellar HRV sample.",
                    "author_names": "B. Stellar",
                    "categories": ["astro-ph.SR"],
                    "publish_at": "2025-01-11T00:00:00",
                    "score": 1.0,
                }
            ],
            "astro-ph.IM": [
                {
                    "arxiv_id": "2501.00002",
                    "title": "Gaia DR3 high radial velocity stars",
                    "abstract": "A stellar HRV sample with methods content.",
                    "author_names": "B. Stellar",
                    "categories": ["astro-ph.SR", "astro-ph.IM"],
                    "publish_at": "2025-01-11T00:00:00",
                    "score": 1.5,
                }
            ],
        }
        return {"total": len(by_category.get(category, [])), "results": by_category.get(category, [])}


class FailingDeepXivClient:
    token = "fake-token"
    calls = 0

    def __init__(self, token: str | None = None) -> None:
        del token
        self.__class__.calls = 0

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
        del query, size, search_mode, date_from, date_to, categories
        self.__class__.calls += 1
        raise RuntimeError("DeepXiv quota exhausted")


class DeepXivCategoryOrTest(unittest.TestCase):
    def test_deepxiv_categories_are_fanned_out_and_union_deduplicated(self) -> None:
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
                categories=["astro-ph.GA", "astro-ph.SR", "astro-ph.IM"],
                max_results=5,
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
                patch.object(pipeline, "DeepXivClient", CategoryFanoutDeepXivClient),
            ):
                summary = pipeline.run_pipeline(config)

            self.assertEqual(summary["status"], "complete")
            self.assertEqual(
                CategoryFanoutDeepXivClient.calls,
                [["astro-ph.GA"], ["astro-ph.SR"], ["astro-ph.IM"]],
            )

            record = json.loads(month_json_path(config.notes_dir, "2025-01").read_text(encoding="utf-8"))
            self.assertEqual(record["stats"]["raw_unique"], 2)
            self.assertEqual([row["category"] for row in record["search_log"]], config.categories)
            papers_by_id = {paper["arxiv_id"]: paper for paper in record["papers"]}
            self.assertEqual(sorted(papers_by_id), ["2501.00001", "2501.00002"])
            self.assertEqual(papers_by_id["2501.00002"]["match"]["categories"], ["astro-ph.SR", "astro-ph.IM"])

    def test_deepxiv_failure_falls_back_to_arxiv_for_rest_of_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = SearchConfig(
                workspace=root,
                notes_dir=root / "notes",
                logs_dir=root / "logs",
                start_date=date(2025, 1, 1),
                end_date=date(2025, 1, 31),
                source="deepxiv",
                queries=["hypervelocity stars", "runaway stars"],
                categories=["astro-ph.GA", "astro-ph.SR"],
                max_results=5,
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
                patch.object(pipeline, "DeepXivClient", FailingDeepXivClient),
            ):
                summary = pipeline.run_pipeline(config)

            self.assertEqual(summary["status"], "complete")
            self.assertEqual(FailingDeepXivClient.calls, 1)
            self.assertEqual(
                FakeArxivClient.calls,
                [
                    ("hypervelocity stars", ["astro-ph.GA", "astro-ph.SR"]),
                    ("runaway stars", ["astro-ph.GA", "astro-ph.SR"]),
                ],
            )

            record = json.loads(month_json_path(config.notes_dir, "2025-01").read_text(encoding="utf-8"))
            self.assertEqual(record["stats"]["deepxiv_fallback_count"], 1)
            self.assertEqual([row["source"] for row in record["search_log"]], ["arxiv", "arxiv"])
            self.assertEqual(record["search_log"][0]["fallback_from"], "deepxiv")
            self.assertIn("DeepXiv fallback", record["search_log"][0]["error"])
            self.assertIsNone(record["search_log"][1]["fallback_from"])
            self.assertEqual(record["papers"][0]["provenance"]["search_source"], "arxiv")
            self.assertEqual(record["papers"][0]["provenance"]["configured_search_source"], "deepxiv")
            self.assertEqual(record["papers"][0]["abstract"]["source"], "arxiv")


if __name__ == "__main__":
    unittest.main()
