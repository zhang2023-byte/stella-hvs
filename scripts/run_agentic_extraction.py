#!/usr/bin/env python3
"""Run agentic (tool-driven ReAct) benchmark extractions — method C.

Archives runs under benchmark/runs/ in the same layout as the staged
direct-API pipeline, plus per-call request archives and the reviewer's
challenge list. Inputs come only from literature/<arxiv_id>/ via the
deterministic context packer.

Examples:
    # One pilot paper, defaults from .env
    python scripts/run_agentic_extraction.py --arxiv-id 1901.04559 \
        --run-id pilot-agentic-smoke

    # An evaluation set, three papers at a time
    python scripts/run_agentic_extraction.py --arxiv-id ... --parallel 3
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as _dt
import json
from pathlib import Path

from stella.benchmark.agentic_run import (
    DEFAULT_MAX_REPAIR_ROUNDS,
    DEFAULT_REVIEWER_MODEL,
    PIPELINE_NAME,
    PIPELINE_VERSION,
    run_paper_agentic,
)
from stella.benchmark.extraction_run import (
    PILOT_PAPERS,
    git_short_hash,
    load_frozen_validator,
)
from stella.lit.env import env_value, load_env_files

WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_RUNS_DIR = WORKSPACE / "benchmark" / "runs"

# First-party provider pins (same rationale as the staged pipeline: the
# gateway's price-first routing can land on endpoints with a 40x prompt-cache
# price, and tool loops repost history often).
DEFAULT_PROVIDER_ORDER = {
    "deepseek-v4-pro": ["deepseek"],
    "deepseek-v4-flash": ["deepseek"],
    "mimo-v2.5-pro": ["infini-ai", "xiaomi"],
    "mimo-v2.5": ["infini-ai", "xiaomi"],
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Agentic (ReAct) benchmark extraction runner."
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument(
        "--arxiv-id", action="append", default=None, help="Paper id (repeatable)."
    )
    selection.add_argument(
        "--pilot",
        action="store_true",
        help=f"Run the pilot papers: {', '.join(PILOT_PAPERS)}.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Extractor model id. Default: LLM_MODEL from the environment.",
    )
    parser.add_argument(
        "--reviewer-model",
        default=DEFAULT_REVIEWER_MODEL,
        help=f"Independent reviewer model id. Default: {DEFAULT_REVIEWER_MODEL}.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Run directory name. Default: <UTCdate>-agentic-<model>.",
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=DEFAULT_RUNS_DIR,
        help="Runs root. Default: benchmark/runs/",
    )
    parser.add_argument(
        "--max-repair-rounds",
        type=int,
        default=DEFAULT_MAX_REPAIR_ROUNDS,
        help=f"Bounded validator repair rounds. Default: {DEFAULT_MAX_REPAIR_ROUNDS}.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=1800,
        help="Per-call HTTP timeout. Default: 1800.",
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=1,
        help="Papers processed concurrently. Default: 1.",
    )
    return parser


def provider_extra(model: str) -> dict:
    order = DEFAULT_PROVIDER_ORDER.get(model)
    return {"provider": {"order": list(order)}} if order else {}


def main() -> int:
    load_env_files(WORKSPACE)
    args = build_parser().parse_args()
    papers = list(PILOT_PAPERS) if args.pilot else list(dict.fromkeys(args.arxiv_id))
    model = args.model or env_value("LLM_MODEL")
    if not model:
        raise SystemExit("set LLM_MODEL in .env or pass --model")
    api_key = env_value("LLM_API_KEY")
    base_url = env_value("LLM_BASE_URL")
    if not api_key or not base_url:
        raise SystemExit("LLM_API_KEY and LLM_BASE_URL are required in .env")

    prompt_version = git_short_hash(WORKSPACE)
    run_id = args.run_id or f"{_dt.datetime.now():%Y%m%d-%H%M}-agentic-{model}"
    run_dir = args.runs_dir.expanduser() / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_config.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "pipeline": f"{PIPELINE_NAME}/{PIPELINE_VERSION}",
                "prompt_version": prompt_version,
                "model": model,
                "reviewer_model": args.reviewer_model,
                "base_url": base_url,
                "temperature": 0,
                "max_repair_rounds": args.max_repair_rounds,
                "request_extra": provider_extra(model),
                "reviewer_request_extra": provider_extra(args.reviewer_model),
                "parallel": args.parallel,
                "papers": papers,
                "created_at": _dt.datetime.now().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    def run_one(arxiv_id: str):
        return run_paper_agentic(
            workspace=WORKSPACE,
            arxiv_id=arxiv_id,
            run_dir=run_dir,
            api_key=api_key,
            base_url=base_url,
            model=model,
            reviewer_model=args.reviewer_model,
            prompt_version=prompt_version,
            max_repair_rounds=args.max_repair_rounds,
            timeout_seconds=args.timeout_seconds,
            request_extra=provider_extra(model),
            reviewer_request_extra=provider_extra(args.reviewer_model),
            validator_module=load_frozen_validator(WORKSPACE),
        )

    def report(result) -> None:
        print(
            f"{result.arxiv_id}: {result.status} "
            f"(plan={result.plan_calls}, cand_calls={result.candidate_calls}, "
            f"repairs={result.repair_calls}, review={result.review_calls}, "
            f"challenges={result.review_challenges}, "
            f"errors={result.validator_errors}, usage={result.usage_totals})",
            flush=True,
        )
        if result.error:
            print(f"  transport error: {result.error}", flush=True)

    failures = 0
    workers = max(1, args.parallel)
    if workers == 1:
        for arxiv_id in papers:
            print(f"=== {arxiv_id} ({model} + reviewer {args.reviewer_model}) ===", flush=True)
            result = run_one(arxiv_id)
            report(result)
            if result.status not in ("ok", "ok_with_cjk_warnings"):
                failures += 1
    else:
        print(
            f"running {len(papers)} papers, {workers} at a time "
            f"({model} + reviewer {args.reviewer_model})",
            flush=True,
        )
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(run_one, pid): pid for pid in papers}
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                report(result)
                if result.status not in ("ok", "ok_with_cjk_warnings"):
                    failures += 1
    print(f"\nRun archived at {run_dir}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
