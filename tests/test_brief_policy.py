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
from high_velocity_lit.note_paths import month_dir, month_json_path, month_markdown_path  # noqa: E402


class FakeArxivClient:
    pass


class FakeDeepXivClient:
    token = "fake-token"
    brief_calls: list[str] = []

    def __init__(self, token: str | None = None) -> None:
        type(self).brief_calls = []

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
            "total": 2,
            "results": [
                {
                    "arxiv_id": "2501.00001",
                    "title": "Discovery of a hypervelocity star candidate",
                    "abstract": "Direct-match search abstract.",
                    "author_names": "A. Direct",
                    "categories": ["astro-ph.GA"],
                    "publish_at": "2025-01-10T00:00:00",
                    "score": 2.0,
                },
                {
                    "arxiv_id": "2501.00002",
                    "title": "Stellar Escape from Globular Clusters. I. Escape Mechanisms and Properties at Ejection",
                    "abstract": "Weak-match search abstract.",
                    "author_names": "B. Weak",
                    "categories": ["astro-ph.GA"],
                    "publish_at": "2025-01-11T00:00:00",
                    "score": 1.0,
                },
            ],
        }

    def brief(self, arxiv_id: str) -> dict[str, object]:
        type(self).brief_calls.append(arxiv_id)
        return {"tldr": f"Brief for {arxiv_id}."}


class FakeLLMTitleClassifier:
    def __init__(self, *, api_key: str, base_url: str, model: str) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    def classify_batch(self, papers: list[dict[str, object]]) -> dict[str, object]:
        return {
            "2501.00002": pipeline.TitleDecision(
                True,
                0.88,
                "Abstract and title indicate a directly relevant high-velocity-star paper.",
                "llm-direct",
            )
        }


