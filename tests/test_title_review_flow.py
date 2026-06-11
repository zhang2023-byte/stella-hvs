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
from stella.lit.note_paths import month_dir, month_json_path, month_markdown_path, month_title_triage_path  # noqa: E402


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
                    "abstract": "Ambiguous search abstract.",
                    "author_names": "B. Ambiguous",
                    "categories": ["astro-ph.GA"],
                    "publish_at": "2025-01-11T00:00:00",
                    "score": 1.0,
                },
            ],
        }


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
                "llm-related",
            )
        }


class ScoreCapDeepXivClient:
    token = "fake-token"

    def __init__(self, token: str | None = None) -> None:
        del token

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
        return {
            "total": 4,
            "results": [
                {
                    "arxiv_id": "2501.00001",
                    "title": "Stellar escape from compact clusters",
                    "abstract": "Lowest score ambiguous paper.",
                    "author_names": "A. Low",
                    "categories": ["astro-ph.GA"],
                    "publish_at": "2025-01-10T00:00:00",
                    "score": 0.1,
                },
                {
                    "arxiv_id": "2501.00002",
                    "title": "Kinematic products of cluster disruption",
                    "abstract": "Second-highest score ambiguous paper.",
                    "author_names": "B. High",
                    "categories": ["astro-ph.GA"],
                    "publish_at": "2025-01-11T00:00:00",
                    "score": 2.0,
                },
                {
                    "arxiv_id": "2501.00003",
                    "title": "Dynamical evolution of stellar populations",
                    "abstract": "Mid score ambiguous paper.",
                    "author_names": "C. Mid",
                    "categories": ["astro-ph.GA"],
                    "publish_at": "2025-01-12T00:00:00",
                    "score": 1.0,
                },
                {
                    "arxiv_id": "2501.00004",
                    "title": "Halo kinematic anomalies in survey data",
                    "abstract": "Highest score ambiguous paper.",
                    "author_names": "D. Top",
                    "categories": ["astro-ph.GA"],
                    "publish_at": "2025-01-13T00:00:00",
                    "score": 3.0,
                },
            ],
        }


class RecordingLLMTitleClassifier:
    reviewed_ids: list[str] = []

    def __init__(self, *, api_key: str, base_url: str, model: str) -> None:
        del api_key, base_url, model
        self.__class__.reviewed_ids = []

    def classify_batch(self, papers: list[dict[str, object]]) -> dict[str, object]:
        self.__class__.reviewed_ids.extend(str(paper["arxiv_id"]) for paper in papers)
        return {
            str(paper["arxiv_id"]): pipeline.TitleDecision(
                True,
                0.8,
                "Selected by score cap for LLM review.",
                "llm-related",
            )
            for paper in papers
        }


