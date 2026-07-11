"""Canonical validation for modern arXiv identifiers used in local paths."""

from __future__ import annotations

import re


ARXIV_ID_RE = re.compile(r"^[0-9]{4}\.[0-9]{4,5}(?:v[0-9]+)?$")
UNVERSIONED_ARXIV_ID_RE = re.compile(r"^[0-9]{4}\.[0-9]{4,5}$")


def validate_arxiv_id(value: str, *, allow_version: bool = True) -> str:
    """Return a normalized modern arXiv ID or reject unsafe/ambiguous input."""

    text = str(value or "").strip()
    pattern = ARXIV_ID_RE if allow_version else UNVERSIONED_ARXIV_ID_RE
    if pattern.fullmatch(text) is None:
        example = "2401.10635 or 2401.10635v1" if allow_version else "2401.10635"
        raise ValueError(f"arXiv ID must look like {example}; got {value!r}")
    return text


def validate_unversioned_arxiv_id(value: str) -> str:
    return validate_arxiv_id(value, allow_version=False)


def parse_arxiv_id_list(value: str) -> list[str]:
    ids = [
        validate_arxiv_id(item)
        for item in (part.strip() for part in str(value or "").split(","))
        if item
    ]
    if not ids:
        raise ValueError("arXiv ID list cannot be empty")
    return ids
