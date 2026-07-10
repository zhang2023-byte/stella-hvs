#!/usr/bin/env python3
"""Create a method-A run config under the shared benchmark run contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stella.benchmark.campaign import papers_for_split, sha256_file
from stella.benchmark.context_pack import PACKER_VERSION
from stella.benchmark.run_contract import (
    build_run_config,
    canonical_sha256,
    ensure_run_config,
    git_state,
)

WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_RUNS_DIR = WORKSPACE / "benchmark" / "runs"
PIPELINE_NAME = "stella-skill-agent-extraction"
PIPELINE_VERSION = "1.1.0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a method-A run config.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--harness", required=True)
    parser.add_argument("--harness-version", required=True)
    parser.add_argument("--model", required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--campaign-manifest", type=Path)
    selection.add_argument("--arxiv-id", action="append")
    parser.add_argument("--split", choices=("dev", "test"))
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--notes", default="")
    return parser


def _skill_hash() -> str:
    skill_root = WORKSPACE / "skills" / "hvs-candidates-extraction"
    return canonical_sha256(
        {
            str(path.relative_to(WORKSPACE)): sha256_file(path)
            for path in sorted(skill_root.rglob("*"))
            if path.is_file()
        }
    )


def main() -> int:
    args = build_parser().parse_args()
    campaign = None
    if args.campaign_manifest:
        if args.split is None:
            raise SystemExit("--campaign-manifest requires --split dev|test")
        campaign = json.loads(args.campaign_manifest.read_text(encoding="utf-8"))
        papers = papers_for_split(campaign, args.split)
    else:
        if args.split is not None:
            raise SystemExit("--split requires --campaign-manifest")
        papers = sorted(dict.fromkeys(args.arxiv_id or []))
    method = {
        "pipeline": {"name": PIPELINE_NAME, "version": PIPELINE_VERSION},
        "harness": {"name": args.harness, "version": args.harness_version},
        "models": {"extractor": args.model, "reviewer": None},
        "providers": {"extractor": []},
        "versions": {
            "prompt": git_state(WORKSPACE)["commit"][:12],
            "skill": _skill_hash(),
            "validator": sha256_file(WORKSPACE / "scripts" / "validate_hvs_candidates.py"),
            "context_packer": PACKER_VERSION,
        },
    }
    config = build_run_config(
        run_id=args.run_id,
        method=method,
        expected_papers=papers,
        code=git_state(WORKSPACE),
        campaign=campaign,
        campaign_sha256=sha256_file(args.campaign_manifest) if args.campaign_manifest else None,
        split=args.split or "experimental",
    )
    if args.notes:
        config["notes"] = args.notes
    run_dir = args.runs_dir.expanduser() / args.run_id
    ensure_run_config(run_dir, config)
    print(f"Wrote {run_dir / 'run_config.json'}")
    print("Use scripts/run_agent_harness.py prepare, launch, and collect for each paper.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
