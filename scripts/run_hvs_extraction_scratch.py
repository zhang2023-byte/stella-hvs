#!/usr/bin/env python3
"""Run the hvs_extraction_scratch pipeline for explicit papers.

Scratch runs stay isolated under ``benchmark/scratch/hvs-extraction/runs/``
and never touch formal campaign paths. Real model requests require
``LLM_API_KEY`` and ``LLM_BASE_URL`` in ``.env`` and the user's explicit
authorization for LLM calls.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stella.benchmark.scratch.method_config import default_scratch_method_config
from stella.benchmark.scratch.run import create_run_config, run_papers
from stella.lit.env import env_value
from stella.lit.llm_batch import chat_completion_raw


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-id",
        default=None,
        help="run identity; default scratch-<UTC timestamp>",
    )
    parser.add_argument(
        "--variant",
        choices=("ensemble", "single"),
        default="ensemble",
        help="roster construction variant (default: ensemble)",
    )
    parser.add_argument(
        "--arxiv-id",
        action="append",
        required=True,
        help="paper to process; repeat for multiple papers",
    )
    parser.add_argument(
        "--rerun-failed",
        action="store_true",
        help="rerun papers whose paper_result is failed",
    )
    parser.add_argument("--paper-workers", type=int, default=2)
    parser.add_argument("--candidate-workers", type=int, default=4)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_id = args.run_id or "scratch-" + datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    api_key = env_value("LLM_API_KEY")
    base_url = env_value("LLM_BASE_URL")
    if not api_key or not base_url:
        raise SystemExit("LLM_API_KEY and LLM_BASE_URL are required in .env")
    config = default_scratch_method_config(ROOT)
    create_run_config(
        ROOT, run_id, sorted(set(args.arxiv_id)), config=config, variant=args.variant
    )
    summary = run_papers(
        ROOT,
        run_id,
        sorted(set(args.arxiv_id)),
        config=config,
        variant=args.variant,
        transport=chat_completion_raw,
        api_key=api_key,
        base_url=base_url,
        rerun_failed=args.rerun_failed,
        paper_workers=args.paper_workers,
        candidate_workers=args.candidate_workers,
    )
    print(json.dumps(summary["totals"], ensure_ascii=False, indent=2))
    print(f"run summary: benchmark/scratch/hvs-extraction/runs/{run_id}/run_summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
