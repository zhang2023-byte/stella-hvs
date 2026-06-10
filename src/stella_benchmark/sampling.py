"""Stratified benchmark paper sampling from the HVS candidates index."""

from __future__ import annotations

import random
from datetime import datetime
from typing import Any

from .models import (
    BENCHMARK_MANIFEST_SCHEMA_VERSION,
    BenchmarkManifest,
    ManifestPaper,
    ManifestSelection,
)

STRATA_SPEC = "year_bucket x extraction_status x candidate_count_bucket"
SAMPLED_STATUSES = ("candidates_found", "no_candidates")


def year_bucket(year: str) -> str:
    try:
        value = int(str(year).strip())
    except (TypeError, ValueError):
        return "unknown"
    if value <= 2020:
        return "2018-2020"
    if value <= 2023:
        return "2021-2023"
    return "2024-2026"


def candidate_count_bucket(count: int) -> str:
    if count <= 0:
        return "0"
    if count <= 3:
        return "1-3"
    if count <= 20:
        return "4-20"
    return ">20"


def assign_stratum(item: dict[str, Any]) -> str:
    status = str(item.get("extraction_status") or "unknown")
    count = int(item.get("candidate_count") or 0)
    return f"{year_bucket(str(item.get('year') or ''))}|{status}|{candidate_count_bucket(count)}"


def eligible_papers(index_record: dict[str, Any]) -> list[dict[str, Any]]:
    papers = index_record.get("papers") or []
    return [
        item
        for item in papers
        if isinstance(item, dict) and item.get("extraction_status") in SAMPLED_STATUSES
    ]


def allocate_per_stratum(stratum_sizes: dict[str, int], size: int) -> dict[str, int]:
    """Proportional allocation with at least one paper per non-empty stratum.

    When size is smaller than the number of non-empty strata, the largest
    strata win (ties broken by stratum name for determinism).
    """
    strata = sorted(name for name, count in stratum_sizes.items() if count > 0)
    total = sum(stratum_sizes[name] for name in strata)
    if not strata or size <= 0 or total == 0:
        return {}
    size = min(size, total)

    if size < len(strata):
        ranked = sorted(strata, key=lambda name: (-stratum_sizes[name], name))
        return {name: 1 for name in ranked[:size]}

    allocation = {name: 1 for name in strata}
    while sum(allocation.values()) < size:
        # Largest proportional deficit, capped by stratum size.
        candidates = [name for name in strata if allocation[name] < stratum_sizes[name]]
        if not candidates:
            break
        deficits = {
            name: (stratum_sizes[name] * size / total) - allocation[name] for name in candidates
        }
        best = max(candidates, key=lambda name: (deficits[name], stratum_sizes[name], name))
        allocation[best] += 1
    return allocation


def select_sample(
    index_record: dict[str, Any],
    *,
    size: int,
    seed: int,
    sample_round: int = 1,
    exclude_arxiv_ids: set[str] | None = None,
) -> list[ManifestPaper]:
    exclude = exclude_arxiv_ids or set()
    by_stratum: dict[str, list[dict[str, Any]]] = {}
    for item in eligible_papers(index_record):
        if str(item.get("arxiv_id") or "") in exclude:
            continue
        by_stratum.setdefault(assign_stratum(item), []).append(item)

    allocation = allocate_per_stratum(
        {name: len(items) for name, items in by_stratum.items()}, size
    )
    rng = random.Random(seed)
    selected: list[ManifestPaper] = []
    for name in sorted(allocation):
        pool = sorted(by_stratum[name], key=lambda item: str(item.get("arxiv_id") or ""))
        for item in rng.sample(pool, allocation[name]):
            selected.append(
                ManifestPaper(
                    arxiv_id=str(item.get("arxiv_id") or ""),
                    year=str(item.get("year") or ""),
                    stratum=name,
                    canonical_status=str(item.get("extraction_status") or ""),
                    canonical_candidate_count=int(item.get("candidate_count") or 0),
                    sample_round=sample_round,
                )
            )
    selected.sort(key=lambda paper: paper.arxiv_id)
    return selected


def build_manifest(
    index_record: dict[str, Any],
    *,
    size: int,
    seed: int,
    source_index_path: str,
    frozen: bool = True,
) -> BenchmarkManifest:
    papers = select_sample(index_record, size=size, seed=seed)
    return BenchmarkManifest(
        schema_version=BENCHMARK_MANIFEST_SCHEMA_VERSION,
        created_at=datetime.now().isoformat(timespec="seconds"),
        seed=seed,
        frozen=frozen,
        selection=ManifestSelection(
            size=len(papers),
            strata_spec=STRATA_SPEC,
            source_index_path=source_index_path,
            source_index_generated_at=str(index_record.get("generated_at") or ""),
        ),
        papers=papers,
    )


def manifest_is_frozen(payload: dict[str, Any]) -> bool:
    return bool(payload.get("frozen"))
