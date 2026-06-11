"""Helpers for Stella note storage paths."""

from __future__ import annotations

import re
from pathlib import Path


MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
YEAR_RE = re.compile(r"^\d{4}$")


def year_slug(month_slug: str) -> str:
    return month_slug[:4]


def month_dir(notes_dir: Path, month_slug: str) -> Path:
    return notes_dir / year_slug(month_slug) / month_slug


def legacy_month_dir(notes_dir: Path, month_slug: str) -> Path:
    return notes_dir / month_slug


def month_json_path(notes_dir: Path, month_slug: str) -> Path:
    return month_dir(notes_dir, month_slug) / f"{month_slug}.json"


def month_markdown_path(notes_dir: Path, month_slug: str) -> Path:
    return month_dir(notes_dir, month_slug) / f"{month_slug}.md"


def month_title_triage_path(notes_dir: Path, month_slug: str) -> Path:
    return month_dir(notes_dir, month_slug) / f"{month_slug}.title-triage.json"


def candidate_month_json_paths(notes_dir: Path, month_slug: str) -> list[Path]:
    return [
        month_json_path(notes_dir, month_slug),
        legacy_month_dir(notes_dir, month_slug) / f"{month_slug}.json",
    ]


def resolve_month_json_path(notes_dir: Path, month_slug: str) -> Path:
    for candidate in candidate_month_json_paths(notes_dir, month_slug):
        if candidate.exists():
            return candidate
    return month_json_path(notes_dir, month_slug)


def iter_month_json_paths(notes_dir: Path) -> list[Path]:
    if not notes_dir.exists():
        return []

    by_month: dict[str, Path] = {}

    for year_dir in sorted(notes_dir.iterdir()):
        if not year_dir.is_dir() or not YEAR_RE.fullmatch(year_dir.name):
            continue
        for month_dir_path in sorted(year_dir.iterdir()):
            if not month_dir_path.is_dir() or not MONTH_RE.fullmatch(month_dir_path.name):
                continue
            candidate = month_dir_path / f"{month_dir_path.name}.json"
            if candidate.exists():
                by_month[month_dir_path.name] = candidate

    for child in sorted(notes_dir.iterdir()):
        if not child.is_dir() or not MONTH_RE.fullmatch(child.name):
            continue
        candidate = child / f"{child.name}.json"
        if candidate.exists() and child.name not in by_month:
            by_month[child.name] = candidate

    return [by_month[month] for month in sorted(by_month)]
