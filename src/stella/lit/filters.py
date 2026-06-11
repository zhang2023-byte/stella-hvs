"""Local relevance filters for high-velocity star papers."""

from __future__ import annotations

import html
import re
from typing import Any


TAG_RE = re.compile(r"<[^>]+>")

RELEVANCE_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("hypervelocity star", re.compile(r"\bhyper[-\s]?velocity\s+stars?\b|\bHVSs?\b", re.I)),
    (
        "high-velocity star",
        re.compile(
            r"\bhigh[-\s]?velocity\s+(?:candidate\s+)?stars?\b|"
            r"\bstars?\s+with\s+galactocentric\s+velocit(?:y|ies)\b|"
            r"\bstars?\s+with\s+space\s+velocit(?:y|ies)\b",
            re.I,
        ),
    ),
    ("runaway star", re.compile(r"\b(?:OB\s+)?runaway\s+stars?\b", re.I)),
    ("fast-moving star", re.compile(r"\bfast[-\s]?moving\s+stars?\b", re.I)),
    ("unbound star", re.compile(r"\bunbound\s+stars?\b|\bescaping\s+stars?\b", re.I)),
    (
        "peculiar-velocity star",
        re.compile(
            r"\bpeculiar\s+velocit(?:y|ies)\b.{0,100}\bstars?\b|"
            r"\bstars?\b.{0,100}\bpeculiar\s+velocit(?:y|ies)\b",
            re.I | re.S,
        ),
    ),
]


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(clean_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(clean_text(item) for item in value.values())
    text = html.unescape(str(value))
    return TAG_RE.sub(" ", text)


def paper_text(paper: dict[str, Any]) -> str:
    fields = [
        paper.get("title"),
        paper.get("abstract"),
        paper.get("tldr"),
        paper.get("keywords"),
    ]
    return "\n".join(clean_text(field) for field in fields if field)


def relevance_matches(paper: dict[str, Any]) -> list[str]:
    text = paper_text(paper)
    matches: list[str] = []
    for label, pattern in RELEVANCE_RULES:
        if pattern.search(text):
            matches.append(label)
    return matches


def is_relevant(paper: dict[str, Any]) -> bool:
    return bool(relevance_matches(paper))


def category_matches(paper: dict[str, Any], allowed_categories: list[str]) -> bool:
    if not allowed_categories:
        return True
    categories = paper.get("categories") or []
    if isinstance(categories, str):
        categories = [categories]
    if not categories:
        # Missing category metadata should not silently drop a possible paper.
        return True
    allowed = set(allowed_categories)
    normalized: list[str] = []
    for category in categories:
        normalized.extend(part for part in re.split(r"[\s,]+", str(category)) if part)
    return any(category in allowed for category in normalized)


def score_matches(paper: dict[str, Any], min_score: float | None) -> bool:
    if min_score is None:
        return True
    try:
        return float(paper.get("_best_score", paper.get("score", 0)) or 0) >= min_score
    except (TypeError, ValueError):
        return False
