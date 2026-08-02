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
    gold_selections: Path
    runs: Path
    releases: Path
    scoring: Path


def validate_path_segment(value: str, label: str = "path segment") -> str:
    """Require one non-special filesystem segment for generated artifacts."""

    raw = str(value or "")
    segment = raw.strip()
    if (
        not segment
        or segment != raw
        or segment in {".", ".."}
        or "/" in segment
        or "\\" in segment
        or "\x00" in segment
    ):
        raise ValueError(f"invalid {label}: {value!r}")
    return segment


def require_external_path(path: Path, *, workspace: Path, label: str) -> Path:
    """Resolve a private artifact path and reject the public workspace tree."""

    resolved = path.expanduser().resolve()
    workspace_root = workspace.expanduser().resolve()
    if resolved == workspace_root or resolved.is_relative_to(workspace_root):
        raise ValueError(
            f"refusing {label}: path must be outside the public workspace: {resolved}"
        )
    return resolved


def campaign_paths(workspace: Path, campaign_id: str = ACTIVE_BENCHMARK_CAMPAIGN) -> CampaignPaths:
    campaign_id = validate_path_segment(campaign_id, "campaign id")
    root = workspace / "benchmark" / "campaigns" / campaign_id
    manifest = root / "manifest"
    return CampaignPaths(
        root=root,
        manifest=manifest,
        sampling_manifest=manifest / "sampling_manifest.json",
        campaign_manifest=manifest / "campaign_manifest.json",
        gold_manifest=manifest / "gold_manifest.json",
        gold_selections=manifest / "gold_selections",
        runs=root / "runs",
        releases=root / "releases",
        scoring=root / "scoring",
    )
