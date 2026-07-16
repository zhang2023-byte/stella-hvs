#!/usr/bin/env python3
"""Archive benchmark v1 byte-for-byte and initialize campaign-scoped v2."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from stella.benchmark.campaign import build_campaign, sha256_file
from stella.legacy_versions import normalize_legacy_schema
from stella.schema_registry import schema_ref

WORKSPACE = Path(__file__).resolve().parents[1]
BENCHMARK = WORKSPACE / "benchmark"
V1 = BENCHMARK / "campaigns" / "hvs-extraction-v1"
V2_CAMPAIGN_ID = "hvs-extraction-v2"
V2 = BENCHMARK / "campaigns" / V2_CAMPAIGN_ID


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _current_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=WORKSPACE, check=True, capture_output=True, text=True
    ).stdout.strip()


def _move_contents(source: Path, destination: Path, records: list[dict], *, write: bool) -> None:
    if not source.exists():
        return
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.name in {".DS_Store", ".gitkeep"}:
            continue
        relative = path.relative_to(source)
        target = destination / relative
        before = _digest(path)
        records.append({"source": str(path.relative_to(WORKSPACE)), "destination": str(target.relative_to(WORKSPACE)), "sha256": before, "bytes": path.stat().st_size})
        if write:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(target))
            if _digest(target) != before:
                raise RuntimeError(f"hash changed while archiving {path}")


def migrate(*, write: bool) -> dict:
    records: list[dict] = []
    for name in ("manifest", "runs", "releases", "scoring"):
        _move_contents(BENCHMARK / name, V1 / name, records, write=write)
    report = {
        "schema": schema_ref("benchmark.archive_inventory"),
        "campaign_id": "hvs-extraction-v1",
        "files": records,
    }
    if not write:
        return report

    V1.mkdir(parents=True, exist_ok=True)
    (V1 / "archive_inventory.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for name in ("manifest", "runs", "releases", "scoring"):
        (V2 / name).mkdir(parents=True, exist_ok=True)

    old_sampling = json.loads((V1 / "manifest" / "sampling_manifest.json").read_text(encoding="utf-8"))
    sampling = normalize_legacy_schema(old_sampling)
    sampling_path = V2 / "manifest" / "sampling_manifest.json"
    sampling_path.write_text(json.dumps(sampling, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    old_gold = json.loads((V1 / "manifest" / "gold_manifest.json").read_text(encoding="utf-8"))
    gold = normalize_legacy_schema(old_gold)
    (V2 / "manifest" / "gold_manifest.json").write_text(json.dumps(gold, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    campaign = build_campaign(
        sampling,
        sampling_manifest_sha256=sha256_file(sampling_path),
        sampling_manifest_path=str(sampling_path.relative_to(WORKSPACE)),
        code_commit=_current_commit(),
        campaign_id=V2_CAMPAIGN_ID,
    )
    (V2 / "manifest" / "campaign_manifest.json").write_text(
        json.dumps(campaign, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    report = migrate(write=args.write)
    print(json.dumps({"write": args.write, "files": len(report["files"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