class TitleReviewFlowTest(unittest.TestCase):
    def make_config(self, root: Path, *, llm_review: bool, llm_api_key: str | None = None) -> SearchConfig:
        return SearchConfig(
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
            llm_api_key=llm_api_key,
            llm_base_url="https://api.openai.com/v1",
            llm_model="gpt-4o-mini",
            llm_batch_size=25,
            llm_review=llm_review,
            search_sleep_seconds=0,
            progress=False,
            token=None,
        )

    def test_without_llm_review_only_rule_related_papers_enter_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root, llm_review=False)

            existing_month_dir = month_dir(config.notes_dir, "2024-12")
            existing_month_dir.mkdir(parents=True, exist_ok=True)
            (existing_month_dir / "2024-12.json").write_text(
                json.dumps(
                    {
                        "schema_version": "stella.literature.month.v3",
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
            self.assertEqual(summary["index_json"], str(config.notes_dir / "00_literature_notes_index.json"))

            triage_json = month_title_triage_path(config.notes_dir, "2025-01")
            triage_record = json.loads(triage_json.read_text(encoding="utf-8"))
            self.assertEqual([paper["arxiv_id"] for paper in triage_record["rule_related_papers"]], ["2501.00001"])
            self.assertEqual(
                [paper["arxiv_id"] for paper in triage_record["no_clear_title_evidence_papers"]],
                ["2501.00002"],
            )

            run_log = Path(summary["run_log"])
            records = [json.loads(line) for line in run_log.read_text(encoding="utf-8").splitlines()]
            self.assertFalse([record for record in records if record.get("event") == "brief"])

            note = month_markdown_path(config.notes_dir, "2025-01").read_text(encoding="utf-8")
            self.assertNotIn("Ambiguous search abstract.", note)
            self.assertNotIn("DeepXiv brief", note)

            record = json.loads(month_json_path(config.notes_dir, "2025-01").read_text(encoding="utf-8"))
            self.assertEqual([paper["arxiv_id"] for paper in record["papers"]], ["2501.00001"])
            self.assertNotIn("brief", record["papers"][0])
            self.assertEqual(record["stats"]["rule_related_count"], 1)
            self.assertEqual(record["stats"]["no_clear_title_evidence_count"], 1)
            self.assertEqual(record["stats"]["llm_reviewed_count"], 0)

    def test_llm_review_confirms_ambiguous_titles_without_fetching_brief(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root, llm_review=True, llm_api_key="test-key")

            with (
                patch.object(pipeline, "ArxivClient", FakeArxivClient),
                patch.object(pipeline, "DeepXivClient", FakeDeepXivClient),
                patch.object(pipeline, "LLMTitleClassifier", FakeLLMTitleClassifier),
                patch.object(pipeline, "load_llm_api_key", return_value="test-key"),
            ):
                summary = pipeline.run_pipeline(config)

            self.assertEqual(summary["status"], "complete")

            triage_json = month_title_triage_path(config.notes_dir, "2025-01")
            triage_record = json.loads(triage_json.read_text(encoding="utf-8"))
            ambiguous_paper = triage_record["no_clear_title_evidence_papers"][0]
            self.assertEqual(ambiguous_paper["review"]["status"], "confirmed")

            record = json.loads(month_json_path(config.notes_dir, "2025-01").read_text(encoding="utf-8"))
            self.assertEqual(record["stats"]["llm_reviewed_count"], 1)
            self.assertEqual(record["stats"]["llm_confirmed_count"], 1)
            papers_by_id = {paper["arxiv_id"]: paper for paper in record["papers"]}
            self.assertEqual(sorted(papers_by_id), ["2501.00001", "2501.00002"])
            self.assertTrue(all("brief" not in paper for paper in papers_by_id.values()))

            note = month_markdown_path(config.notes_dir, "2025-01").read_text(encoding="utf-8")
            self.assertIn("LLM confirmed 1 paper", note)
            self.assertNotIn("DeepXiv brief", note)

    def test_deepxiv_llm_review_caps_ambiguous_candidates_by_score(self) -> None:
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
                max_results=4,
                search_mode="hybrid",
                min_score=None,
                llm_api_key="test-key",
                llm_base_url="https://api.openai.com/v1",
                llm_model="gpt-4o-mini",
                llm_batch_size=25,
                llm_review=True,
                search_sleep_seconds=0,
                progress=False,
                deepxiv_llm_review_max_candidates=2,
                token=None,
            )

            with (
                patch.object(pipeline, "ArxivClient", FakeArxivClient),
                patch.object(pipeline, "DeepXivClient", ScoreCapDeepXivClient),
                patch.object(pipeline, "LLMTitleClassifier", RecordingLLMTitleClassifier),
                patch.object(pipeline, "load_llm_api_key", return_value="test-key"),
            ):
                pipeline.run_pipeline(config)

            self.assertEqual(RecordingLLMTitleClassifier.reviewed_ids, ["2501.00004", "2501.00002"])

            triage_record = json.loads(
                month_title_triage_path(config.notes_dir, "2025-01").read_text(encoding="utf-8")
            )
            reviews = {
                paper["arxiv_id"]: paper.get("review", {}).get("status")
                for paper in triage_record["no_clear_title_evidence_papers"]
            }
            self.assertEqual(reviews["2501.00004"], "confirmed")
            self.assertEqual(reviews["2501.00002"], "confirmed")
            self.assertEqual(reviews["2501.00003"], "skipped")
            self.assertEqual(reviews["2501.00001"], "skipped")

            record = json.loads(month_json_path(config.notes_dir, "2025-01").read_text(encoding="utf-8"))
            self.assertEqual(record["stats"]["no_clear_title_evidence_count"], 4)
            self.assertEqual(record["stats"]["llm_reviewed_count"], 2)
            self.assertEqual(record["stats"]["llm_confirmed_count"], 2)
            self.assertEqual(record["stats"]["llm_skipped_count"], 2)


if __name__ == "__main__":
    unittest.main()