class BriefPolicyTest(unittest.TestCase):
    def test_brief_is_only_fetched_for_direct_rule_matches(self) -> None:
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
                max_results=2,
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

            existing_month_dir = month_dir(config.notes_dir, "2024-12")
            existing_month_dir.mkdir(parents=True, exist_ok=True)
            (existing_month_dir / "2024-12.json").write_text(
                json.dumps(
                    {
                        "schema_version": "stella.literature.month.v2",
                        "month": "2024-12",
                        "date_from": "2024-12-01",
                        "date_to": "2024-12-31",
                        "papers": [
                            {
                                "arxiv_id": "2412.00001",
                                "title": "A data-rich hypervelocity star catalog",
                                "published_at": "2024-12-15",
                                "links": {
                                    "abs": "https://arxiv.org/abs/2412.00001",
                                    "pdf": "https://arxiv.org/pdf/2412.00001",
                                },
                                "catalog_assessment": {
                                    "has_observational_catalog": True,
                                },
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            with (
                patch.object(pipeline, "ArxivClient", FakeArxivClient),
                patch.object(pipeline, "DeepXivClient", FakeDeepXivClient),
            ):
                summary = pipeline.run_pipeline(config)

            self.assertEqual(summary["status"], "complete")
            self.assertEqual(FakeDeepXivClient.brief_calls, ["2501.00001"])
            self.assertEqual(summary["index_json"], str(config.notes_dir / "index.json"))

            run_log = Path(summary["run_log"])
            records = [json.loads(line) for line in run_log.read_text(encoding="utf-8").splitlines()]
            brief_events = [record for record in records if record.get("event") == "brief"]
            self.assertEqual([event["arxiv_id"] for event in brief_events], ["2501.00001"])

            note = month_markdown_path(config.notes_dir, "2025-01").read_text(encoding="utf-8")
            self.assertIn("Brief for 2501.00001.", note)
            self.assertIn("weak match not fetched", note)
            self.assertIn("Weak-match search abstract.", note)
            self.assertIn("**Search Abstract**", note)
            self.assertIn("**Strong / Direct Matches**", note)
            self.assertIn("---\n\n**Weak Matches**", note)
            self.assertLess(
                note.index("Discovery of a hypervelocity star candidate"),
                note.index("Stellar Escape from Globular Clusters"),
            )

            month_json = month_json_path(config.notes_dir, "2025-01")
            index_json = config.notes_dir / "index.json"
            self.assertTrue(month_json.exists())
            self.assertTrue(index_json.exists())
            self.assertFalse((config.notes_dir / "papers.jsonl").exists())
            index_markdown = (config.notes_dir / "index.md").read_text(encoding="utf-8")
            self.assertIn("| 2025 | 2 | 0 |", index_markdown)
            self.assertIn("[A data-rich hypervelocity star catalog](2024/2024-12/2024-12.md)", index_markdown)

            record = json.loads(month_json.read_text(encoding="utf-8"))
            self.assertEqual(record["schema_version"], "stella.literature.month.v2")
            self.assertEqual(record["papers"][0]["triage"]["level"], "direct")
            self.assertEqual(record["papers"][1]["triage"]["level"], "weak")
            self.assertTrue(record["papers"][0]["brief"]["fetched"])
            self.assertFalse(record["papers"][1]["brief"]["fetched"])
            self.assertEqual(record["papers"][1]["abstract"]["text"], "Weak-match search abstract.")

            index = json.loads(index_json.read_text(encoding="utf-8"))
            self.assertEqual(index["schema_version"], "stella.literature.index.v4")
            years = {item["year"]: item for item in index["years"]}
            self.assertEqual(years["2025"]["literature_count"], 2)
            self.assertEqual(years["2025"]["data_related_count"], 0)
            self.assertEqual(years["2024"]["literature_count"], 1)
            self.assertEqual(years["2024"]["data_related_count"], 1)
            self.assertEqual(
                years["2024"]["data_related_papers"][0]["navigation_path"],
                "2024/2024-12/2024-12.md",
            )
            self.assertEqual(len(index["papers"]), 3)

    def test_llm_review_keeps_confirmed_weak_matches_in_weak_tier_without_brief(self) -> None:
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
                max_results=2,
                search_mode="hybrid",
                min_score=None,
                classifier="rules",
                llm_api_key="test-key",
                llm_base_url="https://example.test/v1",
                llm_model="test-model",
                llm_batch_size=25,
                llm_review=True,
                search_sleep_seconds=0,
                brief_sleep_seconds=0,
                use_brief=True,
                progress=False,
                token=None,
            )

            with (
                patch.object(pipeline, "ArxivClient", FakeArxivClient),
                patch.object(pipeline, "DeepXivClient", FakeDeepXivClient),
                patch.object(pipeline, "LLMTitleClassifier", FakeLLMTitleClassifier),
                patch.object(pipeline, "load_llm_api_key", return_value="test-key"),
            ):
                summary = pipeline.run_pipeline(config)

            self.assertEqual(summary["status"], "complete")
            self.assertEqual(FakeDeepXivClient.brief_calls, ["2501.00001"])

            month_json = month_json_path(config.notes_dir, "2025-01")
            record = json.loads(month_json.read_text(encoding="utf-8"))
            self.assertEqual(record["stats"]["weak_llm_reviewed"], 1)
            self.assertEqual(record["stats"]["weak_llm_included"], 1)
            self.assertEqual(record["stats"]["brief_eligible_count"], 1)
            papers_by_id = {paper["arxiv_id"]: paper for paper in record["papers"]}
            self.assertEqual(papers_by_id["2501.00002"]["triage"]["level"], "weak")
            self.assertEqual(papers_by_id["2501.00002"]["triage"]["label"], "rule-weak-llm-confirmed")
            self.assertFalse(papers_by_id["2501.00002"]["brief"]["fetched"])

            note = month_markdown_path(config.notes_dir, "2025-01").read_text(encoding="utf-8")
            self.assertIn("kept after review 1 paper", note)
            self.assertIn("**Weak Matches**", note)
            self.assertNotIn("Brief for 2501.00002.", note)


if __name__ == "__main__":
    unittest.main()
