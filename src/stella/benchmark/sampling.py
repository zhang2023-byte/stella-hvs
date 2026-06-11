"""Deterministic stratified sampling for the expert gold-standard benchmark.

Design (agreed 2026-06-11, see benchmark/README.md and the sampling manifest):

- The frame is every archived paper with a ``literature_hvs_candidates.json``,
  minus the three Phase-2 pilot papers (excluded only because the extraction
  pipeline is tuned on them; any other exclusion would bias the frame).
- Stratification variables are paper-intrinsic only. Tool products may serve
  as *declared proxies* but never as exclusion criteria.
- Primary stratum: candidates proxy. ``status == "candidates_found"`` in the
  legacy extraction counts as proxy-positive, everything else (including
  unfinished legacy files) as proxy-negative. Positives are deliberately
  oversampled; inverse-probability weights are recorded per paper so that
  population-level estimates can be reconstructed. After gold annotation the
  proxy confusion matrix is itself a reportable result.
- Secondary stratum: deterministic TeX table complexity (number of table
  environments, maximum row count of any tabular-like block), recomputable
  from the archived source. Papers without an archived TeX source count as
  the lowest complexity bin and are flagged.
- Era: implicit stratification. Within each primary-by-complexity cell,
  papers are sorted chronologically (by arXiv id) and drawn by seeded
  systematic sampling, which spreads the sample across publication years.
- Roles: each sampled paper is blind (expert annotates from the PDF only) or
  verification (expert reviews AI prefill against the PDF). A subset of the
  blind papers is double-annotated (overlap) for inter-annotator agreement.

Everything is deterministic given the seed: sub-draws use purpose-derived
seeds so adding a stratum or reordering iteration cannot silently reshuffle
other draws.
"""

from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass
from pathlib import Path

MANIFEST_SCHEMA_VERSION = "stella.benchmark_sampling_manifest.v0.1"
DEFAULT_SEED = 20260611

PROXY_POSITIVE = "candidates_proxy_positive"
PROXY_NEGATIVE = "candidates_proxy_negative"
COMPLEXITY_LOW = "table_complexity_low"
COMPLEXITY_HIGH = "table_complexity_high"
ROLE_BLIND = "blind"
ROLE_VERIFICATION = "verification"

# A paper is high-complexity when either threshold is met. Chosen on the
# 2026-06 frame so both bins are non-degenerate in both primary strata
# (positive 23/26, negative 98/60).
COMPLEXITY_HIGH_MIN_TABLES = 4
COMPLEXITY_HIGH_MIN_ROWS = 40

# Pilot papers for tuning the Phase-2 extraction pipeline. Excluded from the
# frame for tuning-leakage reasons only.
PILOT_PAPERS: dict[str, str] = {
    "2101.10878": "phase-2 pipeline pilot (tuning leakage)",
    "2011.10206": "phase-2 pipeline pilot (tuning leakage)",
    "1901.04559": "phase-2 pipeline pilot (tuning leakage)",
}

# Per primary stratum: total blind, total verification, and how many of the
# blind papers are double-annotated. Positives carry most of the field-level
# information (L2-L4), hence the deliberate oversampling.
ALLOCATION: dict[str, dict[str, int]] = {
    PROXY_POSITIVE: {"blind": 8, "verification": 20, "overlap": 3},
    PROXY_NEGATIVE: {"blind": 4, "verification": 15, "overlap": 2},
}

TABLE_ENV_RE = re.compile(r"\\begin\{(deluxetable\*?|table\*?|longtable)\}")
ROW_BLOCK_RE = re.compile(
    r"\\begin\{(tabular\*?|array|deluxetable\*?|longtable)\}(.*?)\\end\{\1\}",
    re.S,
)
ARXIV_ID_RE = re.compile(r"^([0-9]{4})\.([0-9]{4,5})$")


