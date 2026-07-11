"""Campaign-scoped benchmark path resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from stella.schema_registry import ACTIVE_BENCHMARK_CAMPAIGN


@dataclass(frozen=True)
class CampaignPaths:
    root: Path
    manifest: Path
    sampling_manifest: Path
    campaign_manifest: Path
    gold_manifest: Path
    runs: Path
    releases: Path
    scoring: Path


def campaign_paths(workspace: Path, campaign_id: str = ACTIVE_BENCHMARK_CAMPAIGN) -> CampaignPaths:
    if not campaign_id or "/" in campaign_id or ".." in campaign_id:
        raise ValueError(f"invalid campaign id: {campaign_id!r}")
    root = workspace / "benchmark" / "campaigns" / campaign_id
    manifest = root / "manifest"
    return CampaignPaths(
        root=root,
        manifest=manifest,
        sampling_manifest=manifest / "sampling_manifest.json",
        campaign_manifest=manifest / "campaign_manifest.json",
        gold_manifest=manifest / "gold_manifest.json",
        runs=root / "runs",
        releases=root / "releases",
        scoring=root / "scoring",
    )
