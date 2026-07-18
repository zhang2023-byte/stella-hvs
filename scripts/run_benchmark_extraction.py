#!/usr/bin/env python3
"""Run reviewer-backed direct-API benchmark extractions and archive them.

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
from stella.benchmark.components import build_run_component_hashes
from stella.benchmark.campaign import papers_for_split, sha256_file
from stella.benchmark.extraction_run import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_REPAIR_ROUNDS,
    PILOT_PAPERS,
    PIPELINE_NAME,
    build_system_prompt,
    git_short_hash,
    load_frozen_validator,
    run_paper,
    write_harness_error_report,
)
from stella.benchmark.extraction_review import (
    DEFAULT_REVIEWER_MODEL,
    DEFAULT_REVIEWER_PROVIDER_ORDER,
    REVIEW_ACTIONABLE_SEVERITY,
    REVIEW_REVISION_ROUNDS,
    WORKFLOW_REVIEW_RETRIES,
    build_workflow_reviewer_system_prompt,
)
from stella.schema_registry import STELLA_RELEASE
from stella.lit.env import env_value, load_env_files
from stella.lit.arxiv_ids import validate_unversioned_arxiv_id
from stella.lit.schema_templates import build_hvs_candidates_template
from stella.lit.schema_docs import assert_generated_schema_docs_current
from stella.lit.extraction_rules import (
    assert_generated_rule_views_current,
    rule_profile_sha256,
)
from stella.benchmark.run_contract import (
    build_run_config,
    ensure_run_config,
    git_state,
    prepare_run_resume,
    prepare_external_failure_retry,
)
from stella.benchmark.run_trace import RunTrace
from stella.benchmark.paths import campaign_paths
from stella.benchmark.task_surfaces import (
    TASK_SURFACE_IDS,
    surface_binding,
)
from stella.benchmark.method_policy import PRIMARY_TASK_SURFACE, require_legacy_opt_in

WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_RUNS_DIR = campaign_paths(WORKSPACE).runs

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
    # TokenDance displays the first-party GLM route as BigModel; its gateway
    # provider tag is `bigmodel`. Keep the quality-first default reviewer on that
    # exact route so the provider becomes part of run provenance/fingerprint.
    DEFAULT_REVIEWER_MODEL: list(DEFAULT_REVIEWER_PROVIDER_ORDER),
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
        "--retry-external-paper",
        action="append",
        default=None,
        type=validate_unversioned_arxiv_id,
        help=(
            "Retry one existing formal-run paper whose report status is exactly "
            "transport_error (repeatable). Requires --run-id."
        ),
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model id. Default: LLM_MODEL from the environment.",
    )
    parser.add_argument(
        "--reviewer-model",
        default=DEFAULT_REVIEWER_MODEL,
        help=f"Independent reviewer model id. Default: {DEFAULT_REVIEWER_MODEL}.",
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
        help="Runs root. Default: the active campaign runs directory.",
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
        "--task-surface",
        choices=TASK_SURFACE_IDS,
        default=PRIMARY_TASK_SURFACE,
        help=(
            "Generation task surface. Default: core_prov. FULL is a retained "
            "legacy diagnostic and requires --allow-legacy-full."
        ),
    )
    parser.add_argument(
        "--allow-legacy-full",
        action="store_true",
        help="Explicitly opt into the legacy FULL diagnostic surface.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Pack contexts and report prompt sizes without calling the API.",
    )
    parser.add_argument(
        "--trace-root",
        type=Path,
        default=None,
        help="Optional local dev-console trace root; does not affect the method fingerprint.",
    )
    parser.add_argument(
        "--trace-campaign-id",
        default=None,
        help="Optional trace namespace override for experimental dev-console runs.",
    )
    parser.add_argument(
        "--roster-cache-root",
        type=Path,
        default=None,
        help="Shared surface-neutral roster cache (default: <runs-dir>/_shared_rosters).",
    )
    parser.add_argument(
        "--stream-responses",
        action="store_true",
        help="Request OpenAI-compatible streaming responses for live dev traces. Default: false.",
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


def provider_extra(model: str) -> dict:
    order = DEFAULT_PROVIDER_ORDER.get(model)
    return {"provider": {"order": list(order)}} if order else {}


def main() -> int:
    args = build_parser().parse_args()
    try:
        require_legacy_opt_in(
            method="B",
            task_surface=args.task_surface,
            allow_legacy_full=args.allow_legacy_full,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    assert_generated_rule_views_current(WORKSPACE)
    assert_generated_schema_docs_current(WORKSPACE)
    if args.campaign:
        paths = campaign_paths(WORKSPACE, args.campaign)
        args.campaign_manifest = paths.campaign_manifest
        if args.runs_dir == DEFAULT_RUNS_DIR:
            args.runs_dir = paths.runs
    load_env_files(WORKSPACE)
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
    retry_external_papers = list(dict.fromkeys(args.retry_external_paper or []))
    if retry_external_papers and campaign is None:
        raise SystemExit("--retry-external-paper requires --campaign/--campaign-manifest")
    if retry_external_papers and not args.run_id:
        raise SystemExit("--retry-external-paper requires an explicit --run-id")
    model = args.model or env_value("LLM_MODEL")
    if not model:
        raise SystemExit("set LLM_MODEL in .env or pass --model")

    if args.dry_run:
        system_chars = len(build_system_prompt(WORKSPACE, args.task_surface))
        reviewer_chars = len(
            build_workflow_reviewer_system_prompt(
                WORKSPACE, args.task_surface
            )
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
    reviewer_extra = provider_extra(args.reviewer_model)
    run_id = args.run_id or f"{_dt.datetime.now():%Y%m%d-%H%M}-{model}"
    run_dir = args.runs_dir.expanduser() / run_id
    if campaign is not None and model == args.reviewer_model:
        raise SystemExit(
            "formal method B requires distinct extractor and reviewer model ids"
        )
    code = git_state(WORKSPACE)
    method = {
        "producer": PIPELINE_NAME,
        "models": {"extractor": model, "reviewer": args.reviewer_model},
        "providers": {
            "extractor": request_extra.get("provider", {}).get("order", []),
            "reviewer": reviewer_extra.get("provider", {}).get("order", []),
        },
        "provenance": {
            "stella_release": STELLA_RELEASE,
            "code_commit": code["commit"],
            "components": {},
        },
        "parameters": {
            "temperature": 0,
            "max_tokens": args.max_tokens,
            "max_repair_rounds": args.max_repair_rounds,
            "batch_size": args.batch_size,
            "timeout_seconds": args.timeout_seconds,
            "paper_parallelism": max(1, args.parallel),
            "fallback_extractor_models": request_extra.get("models", []),
            "reviewer_enabled": True,
            "roster_strategy": "surface_neutral_shared_v1",
            "roster_rule_profile_id": "hvs_roster",
            "roster_rule_profile_sha256": rule_profile_sha256(
                WORKSPACE, "hvs_roster"
            ),
            "reviewer_orchestration": "workflow_whole_response",
            "reviewer_structured_retries": WORKFLOW_REVIEW_RETRIES,
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
    method["provenance"]["components"] = build_run_component_hashes(WORKSPACE, method)
    if args.stream_responses:
        method["parameters"]["stream_responses"] = True
    desired = build_run_config(
        run_id=run_id,
        method=method,
        expected_papers=papers,
        code=code,
        campaign=campaign,
        campaign_sha256=(sha256_file(args.campaign_manifest) if args.campaign_manifest else None),
        split=args.split or "experimental",
    )
    existing_config = (run_dir / "run_config.json").exists()
    config = ensure_run_config(run_dir, desired)
    resume = (
        prepare_external_failure_retry(run_dir, papers, retry_external_papers)
        if retry_external_papers
        else prepare_run_resume(run_dir, papers)
    )
    trace = (
        RunTrace(
            args.trace_root,
            campaign_id=str(
                args.trace_campaign_id
                or (config.get("campaign") or {}).get("campaign_id")
                or "experimental"
            ),
            run_id=run_id,
            method="B",
        )
        if args.trace_root is not None
        else None
    )
    if trace is not None:
        trace.emit(
            "run.resumed" if existing_config else "run.started",
            stage="launch",
            status="running",
            data={
                "pending": resume["pending"],
                "skipped_success": resume["skipped_success"],
                "archived": resume["archived"],
            },
            payload_kind="run.config",
            payload=config,
        )
        for arxiv_id in resume["skipped_success"]:
            trace.emit(
                "paper.skipped",
                paper_id=arxiv_id,
                stage="resume",
                status="already_successful",
            )
    for arxiv_id, archived in resume["archived"].items():
        print(f"archived failed attempt for {arxiv_id} at {archived}")
    pending_papers = list(resume["pending"])
    if request_extra or reviewer_extra:
        print(
            "gateway routing: "
            + json.dumps(
                {"extractor": request_extra, "reviewer": reviewer_extra},
                ensure_ascii=False,
            )
        )

    def run_one(arxiv_id: str):
        # Each worker loads its own validator module instance so no state
        # is shared between concurrently running papers.
        try:
            return run_paper(
                workspace=WORKSPACE,
                arxiv_id=arxiv_id,
                run_dir=run_dir,
                api_key=api_key,
                base_url=base_url,
                model=model,
                reviewer_model=args.reviewer_model,
                prompt_version=prompt_version,
                batch_size=args.batch_size,
                max_repair_rounds=args.max_repair_rounds,
                max_tokens=args.max_tokens,
                timeout_seconds=args.timeout_seconds,
                request_extra=request_extra,
                reviewer_request_extra=reviewer_extra,
                task_surface=args.task_surface,
                method_fingerprint=config["method_fingerprint"],
                validator_module=load_frozen_validator(WORKSPACE),
                trace=trace,
                stream_responses=args.stream_responses,
                roster_cache_root=(
                    args.roster_cache_root
                    if args.roster_cache_root is not None
                    else args.runs_dir / "_shared_rosters"
                ),
            )
        except Exception as exc:  # preserve the paper failure and continue the Run
            return write_harness_error_report(
                run_dir=run_dir,
                arxiv_id=arxiv_id,
                error=exc,
                trace=trace,
            )

    def report(result) -> None:
        print(
            f"{result.arxiv_id}: {result.status} "
            f"(scaffold={result.scaffold_attempts}, batches={result.batch_count}, "
            f"batch_calls={result.batch_calls}, repairs={result.repair_rounds}, "
            f"review={result.review_calls}, challenges={result.review_challenges}, "
            f"errors={result.validator_errors}, usage={result.usage_totals})",
            flush=True,
        )
        if result.error:
            print(f"  transport error: {result.error}", flush=True)

    failures = 0
    workers = max(1, args.parallel)
    if workers == 1:
        for arxiv_id in pending_papers:
            print(
                f"=== {arxiv_id} ({model} + reviewer {args.reviewer_model}) ===",
                flush=True,
            )
            result = run_one(arxiv_id)
            report(result)
            if result.status not in ("ok", "ok_with_cjk_warnings"):
                failures += 1
    else:
        print(
            f"running {len(pending_papers)} papers, {workers} at a time "
            f"({model} + reviewer {args.reviewer_model})",
            flush=True,
        )
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(run_one, pid): pid for pid in pending_papers}
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                report(result)
                if result.status not in ("ok", "ok_with_cjk_warnings"):
                    failures += 1
    print(f"\nRun archived at {run_dir}")
    if trace is not None:
        trace.emit(
            "run.completed",
            stage="final",
            status="failed" if failures else "completed",
            data={"failures": failures, "pending_count": len(pending_papers)},
        )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