@dataclass(frozen=True)
class FramePaper:
    """One paper in the sampling frame with its stratification variables."""

    arxiv_id: str
    status: str
    n_tables: int
    max_table_rows: int
    has_tex_source: bool = True

    @property
    def stratum(self) -> str:
        if self.status == "candidates_found":
            return PROXY_POSITIVE
        return PROXY_NEGATIVE

    @property
    def complexity_bin(self) -> str:
        if (
            self.n_tables >= COMPLEXITY_HIGH_MIN_TABLES
            or self.max_table_rows >= COMPLEXITY_HIGH_MIN_ROWS
        ):
            return COMPLEXITY_HIGH
        return COMPLEXITY_LOW

    @property
    def chronological_key(self) -> tuple[int, int, str]:
        match = ARXIV_ID_RE.match(self.arxiv_id)
        if match:
            return int(match.group(1)), int(match.group(2)), self.arxiv_id
        return (9999, 99999, self.arxiv_id)


def measure_tex_complexity(source_dir: Path) -> tuple[int, int]:
    """Count table environments and the maximum row count of any block.

    Deterministic and recomputable from the archived ``arxiv_source``
    directory. A missing directory yields ``(0, 0)``.
    """

    n_tables = 0
    max_rows = 0
    if not source_dir.is_dir():
        return n_tables, max_rows
    for tex_path in sorted(source_dir.rglob("*.tex")):
        text = tex_path.read_text(encoding="utf-8", errors="replace")
        n_tables += len(TABLE_ENV_RE.findall(text))
        for match in ROW_BLOCK_RE.finditer(text):
            rows = match.group(2).count(r"\\")
            max_rows = max(max_rows, rows)
    return n_tables, max_rows


def _purpose_rng(seed: int, purpose: str) -> random.Random:
    return random.Random(f"{seed}|{purpose}")


def allocate_proportionally(bin_sizes: dict[str, int], total: int) -> dict[str, int]:
    """Largest-remainder proportional allocation with deterministic ties.

    Bins larger than zero receive at least their floored share; leftover
    units go to the largest remainders, ties broken by bin name. The result
    never allocates more than a bin's population.
    """

    population = sum(bin_sizes.values())
    if population == 0 or total == 0:
        return {name: 0 for name in bin_sizes}
    if total > population:
        raise ValueError(f"cannot allocate {total} from population {population}")
    shares = {
        name: total * size / population for name, size in bin_sizes.items()
    }
    allocation = {name: math.floor(share) for name, share in shares.items()}
    leftover = total - sum(allocation.values())
    remainders = sorted(
        bin_sizes,
        key=lambda name: (-(shares[name] - allocation[name]), name),
    )
    for name in remainders:
        if leftover == 0:
            break
        if allocation[name] < bin_sizes[name]:
            allocation[name] += 1
            leftover -= 1
    # If some bins were capped at their population, push the rest elsewhere.
    while leftover > 0:
        progressed = False
        for name in sorted(bin_sizes, key=lambda n: (-bin_sizes[n], n)):
            if leftover == 0:
                break
            if allocation[name] < bin_sizes[name]:
                allocation[name] += 1
                leftover -= 1
                progressed = True
        if not progressed:
            raise ValueError("allocation does not fit bin populations")
    return allocation


def systematic_sample(
    items: list[FramePaper], count: int, rng: random.Random
) -> list[FramePaper]:
    """Seeded systematic sample from a chronologically sorted list."""

    if count < 0 or count > len(items):
        raise ValueError(f"cannot draw {count} from {len(items)} items")
    if count == 0:
        return []
    ordered = sorted(items, key=lambda paper: paper.chronological_key)
    step = len(ordered) / count
    start = rng.uniform(0.0, step)
    picks = []
    for index in range(count):
        position = min(int(start + index * step), len(ordered) - 1)
        picks.append(ordered[position])
    # Systematic positions are strictly increasing because step >= 1.
    return picks


def _select_role_subset(
    selected: list[FramePaper], count: int, rng: random.Random
) -> set[str]:
    subset = systematic_sample(selected, count, rng)
    return {paper.arxiv_id for paper in subset}


