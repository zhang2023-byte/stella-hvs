#!/usr/bin/env python3
"""Refresh the gold integrity manifest from the external private gold store.

Gold annotations live outside this workspace, in the private gold repository
pointed to by STELLA_GOLD_DIR. This script records the SHA256 of every formal
annotation file there into the active campaign gold_manifest.json so the public
toolchain can verify gold integrity (and scorers can pin exactly which gold
state a run was scored against) without ever containing gold content.

Usage:
    conda run -n stella-env python scripts/update_gold_manifest.py
    conda run -n stella-env python scripts/update_gold_manifest.py --gold-dir <path>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from stella.lit.env import load_env_files
from stella.benchmark.paths import campaign_paths, require_external_path
from stella.benchmark.gold_manifest import validate_append_only_gold_manifest
from stella.schema_registry import schema_ref

WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = campaign_paths(WORKSPACE).gold_manifest
GOLD_DIR_ENV = "STELLA_GOLD_DIR"


def default_gold_dir() -> Path | None:
    value = os.environ.get(GOLD_DIR_ENV, "").strip()
    return Path(value).expanduser() if value else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write SHA256 records for every formal gold annotation file."
    )
    parser.add_argument(
        "--gold-dir",
        type=Path,
        default=None,
        help=f"External private gold annotation root. Default: ${GOLD_DIR_ENV}.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Manifest output path. Default: the active campaign gold_manifest.json.",
    )
    return parser


def file_record(gold_dir: Path, path: Path) -> dict:
    payload = path.read_bytes()
    return {
        "arxiv_id": path.parent.name,
        "file": path.relative_to(gold_dir).as_posix(),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
    }


def build_manifest(gold_dir: Path) -> dict:
    files = sorted(
        gold_dir.glob("*/annotation_*.yaml")
    ) + sorted(gold_dir.glob("*/annotation_*.json"))
    records = [file_record(gold_dir, path) for path in files]
    records.sort(key=lambda record: record["file"])
    return {
        "schema": schema_ref("benchmark.gold_manifest"),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "paper_count": len({record["arxiv_id"] for record in records}),
        "annotation_yaml_count": sum(
            1 for record in records if record["file"].endswith(".yaml")
        ),
        "annotation_json_count": sum(
            1 for record in records if record["file"].endswith(".json")
        ),
        "files": records,
    }


def main() -> int:
    load_env_files(WORKSPACE)
    args = build_parser().parse_args()
    gold_dir = args.gold_dir if args.gold_dir is not None else default_gold_dir()
    if gold_dir is None:
        raise SystemExit(
            f"Set {GOLD_DIR_ENV} or pass --gold-dir to the external private "
            "gold annotation root."
        )
    try:
        gold_dir = require_external_path(
            gold_dir, workspace=WORKSPACE, label="gold directory"
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if not gold_dir.is_dir():
        raise SystemExit(f"gold directory not found: {gold_dir}")
    manifest = build_manifest(gold_dir)
    if args.output.is_file():
        previous = json.loads(args.output.read_text(encoding="utf-8"))
        validate_append_only_gold_manifest(previous, manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {args.output} ("
        f"{manifest['paper_count']} papers, "
        f"{manifest['annotation_yaml_count']} yaml, "
        f"{manifest['annotation_json_count']} json)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
