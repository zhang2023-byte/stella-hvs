#!/usr/bin/env python3
"""Build the frozen hvs-extraction-v1 campaign manifest."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from stella.benchmark.campaign import (
    DEFAULT_FREEZE_TAG,
    build_campaign,
    sha256_file,
)

WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLING = WORKSPACE / "benchmark" / "manifest" / "sampling_manifest.json"
DEFAULT_OUTPUT = WORKSPACE / "benchmark" / "manifest" / "campaign_manifest.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build hvs-extraction-v1 campaign manifest")
    parser.add_argument("--sampling-manifest", type=Path, default=DEFAULT_SAMPLING)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--freeze-tag", default=DEFAULT_FREEZE_TAG)
    return parser


def resolve_tag(tag: str) -> str:
    result = subprocess.run(
        ["git", "rev-list", "-n", "1", tag],
        cwd=WORKSPACE,
        check=True,
        capture_output=True,
        text=True,
    )
    commit = result.stdout.strip()
    if not commit:
        raise ValueError(f"freeze tag does not resolve: {tag}")
    return commit


def main() -> int:
    args = build_parser().parse_args()
    sampling_path = args.sampling_manifest.resolve()
    sampling = json.loads(sampling_path.read_text(encoding="utf-8"))
    try:
        display_path = str(sampling_path.relative_to(WORKSPACE))
    except ValueError:
        display_path = str(sampling_path)
    campaign = build_campaign(
        sampling,
        sampling_manifest_sha256=sha256_file(sampling_path),
        sampling_manifest_path=display_path,
        freeze_tag=args.freeze_tag,
        freeze_commit=resolve_tag(args.freeze_tag),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(campaign, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Campaign: {campaign['campaign_id']}")
    print(f"Splits: {campaign['splits']}")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
