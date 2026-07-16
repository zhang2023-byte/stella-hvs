#!/usr/bin/env python3
"""Create a method-A run config under the shared benchmark run contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stella.benchmark.campaign import papers_for_split, sha256_file
from stella.benchmark.components import build_run_component_hashes
from stella.benchmark.run_contract import (
    build_run_config,
    ensure_run_config,
    git_state,
)
from stella.benchmark.paths import campaign_paths
from stella.schema_registry import ACTIVE_BENCHMARK_CAMPAIGN, STELLA_RELEASE
from stella.lit.arxiv_ids import validate_unversioned_arxiv_id
from stella.lit.extraction_rules import (
    assert_generated_rule_views_current,
    rule_profile_sha256,
)
from stella.benchmark.task_surfaces import FULL, surface_binding

WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_RUNS_DIR = campaign_paths(WORKSPACE).runs
PIPELINE_NAME = "stella-skill-agent-extraction"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a method-A run config.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--harness", required=True)
    parser.add_argument("--harness-version", required=True)
    parser.add_argument("--model", required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--campaign", help=f"Campaign id (default active: {ACTIVE_BENCHMARK_CAMPAIGN}).")
    selection.add_argument("--campaign-manifest", type=Path)
    selection.add_argument("--arxiv-id", action="append", type=validate_unversioned_arxiv_id)
    parser.add_argument("--split", choices=("dev", "test"))
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--notes", default="")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    assert_generated_rule_views_current(WORKSPACE)
    if args.campaign:
        paths = campaign_paths(WORKSPACE, args.campaign)
        args.campaign_manifest = paths.campaign_manifest
        if args.runs_dir == DEFAULT_RUNS_DIR:
            args.runs_dir = paths.runs
    campaign = None
    if args.campaign_manifest:
        if args.split is None:
            raise SystemExit("--campaign/--campaign-manifest requires --split dev|test")
        campaign = json.loads(args.campaign_manifest.read_text(encoding="utf-8"))
        papers = papers_for_split(campaign, args.split)
    else:
        if args.split is not None:
            raise SystemExit("--split requires --campaign-manifest")
        papers = sorted(dict.fromkeys(args.arxiv_id or []))
    method = {
        "producer": PIPELINE_NAME,
        "runtime": {"name": args.harness, "release": args.harness_version},
        "models": {"extractor": args.model, "reviewer": None},
        "providers": {"extractor": []},
        "provenance": {
            "stella_release": STELLA_RELEASE,
            "code_commit": git_state(WORKSPACE)["commit"],
            "components": {},
        },
        "parameters": {
            "rule_profile_id": "hvs_extractor",
            "rule_profile_sha256": rule_profile_sha256(
                WORKSPACE, "hvs_extractor"
            ),
            **surface_binding(WORKSPACE, FULL),
        },
    }
    method["provenance"]["components"] = build_run_component_hashes(WORKSPACE, method)
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
