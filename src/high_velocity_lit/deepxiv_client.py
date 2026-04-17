"""Thin DeepXiv SDK wrapper with CLI-compatible token loading."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - python-dotenv is optional in the SDK.
    load_dotenv = None  # type: ignore[assignment]

from deepxiv_sdk import Reader


def load_deepxiv_token(explicit_token: Optional[str] = None) -> Optional[str]:
    if explicit_token:
        return explicit_token

    if load_dotenv is not None:
        for env_path in (Path.home() / ".env", Path.cwd() / ".env"):
            if env_path.exists():
                load_dotenv(env_path, override=True)

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
        self.reader = Reader(token=self.token)

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
        return self.reader.search(
            query=query,
            size=size,
            search_mode=search_mode,
            date_from=date_from,
            date_to=date_to,
            categories=categories,
        )

    def brief(self, arxiv_id: str) -> dict[str, Any]:
        return self.reader.brief(arxiv_id)
