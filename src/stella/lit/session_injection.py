"""Explicit external-service session injection.

A *session file* (``STELLA_SESSION_FILE``) is the only way tests replace
external services: it declares canned discovery results, paper assets,
model decisions, and provider transcripts. Production paths construct
real clients and never read a session. A session is test infrastructure
carried by the run environment, never a scientific request field.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Callable

SESSION_ENV = "STELLA_SESSION_FILE"


def load_session(env: dict[str, str] | None = None) -> dict[str, Any] | None:
    """Load the declared session, or ``None`` for the production path."""

    source = env if env is not None else os.environ
    path = source.get(SESSION_ENV, "")
    if not path:
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"session file {path} must contain a JSON object")
    return data


def session_discovery(session: dict[str, Any] | None) -> dict[str, Any]:
    return (session or {}).get("discovery") or {}


def session_assets(session: dict[str, Any] | None) -> dict[str, Any]:
    return (session or {}).get("assets") or {}


def session_assessments(session: dict[str, Any] | None) -> dict[str, Any]:
    return (session or {}).get("assessments") or {}


def session_review_responses(session: dict[str, Any] | None) -> dict[str, Any]:
    return (session or {}).get("review_responses") or {}


def session_model_responses(session: dict[str, Any] | None) -> list[dict[str, Any]]:
    return (session or {}).get("model_responses") or []


def session_method_config(session: dict[str, Any] | None) -> dict[str, Any]:
    """The frozen method configuration declared by a test session."""

    return (session or {}).get("method") or {}


class FakeCatalogAssessor:
    """CatalogAssessor protocol backed by session decisions."""

    def __init__(self, decisions: dict[str, Any]) -> None:
        self._decisions = decisions
        self.calls: list[list[dict[str, Any]]] = []

    def assess_batch(self, papers: list[dict[str, Any]]) -> dict[str, Any]:
        from stella.lit.catalog_assessment import CatalogAssessment

        self.calls.append(papers)
        output: dict[str, Any] = {}
        for paper in papers:
            arxiv_id = str(paper.get("arxiv_id") or "")
            decision = self._decisions.get(arxiv_id)
            if decision is None:
                continue
            output[arxiv_id] = CatalogAssessment(
                has_observational_catalog=bool(
                    decision.get("has_observational_catalog")
                ),
                confidence=float(decision.get("confidence") or 0.0),
                catalog_role=str(decision.get("catalog_role") or "unclear"),
                object_scope=str(decision.get("object_scope") or "unclear"),
                evidence=str(decision.get("evidence") or ""),
                data_products=[
                    str(item) for item in decision.get("data_products") or []
                ],
            )
        return output


class FakeReviewModel:
    """Callable returning a canned catalog-review JSON response."""

    def __init__(self, response: Any) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    def __call__(self, messages=None, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"messages": messages, **kwargs})
        content = (
            json.dumps(self._response, ensure_ascii=False)
            if not isinstance(self._response, str)
            else self._response
        )
        return {
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ]
        }


def materialize_session_assets(
    session: dict[str, Any] | None, paper_id: str, target_dir: Path
) -> list[str]:
    """Write the session's declared assets into the approved layout.

    Asset values are base64-encoded bytes (binary-safe for PDFs and
    source archives). Returns the written relative paths.
    """

    declared = session_assets(session).get(paper_id) or {}
    written: list[str] = []
    for name, value in sorted(declared.items()):
        destination = target_dir / "assets" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(base64.b64decode(value))
        written.append(str(destination))
    return written


AssetFetcher = Callable[[str, str], bytes]


def session_asset_fetcher(
    session: dict[str, Any] | None,
) -> AssetFetcher | None:
    """A fetcher resolving (paper_id, name) to bytes from the session."""

    assets = session_assets(session)
    if not assets:
        return None

    def fetch(paper_id: str, name: str) -> bytes:
        declared = assets.get(paper_id) or {}
        if name not in declared:
            raise KeyError(f"session has no asset {name!r} for {paper_id}")
        return base64.b64decode(declared[name])

    return fetch


class FakeArxivSearcher:
    """ArxivClient-shaped search returning canned month results.

    Session discovery maps ``"YYYY-MM"`` to paper entries; each entry is
    merged into every query covering that month, matching the real
    client's ``search(query, size=..., date_from=..., date_to=...)``
    interface.
    """

    def __init__(self, month_papers: dict[str, list[dict[str, Any]]]) -> None:
        self._month_papers = month_papers
        self.calls: list[dict[str, Any]] = []

    def search(
        self,
        query: str,
        *,
        size: int,
        date_from: str,
        date_to: str,
        categories: list[str] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "query": query,
                "size": size,
                "date_from": date_from,
                "date_to": date_to,
                "categories": list(categories or []),
            }
        )
        papers: list[dict[str, Any]] = []
        for month, entries in sorted(self._month_papers.items()):
            covers = str(date_from or "")[:7] <= month <= str(date_to or "")[:7]
            if not covers:
                continue
            for entry in entries:
                paper = dict(entry)
                paper.setdefault("arxiv_id", paper.get("id", ""))
                paper.setdefault("matched_query", query)
                papers.append(paper)
        return {"total": len(papers), "results": papers}
