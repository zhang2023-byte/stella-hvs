"""Frozen benchmark campaign contract built from a public sampling manifest."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from stella.schema_registry import ACTIVE_BENCHMARK_CAMPAIGN, STELLA_RELEASE, require_schema, schema_ref
from stella.benchmark.paths import validate_path_segment

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

BENCHMARK_PROFILE_SPLITS: dict[str, str | None] = {
    "dev10": "dev",
    "test40": "test",
    "full50": None,
}


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
    sampling_manifest_path: str | None = None,
    code_commit: str,
    campaign_id: str = ACTIVE_BENCHMARK_CAMPAIGN,
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
        "campaign_id": validate_path_segment(campaign_id, "campaign id"),
        "stella_release": STELLA_RELEASE,
        "sampling_manifest": {
            "path": sampling_manifest_path
            or f"benchmark/campaigns/{campaign_id}/manifest/sampling_manifest.json",
            "sha256": sampling_manifest_sha256,
        },
        "code_commit": code_commit.lower(),
        "lifecycle_status": "dev_hardening",
        "test_ready": False,
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


def papers_for_profile(campaign: dict[str, Any], profile: str) -> list[str]:
    """Resolve one benchmark profile in frozen campaign order."""

    try:
        split = BENCHMARK_PROFILE_SPLITS[profile]
    except KeyError as error:
        raise ValueError(f"unknown benchmark profile: {profile}") from error
    return [
        validate_path_segment(str(paper["arxiv_id"]), "paper id")
        for paper in campaign.get("papers", [])
        if split is None or paper.get("split") == split
    ]


def prepare(payload: dict, *, root: Path, paper_id: str | None = None) -> dict:
    """benchmark.prepare_campaign adapter.

    ``dev10`` is the fast default profile, ``test40`` is the held-out split,
    and ``full50`` is the complete contribution regression profile. Only
    ``full50`` requires an explicit, separately recorded authorization.
    """

    import os

    from stella.workflows import operation_complete, operation_failed

    profile = (payload or {}).get("profile") or "dev10"
    if profile not in BENCHMARK_PROFILE_SPLITS:
        return operation_failed(
            f"unknown benchmark profile: {profile}", kind="validation"
        )
    if profile == "full50" and not payload.get("full50_explicitly_authorized"):
        return operation_failed(
            "the full50 profile runs the complete contribution regression "
            "and requires separate explicit authorization",
            kind="authority",
            blockers=["full50"],
            next_action="record full50_explicitly_authorized for the full profile",
        )
    from stella.workflows import DEFAULT_ROOT

    # The frozen campaign sample is repository data; only the run record
    # lives under the (possibly temporary) execution root.
    source_manifest = (
        DEFAULT_ROOT
        / "benchmark"
        / "campaigns"
        / ACTIVE_BENCHMARK_CAMPAIGN
        / "manifest"
        / "campaign_manifest.json"
    )
    if not source_manifest.is_file():
        return operation_failed(
            f"the frozen campaign manifest is missing: {source_manifest}",
            kind="precondition",
        )
    try:
        campaign = json.loads(source_manifest.read_text(encoding="utf-8"))
    except ValueError as error:
        return operation_failed(
            f"invalid campaign manifest: {error}", kind="validation"
        )
    selected_ids = set(papers_for_profile(campaign, profile))
    papers = [
        {
            "arxiv_id": paper["arxiv_id"],
            "split": paper.get("split"),
        }
        for paper in campaign.get("papers") or []
        if paper.get("arxiv_id") in selected_ids
    ]
    if not papers:
        return operation_failed(
            "the campaign sample resolved to zero papers; refusing to run",
            kind="precondition",
        )
    run_id = (payload or {}).get("run_id") or os.environ.get(
        "STELLA_WORKER_RUN_ID", ""
    )
    if not run_id:
        return operation_failed(
            "campaign preparation requires the outer run id",
            kind="precondition",
        )
    run_dir = Path(root) / "runs" / "benchmark" / run_id
    campaign_record = {
        "schema": {"name": "benchmark.campaign", "version": 1},
        "profile": profile,
        "campaign_id": campaign.get("campaign_id"),
        "source_manifest_sha256": sha256_file(source_manifest),
        "papers": papers,
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    campaign_path = run_dir / "campaign.json"
    campaign_path.write_text(
        json.dumps(campaign_record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return operation_complete(
        artifacts=[str(campaign_path)],
        profile=profile,
        paper_count=len(papers),
        note="campaign sample frozen under the requested run id",
    )


def validate_manifest(payload: dict, result: dict, *, root: Path) -> list[str]:
    """A completed campaign preparation must carry a validated profile."""

    if result.get("status") != "complete":
        return []
    profile = (result.get("detail") or {}).get("profile")
    if profile not in BENCHMARK_PROFILE_SPLITS:
        return [f"campaign preparation reported an unknown profile: {profile!r}"]
    return []
