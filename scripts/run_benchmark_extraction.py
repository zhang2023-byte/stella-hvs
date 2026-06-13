#!/usr/bin/env python3
"""Run direct-API benchmark extractions and archive them under benchmark/runs/.

Examples:
    # Free dry run: pack contexts, report sizes, no API calls
    python scripts/run_benchmark_extraction.py --pilot --dry-run

    # Pilot extraction with the default model from .env
    python scripts/run_benchmark_extraction.py --pilot

    # One paper, explicit model and run id
    python scripts/run_benchmark_extraction.py --arxiv-id 2101.10878 \
        --model mimo-v2.5-pro --run-id pilot-mimo

    # Four papers, three at a time
    python scripts/run_benchmark_extraction.py --pilot --parallel 3
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as _dt
import json
from pathlib import Path

from stella.benchmark.context_pack import pack_paper_context, packed_context_summary
from stella.benchmark.extraction_run import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_REPAIR_ROUNDS,
    PILOT_PAPERS,
    PIPELINE_NAME,
    PIPELINE_VERSION,
    PROMPT_TEMPLATE_VERSION,
    build_system_prompt,
    git_short_hash,
    load_frozen_validator,
    run_paper,
)
from stella.lit.env import env_value, load_env_files
from stella.lit.schema_templates import build_hvs_candidates_template

WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_RUNS_DIR = WORKSPACE / "benchmark" / "runs"

# Pin each roster model to its first-party TokenDance provider: the gateway's
# default routing is price-first over *average* rates, which can land on an
# endpoint whose prompt-cache hits cost ~40x more — and cache hits dominate
# the repair-loop economics (86-94% measured hit rate). Fallbacks to other
# providers stay allowed for availability; the archived responses record what
# actually served each call. Tags verified live against the gateway
# (unknown tags are rejected with HTTP 400, so typos cannot mis-route).
DEFAULT_PROVIDER_ORDER = {
    "deepseek-v4-pro": ["deepseek"],
    "deepseek-v4-flash": ["deepseek"],
    # mimo: xiaomi and infini-ai are same-priced (¥3/¥6/¥0.025), but the
    # xiaomi endpoint returned 0% prompt-cache hits on pilot-08's repeated
    # full-context reposts (site stats: xiaomi 20.7% vs infini-ai 75.9%).
    # Prefer infini-ai for the cache tier; xiaomi stays as fallback.
    "mimo-v2.5-pro": ["infini-ai", "xiaomi"],
    "mimo-v2.5": ["infini-ai", "xiaomi"],
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Direct-API benchmark extraction runner."
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
        help="Model id. Default: LLM_MODEL from the environment.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Run directory name. Default: <UTCdate>-<model>.",
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
        help=f"Bounded validator-feedback repair rounds. Default: {DEFAULT_MAX_REPAIR_ROUNDS}.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Candidates per stage-2 fill batch. Default: {DEFAULT_BATCH_SIZE}.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="Optional max_tokens override (default: provider maximum).",
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
        help="Papers processed concurrently (each paper stays sequential "
        "internally). Default: 1.",
    )
    parser.add_argument(
        "--provider",
        action="append",
        default=None,
        help="Preferred gateway provider tag(s), in priority order "
        "(repeatable). Default: first-party pin from DEFAULT_PROVIDER_ORDER "
        "for known models. Pass --no-provider-pin to disable.",
    )
    parser.add_argument(
        "--no-provider-pin",
        action="store_true",
        help="Use the gateway's default price-first routing.",
    )
    parser.add_argument(
        "--fallback-model",
        action="append",
        default=None,
        help="Fallback model id(s) tried if every provider of the main "
        "model fails (repeatable; gateway 'models' field).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Pack contexts and report prompt sizes without calling the API.",
    )
    return parser


def build_request_extra(args, model: str) -> dict:
    """Gateway routing fields for the request body (also archived as
    tooling provenance in each output document)."""

    extra: dict = {}
    if not args.no_provider_pin:
        order = args.provider or DEFAULT_PROVIDER_ORDER.get(model)
        if order:
            extra["provider"] = {"order": list(order)}
    if args.fallback_model:
        extra["models"] = list(dict.fromkeys(args.fallback_model))
    return extra


def main() -> int:
    args = build_parser().parse_args()
    load_env_files(WORKSPACE)
    papers = list(PILOT_PAPERS) if args.pilot else list(dict.fromkeys(args.arxiv_id))
    model = args.model or env_value("LLM_MODEL")
    if not model:
        raise SystemExit("set LLM_MODEL in .env or pass --model")

    if args.dry_run:
        system_chars = len(build_system_prompt(WORKSPACE))
        print(f"system prompt: {system_chars} chars")
        for arxiv_id in papers:
            skeleton = build_hvs_candidates_template(
                literature_dir=WORKSPACE / "literature",
                arxiv_id=arxiv_id,
                workspace=WORKSPACE,
            )
            context = pack_paper_context(
                WORKSPACE, arxiv_id, list(skeleton["inputs"]["ecsv_paths"])
            )
            estimate = (system_chars + context.total_chars) // 4
            print(f"\n{arxiv_id}: ~{estimate} input tokens (rough /4 estimate)")
            print(packed_context_summary(context))
        return 0

    api_key = env_value("LLM_API_KEY")
    base_url = env_value("LLM_BASE_URL")
    if not api_key or not base_url:
        raise SystemExit("LLM_API_KEY and LLM_BASE_URL are required in .env")

    prompt_version = git_short_hash(WORKSPACE)
    request_extra = build_request_extra(args, model)
    run_id = args.run_id or f"{_dt.datetime.now():%Y%m%d-%H%M}-{model}"
    run_dir = args.runs_dir.expanduser() / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_config.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "pipeline": f"{PIPELINE_NAME}/{PIPELINE_VERSION}",
                "prompt_template_version": PROMPT_TEMPLATE_VERSION,
                "prompt_version": prompt_version,
                "model": model,
                "base_url": base_url,
                "temperature": 0,
                "max_tokens": args.max_tokens,
                "max_repair_rounds": args.max_repair_rounds,
                "batch_size": args.batch_size,
                "request_extra": request_extra,
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
    if request_extra:
        print(f"gateway routing: {json.dumps(request_extra, ensure_ascii=False)}")

    def run_one(arxiv_id: str):
        # Each worker loads its own validator module instance so no state
        # is shared between concurrently running papers.
        return run_paper(
            workspace=WORKSPACE,
            arxiv_id=arxiv_id,
            run_dir=run_dir,
            api_key=api_key,
            base_url=base_url,
            model=model,
            prompt_version=prompt_version,
            batch_size=args.batch_size,
            max_repair_rounds=args.max_repair_rounds,
            max_tokens=args.max_tokens,
            timeout_seconds=args.timeout_seconds,
            request_extra=request_extra,
            validator_module=load_frozen_validator(WORKSPACE),
        )

    def report(result) -> None:
        print(
            f"{result.arxiv_id}: {result.status} "
            f"(scaffold={result.scaffold_attempts}, batches={result.batch_count}, "
            f"batch_calls={result.batch_calls}, repairs={result.repair_rounds}, "
            f"errors={result.validator_errors}, usage={result.usage_totals})",
            flush=True,
        )
        if result.error:
            print(f"  transport error: {result.error}", flush=True)

    failures = 0
    workers = max(1, args.parallel)
    if workers == 1:
        for arxiv_id in papers:
            print(f"=== {arxiv_id} ({model}) ===", flush=True)
            result = run_one(arxiv_id)
            report(result)
            if result.status not in ("ok", "ok_with_cjk_warnings"):
                failures += 1
    else:
        print(f"running {len(papers)} papers, {workers} at a time ({model})", flush=True)
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
