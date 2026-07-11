"""Persistent authorization records for sealed formal test runs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stella.benchmark.campaign import sha256_file
from stella.benchmark.paths import validate_path_segment
from stella.schema_registry import require_schema, schema_ref


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _bindings(campaign_path: Path, run_dir: Path) -> dict[str, str]:
    campaign = _load(campaign_path)
    try:
        require_schema(campaign, "benchmark.campaign", require_current=True)
    except ValueError as exc:
        raise ValueError("test release requires a current campaign manifest") from exc
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.is_file():
        raise ValueError("run must be sealed before test release")
    manifest = _load(manifest_path)
    try:
        require_schema(manifest, "benchmark.run_manifest", require_current=True)
    except ValueError:
        raise ValueError("test release requires run manifest v0.1")
    if manifest.get("split") != "test":
        raise ValueError("test release requires a test split run")
    if (manifest.get("leakage_audit") or {}).get("status") != "clean":
        raise ValueError("test release requires a clean leakage audit")
    campaign_hash = sha256_file(campaign_path)
    if (manifest.get("campaign") or {}).get("campaign_id") != campaign.get("campaign_id"):
        raise ValueError("run campaign id does not match campaign manifest")
    if (manifest.get("campaign") or {}).get("sha256") != campaign_hash:
        raise ValueError("run campaign hash does not match campaign manifest")
    run_id = validate_path_segment(str(manifest["run_id"]), "run id")
    return {
        "campaign_id": str(campaign["campaign_id"]),
        "campaign_sha256": campaign_hash,
        "run_id": run_id,
        "run_manifest_sha256": sha256_file(manifest_path),
    }


def build_test_release(*, campaign_path: Path, run_dir: Path) -> dict[str, Any]:
    values = _bindings(campaign_path.resolve(), run_dir.resolve())
    return {
        "schema": schema_ref("benchmark.test_release"),
        "campaign": {"campaign_id": values["campaign_id"], "sha256": values["campaign_sha256"]},
        "run": {
            "run_id": values["run_id"],
            "manifest_sha256": values["run_manifest_sha256"],
            "split": "test",
        },
        "released_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "eligibility": {"sealed": True, "leakage_audit": "clean"},
    }


def _release_path(releases_root: Path, release: dict[str, Any]) -> Path:
    run_id = validate_path_segment(str(release["run"]["run_id"]), "run id")
    return releases_root / f"{run_id}.json"


def write_test_release(*, release: dict[str, Any], releases_root: Path) -> Path:
    path = _release_path(releases_root, release)
    if path.is_file():
        existing = _load(path)
        keys = ("schema", "campaign", "run", "eligibility")
        if any(existing.get(key) != release.get(key) for key in keys):
            raise ValueError("existing release has different bindings")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(release, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def find_matching_release(*, campaign_path: Path, run_dir: Path, releases_root: Path) -> Path | None:
    values = _bindings(campaign_path.resolve(), run_dir.resolve())
    path = releases_root / f"{values['run_id']}.json"
    if not path.is_file():
        return None
    release = _load(path)
    try:
        require_schema(release, "benchmark.test_release", require_current=True)
    except ValueError:
        return None
    if release.get("campaign") != {"campaign_id": values["campaign_id"], "sha256": values["campaign_sha256"]}:
        return None
    if release.get("run") != {"run_id": values["run_id"], "manifest_sha256": values["run_manifest_sha256"], "split": "test"}:
        return None
    if release.get("eligibility") != {"sealed": True, "leakage_audit": "clean"}:
        return None
    return path
