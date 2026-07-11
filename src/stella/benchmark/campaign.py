"""Frozen benchmark campaign contract built from sampling manifest v0.2."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from pathlib import Path
from typing import Any

from stella.schema_registry import ACTIVE_BENCHMARK_CAMPAIGN, STELLA_RELEASE, require_schema, schema_ref
from stella.benchmark.paths import validate_path_segment

CAMPAIGN_ID = ACTIVE_BENCHMARK_CAMPAIGN

DEV_IDS: tuple[str, ...] = (
    "1804.10179",
    "1807.00427",
    "1807.02028",
    "1902.05061",
    "2209.03560",
    "2304.11269",
    "2401.02017",
    "2403.03311",
    "2507.07558",
    "2602.16925",
)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _cell_key(paper: dict[str, Any]) -> str:
    return f"{paper['stratum']}/{paper['complexity_bin']}"


def build_campaign(
    sampling_manifest: dict[str, Any],
    *,
    sampling_manifest_sha256: str,
    sampling_manifest_path: str = "benchmark/campaigns/hvs-extraction-v2/manifest/sampling_manifest.json",
    code_commit: str,
) -> dict[str, Any]:
    require_schema(sampling_manifest, "benchmark.sampling_manifest", require_current=True)
    if re.fullmatch(r"[0-9a-f]{40}", str(code_commit or "").lower()) is None:
        raise ValueError("campaign code_commit must be a full 40-character Git commit")
    papers = sampling_manifest.get("papers")
    if not isinstance(papers, list) or len(papers) != 50:
        raise ValueError("campaign requires exactly 50 sampled papers")
    by_id = {paper.get("arxiv_id"): paper for paper in papers}
    if len(by_id) != 50 or None in by_id:
        raise ValueError("sampling papers must have 50 unique arxiv ids")
    missing_dev = sorted(set(DEV_IDS) - set(by_id))
    if missing_dev:
        raise ValueError(f"dev papers missing from sample: {missing_dev}")
    for paper in papers:
        if paper.get("sampling_phase") == "supplemental" and paper.get(
            "version_consistent"
        ) is not True:
            raise ValueError(
                f"supplemental paper {paper['arxiv_id']} is not version-consistent"
            )

    dev_set = set(DEV_IDS)
    sample_counts = Counter(_cell_key(paper) for paper in papers)
    dev_counts = Counter(_cell_key(by_id[paper_id]) for paper_id in DEV_IDS)
    cells: dict[str, dict[str, Any]] = {}
    for cell, frame_info in sampling_manifest["frame"]["cells"].items():
        test_sampled = sample_counts[cell] - dev_counts[cell]
        evaluation_population = frame_info["population"] - dev_counts[cell]
        post_weight = evaluation_population / test_sampled
        cells[cell] = {
            "frame_population": frame_info["population"],
            "sampled": sample_counts[cell],
            "dev": dev_counts[cell],
            "test": test_sampled,
            "evaluation_frame_population": evaluation_population,
            "test_post_stratified_weight": round(post_weight, 6),
        }

    campaign_papers: list[dict[str, Any]] = []
    for paper in sorted(papers, key=lambda item: item["arxiv_id"]):
        split = "dev" if paper["arxiv_id"] in dev_set else "test"
        post_weight = (
            None if split == "dev" else cells[_cell_key(paper)]["test_post_stratified_weight"]
        )
        campaign_papers.append(
            {
                "arxiv_id": paper["arxiv_id"],
                "split": split,
                "stratum": paper["stratum"],
                "complexity_bin": paper["complexity_bin"],
                "legacy_status": paper["legacy_status"],
                "sampling_phase": paper["sampling_phase"],
                "sampling_weight": paper["sampling_weight"],
                "analysis_weights": {
                    "primary_unweighted": 1.0,
                    "test_post_stratified_sensitivity": post_weight,
                },
            }
        )

    return {
        "schema": schema_ref("benchmark.campaign"),
        "campaign_id": CAMPAIGN_ID,
        "stella_release": STELLA_RELEASE,
        "sampling_manifest": {
            "path": sampling_manifest_path,
            "sha256": sampling_manifest_sha256,
        },
        "code_commit": code_commit.lower(),
        "split_policy": {
            "dev_definition": "fixed pre-gold proxy-balanced set",
            "positive_negative_basis": "legacy_status",
            "difficulty_basis": "table_complexity_low/high",
            "gold_or_model_outcomes_used": False,
            "exposed_papers_permanently_dev": True,
            "test_definition": "exact complement of dev within final sample",
        },
        "analysis_policy": {
            "dev_primary": "unweighted",
            "test_primary": "unweighted",
            "test_sensitivity": "post-stratified to the 197-paper evaluation frame after excluding dev",
            "evaluation_frame_size": sum(
                cell["evaluation_frame_population"] for cell in cells.values()
            ),
        },
        "splits": {"dev": len(DEV_IDS), "test": len(papers) - len(DEV_IDS)},
        "cells": cells,
        "papers": campaign_papers,
    }


def papers_for_split(campaign: dict[str, Any], split: str) -> list[str]:
    if split not in {"dev", "test"}:
        raise ValueError("split must be dev or test")
    return [
        validate_path_segment(str(paper["arxiv_id"]), "paper id")
        for paper in campaign.get("papers", [])
        if paper.get("split") == split
    ]
