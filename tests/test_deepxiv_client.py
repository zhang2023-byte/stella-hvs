from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

from stella.lit.deepxiv_client import DeepXivClient  # noqa: E402


class _ReaderShouldNotBeUsed:
    def search(self, **_: object) -> dict[str, object]:
        raise AssertionError("search() should use the HTTP retrieval path, not SDK Reader.search")


class DeepXivClientSearchTest(unittest.TestCase):
    def test_search_uses_http_retrieval_even_when_sdk_reader_exists(self) -> None:
        client = DeepXivClient.__new__(DeepXivClient)
        client.token = "test-token"
        client.reader = _ReaderShouldNotBeUsed()

        captured: dict[str, object] = {}

        def fake_request(*, path: str, query: dict[str, object], expect_json: bool) -> dict[str, object]:
            captured["path"] = path
            captured["query"] = query
            captured["expect_json"] = expect_json
            return {"total_count": 1, "result": [{"arxiv_id": "2601.19866", "title": "Discovery of Galactic center ejected star in DESI DR1"}]}

        client._request = fake_request  # type: ignore[method-assign]
        result = client.search(
            "hypervelocity stars",
            size=10,
            search_mode="hybrid",
            date_from="2026-01-01",
            date_to="2026-01-31",
            categories=["astro-ph.GA"],
        )

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["results"][0]["arxiv_id"], "2601.19866")
        self.assertEqual(captured["path"], "/arxiv/")
        self.assertEqual(captured["expect_json"], True)
        self.assertEqual(
            captured["query"],
            {
                "type": "retrieve",
                "query": "hypervelocity stars",
                "top_k": 10,
                "source": "arxiv",
                "date_search_type": "between",
                "date_str": ["2026-01-01", "2026-01-31"],
                "categories": ["astro-ph.GA"],
                "use_fine_rerank": "true",
            },
        )

    def test_search_normalizes_unified_retrieve_fields(self) -> None:
        client = DeepXivClient.__new__(DeepXivClient)
        client.token = "test-token"
        client.reader = None

        def fake_request(*, path: str, query: dict[str, object], expect_json: bool) -> dict[str, object]:
            del path, query, expect_json
            return {
                "status": "success",
                "total_count": 1,
                "result": [
                    {
                        "arxiv_id": "2601.19866",
                        "title": "Discovery of Galactic center ejected star in DESI DR1",
                        "date": "2026-01-27",
                        "citation_count": 3,
                        "authors": [
                            {"name": "Sergey E. Koposov", "orgs": ["Institute for Astronomy, University of Edinburgh"]},
                            {"name": "Elena Maria Rossi", "orgs": ["Institute for Astronomy, University of Edinburgh"]},
                        ],
                    }
                ],
            }

        client._request = fake_request  # type: ignore[method-assign]
        result = client.search(
            "hypervelocity stars",
            size=10,
            search_mode="hybrid",
            date_from="2026-01-01",
            date_to="2026-01-31",
            categories=["astro-ph.GA"],
        )

        paper = result["results"][0]
        self.assertEqual(paper["publish_at"], "2026-01-27")
        self.assertEqual(paper["citations"], 3)
        self.assertEqual(paper["author_names"], "Sergey E. Koposov, Elena Maria Rossi")


if __name__ == "__main__":
    unittest.main()
