"""Thin DeepXiv client with CLI-compatible token loading.

This wrapper prefers the local ``deepxiv_sdk`` when available, but it can also
fall back to the public HTTP endpoints. The fallback keeps Stella usable in
lighter environments and makes it easier to test the client without requiring
the SDK import to succeed at module import time.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .env import load_env_files


DEEPXIV_BASE_URL = "https://data.rag.ac.cn"
USER_AGENT = "stella-high-velocity-lit/0.1"


def _load_reader_class() -> type[Any] | None:
    try:
        from deepxiv_sdk import Reader

        return Reader
    except Exception:
        return None


def load_deepxiv_token(explicit_token: Optional[str] = None) -> Optional[str]:
    if explicit_token:
        return explicit_token

    load_env_files(Path.cwd())

    token = os.environ.get("DEEPXIV_TOKEN")
    if token:
        return token

    try:
        from deepxiv_sdk.cli import ensure_token

        return ensure_token(None)
    except Exception:
        return None


class DeepXivClient:
    def __init__(self, token: Optional[str] = None) -> None:
        self.token = load_deepxiv_token(token)
        reader_class = _load_reader_class()
        self.reader = reader_class(token=self.token, timeout=30, max_retries=2) if reader_class is not None else None

    @staticmethod
    def _normalize_result_item(item: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(item)
        if normalized.get("date") and not normalized.get("publish_at"):
            normalized["publish_at"] = normalized["date"]
        if normalized.get("citation_count") is not None and normalized.get("citations") is None:
            normalized["citations"] = normalized.get("citation_count")
        authors = normalized.get("authors")
        if isinstance(authors, list):
            author_names = [
                author.get("name", "").strip()
                for author in authors
                if isinstance(author, dict) and str(author.get("name") or "").strip()
            ]
            if author_names and not normalized.get("author_names"):
                normalized["author_names"] = ", ".join(author_names)
        return normalized

    @classmethod
    def _normalize_search_result(cls, result: dict[str, Any]) -> dict[str, Any]:
        if "results" in result and "total" in result:
            results = result.get("results") or []
            return {
                **result,
                "results": [cls._normalize_result_item(item) for item in results if isinstance(item, dict)],
            }
        if "result" in result or "total_count" in result:
            results = result.get("result") or []
            return {
                "total": result.get("total_count"),
                "results": [cls._normalize_result_item(item) for item in results if isinstance(item, dict)],
            }
        return result

    def _request(self, *, path: str, query: dict[str, Any], expect_json: bool) -> Any:
        params = {key: value for key, value in query.items() if value is not None and value != ""}
        if self.token and "token" not in params:
            params["token"] = self.token
        request = Request(
            f"{DEEPXIV_BASE_URL}{path}?{urlencode(params, doseq=True)}",
            headers={"User-Agent": USER_AGENT},
            method="GET",
        )
        with urlopen(request, timeout=45) as response:
            payload = response.read()
        if expect_json:
            return json.loads(payload.decode("utf-8"))
        return payload.decode("utf-8")

    def search(
        self,
        query: str,
        *,
        size: int,
        search_mode: str,
        date_from: str,
        date_to: str,
        categories: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        # The public HTTP endpoint reliably honors date-bounded retrieval.
        # In practice the SDK Reader.search path has returned stale historical
        # results for monthly searches even when date_from/date_to are set.
        result = self._request(
            path="/arxiv/",
            query={
                "type": "retrieve",
                "query": query,
                "top_k": size,
                "source": "arxiv",
                "date_search_type": "between",
                "date_str": [date_from, date_to],
                "categories": categories or None,
                "use_fine_rerank": "true" if search_mode == "hybrid" else "false",
            },
            expect_json=True,
        )
        return self._normalize_search_result(result)

    def brief(self, arxiv_id: str) -> dict[str, Any]:
        if self.reader is not None:
            return self.reader.brief(arxiv_id)
        return self._request(
            path="/arxiv/",
            query={"type": "brief", "arxiv_id": arxiv_id},
            expect_json=True,
        )

    def head(self, arxiv_id: str) -> dict[str, Any]:
        if self.reader is not None:
            return self.reader.head(arxiv_id)
        return self._request(
            path="/arxiv/",
            query={"type": "head", "arxiv_id": arxiv_id},
            expect_json=True,
        )

    def preview(self, arxiv_id: str) -> dict[str, Any]:
        if self.reader is not None:
            return self.reader.preview(arxiv_id)
        return self._request(
            path="/arxiv/",
            query={"type": "preview", "arxiv_id": arxiv_id},
            expect_json=True,
        )

    def raw(self, arxiv_id: str) -> str:
        if self.reader is not None:
            return str(self.reader.raw(arxiv_id))
        result = self._request(
            path="/arxiv/",
            query={"type": "raw", "arxiv_id": arxiv_id},
            expect_json=True,
        )
        return str(result.get("raw") or "")

    def json(self, arxiv_id: str) -> dict[str, Any]:
        if self.reader is not None:
            return self.reader.json(arxiv_id)
        return self._request(
            path="/arxiv/",
            query={"type": "json", "arxiv_id": arxiv_id},
            expect_json=True,
        )

    def section(self, arxiv_id: str, section_name: str) -> str:
        if self.reader is not None:
            return str(self.reader.section(arxiv_id, section_name))
        result = self._request(
            path="/arxiv/",
            query={"type": "section", "arxiv_id": arxiv_id, "section": section_name},
            expect_json=True,
        )
        if isinstance(result, dict):
            return str(result.get("section") or result.get("content") or result.get("raw") or "")
        return str(result)
