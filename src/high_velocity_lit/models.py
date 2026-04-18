"""Small dataclasses shared by the monthly DeepXiv pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class MonthWindow:
    year: int
    month: int
    start: date
    end: date

    @property
    def slug(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    @property
    def date_from(self) -> str:
        return self.start.isoformat()

    @property
    def date_to(self) -> str:
        return self.end.isoformat()


@dataclass(frozen=True)
class SearchConfig:
    workspace: Path
    notes_dir: Path
    logs_dir: Path
    start_year: int
    start_month: int
    end_year: int
    end_month: int
    end_date: Optional[date]
    source: str
    queries: list[str]
    categories: list[str]
    max_results: int
    search_mode: str
    min_score: Optional[float]
    classifier: str
    llm_api_key: Optional[str]
    llm_base_url: str
    llm_model: str
    llm_batch_size: int
    llm_review_weak: bool
    search_sleep_seconds: float
    brief_sleep_seconds: float
    use_brief: bool
    token: Optional[str] = None
