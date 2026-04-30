from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from high_velocity_lit.arxiv_client import ArxivClient  # noqa: E402


EMPTY_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
  <opensearch:totalResults>0</opensearch:totalResults>
</feed>
"""


class ArxivClientSearchTest(unittest.TestCase):
    def test_search_pushes_categories_into_query_as_or_terms(self) -> None:
        client = ArxivClient()
        captured: dict[str, object] = {}

        def fake_fetch(params: dict[str, object], *, timeout: int, retries: int) -> bytes:
            captured["params"] = params
            captured["timeout"] = timeout
            captured["retries"] = retries
            return EMPTY_FEED

        client._fetch = fake_fetch  # type: ignore[method-assign]

        result = client.search(
            "high-velocity stars",
            size=20,
            date_from="2026-03-01",
            date_to="2026-03-31",
            categories=["astro-ph.GA", "astro-ph.SR", "astro-ph.IM"],
        )

        self.assertEqual(result["total"], 0)
        params = captured["params"]
        self.assertEqual(params["max_results"], 20)
        self.assertEqual(
            params["search_query"],
            'all:"high-velocity stars" AND submittedDate:[202603010000 TO 202603312359] '
            "AND (cat:astro-ph.GA OR cat:astro-ph.SR OR cat:astro-ph.IM)",
        )

    def test_search_omits_category_clause_when_categories_are_disabled(self) -> None:
        client = ArxivClient()
        captured: dict[str, object] = {}

        def fake_fetch(params: dict[str, object], *, timeout: int, retries: int) -> bytes:
            captured["params"] = params
            return EMPTY_FEED

        client._fetch = fake_fetch  # type: ignore[method-assign]

        client.search(
            "runaway stars",
            size=10,
            date_from="2026-03-01",
            date_to="2026-03-31",
            categories=[],
        )

        self.assertEqual(
            captured["params"]["search_query"],
            'all:"runaway stars" AND submittedDate:[202603010000 TO 202603312359]',
        )


if __name__ == "__main__":
    unittest.main()
