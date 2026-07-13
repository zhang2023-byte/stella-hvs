#!/usr/bin/env python3
"""Run agentic (tool-driven ReAct) benchmark extractions — method C.

Archives runs under benchmark/campaigns/hvs-extraction-v2/runs/ in the same layout as the staged
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
    MAX_TOOL_CALLS,
    PIPELINE_NAME,
    build_agentic_system_prompt,
    run_paper_agentic,
)
from stella.benchmark.extraction_review import (
    DEFAULT_REVIEWER_MODEL,
    REVIEW_ACTIONABLE_SEVERITY,
    REVIEW_REVISION_ROUNDS,
    build_reviewer_system_prompt,
)
from stella.benchmark.extraction_run import (
    PILOT_PAPERS,
    git_short_hash,
    load_frozen_validator,
    papers_with_existing_artifacts,
)
from stella.benchmark.campaign import papers_for_split, sha256_file
from stella.benchmark.context_pack import pack_paper_context, packed_context_summary
from stella.benchmark.run_contract import (
    build_run_config,
    canonical_sha256,
    ensure_run_config,
    git_state,
    prepare_paper_retry,
)
from stella.benchmark.paths import campaign_paths
from stella.benchmark.task_surfaces import (
    FULL,
    TASK_SURFACE_IDS,
    surface_binding,
)
from stella.schema_registry import STELLA_RELEASE
from stella.lit.env import env_value, load_env_files
from stella.lit.arxiv_ids import validate_unversioned_arxiv_id
from stella.lit.extraction_rules import (
    assert_generated_rule_views_current,
    rule_profile_sha256,
)
from stella.lit.schema_templates import build_hvs_candidates_template
from stella.lit.schema_docs import assert_generated_schema_docs_current

WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_RUNS_DIR = campaign_paths(WORKSPACE).runs

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
        "--arxiv-id", action="append", default=None, type=validate_unversioned_arxiv_id, help="Paper id (repeatable)."
    )
    selection.add_argument(
        "--pilot",
        action="store_true",
        help=f"Run the pilot papers: {', '.join(PILOT_PAPERS)}.",
    )
    selection.add_argument(
        "--campaign-manifest",
        type=Path,
        help="Formal campaign manifest; requires --split dev|test.",
    )
    selection.add_argument("--campaign", help="Campaign id; resolves manifest and run paths.")
    parser.add_argument("--split", choices=("dev", "test"))
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
        help="Runs root. Default: benchmark/campaigns/hvs-extraction-v2/runs/",
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
    parser.add_argument(
        "--task-surface",
        choices=TASK_SURFACE_IDS,
        default=FULL,
        help="Generation task surface. Default: full.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Pack contexts and report prompt sizes without calling the API.",
    )
    return parser


def provider_extra(model: str) -> dict:
    order = DEFAULT_PROVIDER_ORDER.get(model)
    return {"provider": {"order": list(order)}} if order else {}


def main() -> int:
    load_env_files(WORKSPACE)
    args = build_parser().parse_args()
    assert_generated_rule_views_current(WORKSPACE)
    assert_generated_schema_docs_current(WORKSPACE)
    if args.campaign:
        paths = campaign_paths(WORKSPACE, args.campaign)
        args.campaign_manifest = paths.campaign_manifest
        if args.runs_dir == DEFAULT_RUNS_DIR:
            args.runs_dir = paths.runs
    campaign = None
    if args.campaign_manifest is not None:
        if args.split is None:
            raise SystemExit("--campaign/--campaign-manifest requires --split dev|test")
        campaign = json.loads(args.campaign_manifest.read_text(encoding="utf-8"))
        papers = papers_for_split(campaign, args.split)
    else:
        if args.split is not None:
            raise SystemExit("--split requires --campaign-manifest")
        papers = list(PILOT_PAPERS) if args.pilot else list(dict.fromkeys(args.arxiv_id))
    model = args.model or env_value("LLM_MODEL")
    if not model:
        raise SystemExit("set LLM_MODEL in .env or pass --model")
    if args.dry_run:
        system_chars = len(build_agentic_system_prompt(WORKSPACE, args.task_surface))
        reviewer_chars = len(
            build_reviewer_system_prompt(WORKSPACE, args.task_surface)
        )
        print(f"extractor system prompt: {system_chars} chars")
        print(f"reviewer system prompt: {reviewer_chars} chars")
        for arxiv_id in papers:
            skeleton = build_hvs_candidates_template(
                literature_dir=WORKSPACE / "literature",
                arxiv_id=arxiv_id,
                workspace=WORKSPACE,
            )
            context = pack_paper_context(
                WORKSPACE, arxiv_id, list(skeleton["inputs"]["ecsv_paths"])
            )
            print(f"\n{arxiv_id}: read-only tool context")
            print(packed_context_summary(context))
        return 0
    api_key = env_value("LLM_API_KEY")
    base_url = env_value("LLM_BASE_URL")
    if not api_key or not base_url:
        raise SystemExit("LLM_API_KEY and LLM_BASE_URL are required in .env")

    prompt_version = git_short_hash(WORKSPACE)
    run_id = args.run_id or f"{_dt.datetime.now():%Y%m%d-%H%M}-agentic-{model}"
    run_dir = args.runs_dir.expanduser() / run_id
    if campaign is not None and model == args.reviewer_model:
        raise SystemExit("formal method C requires distinct extractor and reviewer model ids")
    code = git_state(WORKSPACE)
    skill_files = sorted(
        path
        for path in (WORKSPACE / "skills" / "hvs-candidates-extraction").rglob("*")
        if path.is_file()
    )
    extractor_extra = provider_extra(model)
    reviewer_extra = provider_extra(args.reviewer_model)
    method = {
        "producer": PIPELINE_NAME,
        "models": {"extractor": model, "reviewer": args.reviewer_model},
        "providers": {
            "extractor": extractor_extra.get("provider", {}).get("order", []),
            "reviewer": reviewer_extra.get("provider", {}).get("order", []),
        },
        "provenance": {
            "stella_release": STELLA_RELEASE,
            "code_commit": code["commit"],
            "components": {
                "prompt": sha256_file(
                    WORKSPACE / "src" / "stella" / "benchmark" / "agentic_run.py"
                ),
                "reviewer": sha256_file(
                    WORKSPACE
                    / "src"
                    / "stella"
                    / "benchmark"
                    / "extraction_review.py"
                ),
                "tool_loop": sha256_file(
                    WORKSPACE
                    / "src"
                    / "stella"
                    / "benchmark"
                    / "tool_loop.py"
                ),
                "skill": canonical_sha256(
                    {
                        str(path.relative_to(WORKSPACE)): sha256_file(path)
                        for path in skill_files
                    }
                ),
                "validator": sha256_file(
                    WORKSPACE / "scripts" / "validate_hvs_candidates.py"
                ),
                "context_packer": sha256_file(
                    WORKSPACE / "src" / "stella" / "benchmark" / "context_pack.py"
                ),
            },
        },
        "parameters": {
            "temperature": 0,
            "max_repair_rounds": args.max_repair_rounds,
            "timeout_seconds": args.timeout_seconds,
            "paper_parallelism": max(1, args.parallel),
            "tool_call_budgets": dict(MAX_TOOL_CALLS),
            "fallback_extractor_models": [],
            "reviewer_enabled": True,
            "reviewer_max_tool_calls": MAX_TOOL_CALLS["review"],
            "review_revision_rounds": REVIEW_REVISION_ROUNDS,
            "review_actionable_severity": REVIEW_ACTIONABLE_SEVERITY,
            "review_rule_profile_id": "hvs_reviewer",
            "review_rule_profile_sha256": rule_profile_sha256(
                WORKSPACE, "hvs_reviewer"
            ),
            "rule_profile_id": "hvs_extractor",
            "rule_profile_sha256": rule_profile_sha256(
                WORKSPACE, "hvs_extractor"
            ),
            **surface_binding(WORKSPACE, args.task_surface),
        },
    }
    desired = build_run_config(
        run_id=run_id,
        method=method,
        expected_papers=papers,
        code=code,
        campaign=campaign,
        campaign_sha256=(sha256_file(args.campaign_manifest) if args.campaign_manifest else None),
        split=args.split or "experimental",
    )
    config = ensure_run_config(run_dir, desired)
    for arxiv_id in papers_with_existing_artifacts(run_dir, papers):
        archived = prepare_paper_retry(run_dir, arxiv_id)
        print(f"archived failed attempt for {arxiv_id} at {archived}")

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
            request_extra=extractor_extra,
            reviewer_request_extra=reviewer_extra,
            task_surface=args.task_surface,
            method_fingerprint=config["method_fingerprint"],
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