def build_manifest_entries(
    frame: list[FramePaper], seed: int = DEFAULT_SEED
) -> tuple[list[dict], dict]:
    """Draw the sample and return (per-paper entries, frame summary).

    Entries carry stratum, complexity bin, role, overlap flag, and the
    inverse-inclusion-probability sampling weight (cell population divided
    by cell sample size, blind and verification pooled).
    """

    ids = [paper.arxiv_id for paper in frame]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate arxiv ids in frame")
    for paper in frame:
        if paper.arxiv_id in PILOT_PAPERS:
            raise ValueError(
                f"pilot paper {paper.arxiv_id} must be excluded from the frame"
            )

    entries: list[dict] = []
    cells_summary: dict[str, dict] = {}
    for stratum in (PROXY_POSITIVE, PROXY_NEGATIVE):
        members = [paper for paper in frame if paper.stratum == stratum]
        quota = ALLOCATION[stratum]
        n_total = quota["blind"] + quota["verification"]
        bin_populations = {
            bin_name: len([p for p in members if p.complexity_bin == bin_name])
            for bin_name in (COMPLEXITY_LOW, COMPLEXITY_HIGH)
        }
        bin_quota = allocate_proportionally(bin_populations, n_total)

        selected: list[FramePaper] = []
        weights: dict[str, float] = {}
        for bin_name in (COMPLEXITY_LOW, COMPLEXITY_HIGH):
            population = [p for p in members if p.complexity_bin == bin_name]
            n_cell = bin_quota[bin_name]
            rng = _purpose_rng(seed, f"draw|{stratum}|{bin_name}")
            picks = systematic_sample(population, n_cell, rng)
            selected.extend(picks)
            cell_weight = (len(population) / n_cell) if n_cell else 0.0
            for paper in picks:
                weights[paper.arxiv_id] = cell_weight
            cells_summary[f"{stratum}/{bin_name}"] = {
                "population": len(population),
                "sampled": n_cell,
                "sampling_weight": cell_weight,
            }

        selected.sort(key=lambda paper: paper.chronological_key)
        blind_ids = _select_role_subset(
            selected, quota["blind"], _purpose_rng(seed, f"blind|{stratum}")
        )
        blind_papers = [p for p in selected if p.arxiv_id in blind_ids]
        overlap_ids = _select_role_subset(
            blind_papers, quota["overlap"], _purpose_rng(seed, f"overlap|{stratum}")
        )

        for paper in selected:
            role = ROLE_BLIND if paper.arxiv_id in blind_ids else ROLE_VERIFICATION
            entries.append(
                {
                    "arxiv_id": paper.arxiv_id,
                    "stratum": stratum,
                    "complexity_bin": paper.complexity_bin,
                    "n_tables": paper.n_tables,
                    "max_table_rows": paper.max_table_rows,
                    "has_tex_source": paper.has_tex_source,
                    "legacy_status": paper.status,
                    "role": role,
                    "overlap": paper.arxiv_id in overlap_ids,
                    "sampling_weight": round(weights[paper.arxiv_id], 6),
                }
            )

    entries.sort(key=lambda entry: entry["arxiv_id"])
    frame_summary = {
        "size": len(frame),
        "strata": {
            stratum: len([p for p in frame if p.stratum == stratum])
            for stratum in (PROXY_POSITIVE, PROXY_NEGATIVE)
        },
        "cells": cells_summary,
    }
    return entries, frame_summary


def build_manifest(frame: list[FramePaper], seed: int = DEFAULT_SEED) -> dict:
    """Build the full manifest document (without per-paper version checks)."""

    entries, frame_summary = build_manifest_entries(frame, seed)
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "seed": seed,
        "design": {
            "principle": (
                "Stratification variables are paper-intrinsic only; tool "
                "products may serve as declared proxies but never as "
                "exclusion criteria."
            ),
            "primary_stratum": (
                "candidates proxy from the legacy extraction status: "
                "candidates_found counts as proxy-positive, everything else "
                "(including unfinished legacy files) as proxy-negative; "
                "positives are oversampled and weights recorded"
            ),
            "secondary_stratum": {
                "description": (
                    "deterministic TeX table complexity, recomputable from "
                    "the archived arxiv_source; missing source counts as "
                    "lowest complexity and is flagged via has_tex_source"
                ),
                "high_if_n_tables_at_least": COMPLEXITY_HIGH_MIN_TABLES,
                "high_if_max_table_rows_at_least": COMPLEXITY_HIGH_MIN_ROWS,
            },
            "era": (
                "implicit: chronological ordering plus seeded systematic "
                "sampling inside each cell"
            ),
            "allocation": ALLOCATION,
            "pilot_exclusions": [
                {"arxiv_id": arxiv_id, "reason": reason}
                for arxiv_id, reason in sorted(PILOT_PAPERS.items())
            ],
        },
        "frame": frame_summary,
        "papers": entries,
        "warnings": [],
    }
