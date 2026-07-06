#!/usr/bin/env python3
"""Scaffold a run config for a method-A (skill-agent) benchmark rerun.

Methods B and C write their ``run_config.json`` programmatically; method A
extractions are produced by a human-driven coding agent, so this script
creates the same archive contract up front. It records the **agent harness**
(name and version of the coding-agent runtime, e.g. Cursor or Claude Code)
and the **model** alongside the usual run facts, so agent runs are as
reproducible as pipeline runs. The scorer copies ``harness`` into the
scorecard's ``run_source`` and the HTML report displays it.

The extracting agent then fills, for each paper,
``benchmark/runs/<run_id>/<arxiv_id>/literature_hvs_candidates.json``
(current schema, semantic validator must pass) with
``extraction.tooling.agent_runtime = "<harness>/<version>"`` and
``extraction.tooling.model_id`` matching this config.

Usage:
    conda run -n stella-env python scripts/init_agent_run.py \
        --run-id gold8-a-01-cursor-sonnet \
        --harness cursor --harness-version 2.3.1 \
        --model claude-sonnet-5-thinking \
        --arxiv-id 1804.10179 --arxiv-id 1807.00427
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import subprocess
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_RUNS_DIR = WORKSPACE / "benchmark" / "runs"

PIPELINE_NAME = "stella-skill-agent-extraction"
PIPELINE_VERSION = "1.0.0"


def git_short_hash(workspace: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create run_config.json for a skill-agent (method A) run."
    )
    parser.add_argument(
        "--run-id", required=True, help="Run directory name under benchmark/runs/."
    )
    parser.add_argument(
        "--harness",
        required=True,
        help="Coding-agent harness name, e.g. 'cursor' or 'claude-code'.",
    )
    parser.add_argument(
        "--harness-version",
        required=True,
        help="Harness version string as reported by the tool.",
    )
    parser.add_argument(
        "--model",
        required=True,
        help="Model id the harness session uses (dated snapshot if available).",
    )
    parser.add_argument(
        "--arxiv-id",
        action="append",
        required=True,
        help="Paper id (repeatable).",
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=DEFAULT_RUNS_DIR,
        help="Runs root. Default: benchmark/runs/",
    )
    parser.add_argument(
        "--notes",
        default="",
        help="Optional free-text notes (sandboxing setup, session policy).",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    run_dir = args.runs_dir.expanduser() / args.run_id
    config_path = run_dir / "run_config.json"
    if config_path.exists():
        raise SystemExit(f"refusing to overwrite existing {config_path}")

    config = {
        "run_id": args.run_id,
        "pipeline": f"{PIPELINE_NAME}/{PIPELINE_VERSION}",
        "harness": {"name": args.harness, "version": args.harness_version},
        "model": args.model,
        "prompt_version": git_short_hash(WORKSPACE),
        "papers": sorted(dict.fromkeys(args.arxiv_id)),
        "created_at": _dt.datetime.now().isoformat(timespec="seconds"),
    }
    if args.notes:
        config["notes"] = args.notes

    run_dir.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote {config_path}")
    print(
        "Per-paper output contract: "
        f"{run_dir}/<arxiv_id>/literature_hvs_candidates.json with "
        f"extraction.tooling.agent_runtime = "
        f"\"{args.harness}/{args.harness_version}\" and "
        f"extraction.tooling.model_id = \"{args.model}\"; validate each file "
        "with scripts/validate_hvs_candidates.py --require-complete. The "
        "extracting agent reads only literature/<arxiv_id>/ inputs (never "
        "gold, runs, or scoring outputs)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
