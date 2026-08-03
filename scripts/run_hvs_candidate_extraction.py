#!/usr/bin/env python3
"""Run one immutable terminal-only extraction dev or explicit test-smoke run."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stella.hvs_extraction.method_config import (
    CORE_FIELD_REASONING_EFFORTS,
    ROSTER_REASONING_EFFORTS,
    ROSTER_THINKING_TYPES,
    default_hvs_extraction_method_config,
    override_model_routes,
)
from stella.hvs_extraction.run import (
    ProgressReporter,
    create_run_config,
    run_papers,
)
from stella.hvs_extraction.run_policy import (
    load_active_manifest,
    run_preflight,
    select_run_papers,
)
from stella.lit.env import env_value, load_env_files
from stella.lit.llm_batch import chat_completion_raw


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-id",
        default=None,
        help="new run identity; default hvs-dev-<UTC timestamp>",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="run the complete dev10 in manifest order",
    )
    parser.add_argument(
        "--arxiv-id",
        action="append",
        help="targeted dev paper; repeat only for targeted dev",
    )
    parser.add_argument(
        "--allow-test-smoke",
        action="store_true",
        help="allow exactly one explicit test paper and mark it test_smoke",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="validate without creating a run or calling an API",
    )
    parser.add_argument("--paper-workers", type=int, default=2)
    parser.add_argument("--candidate-workers", type=int, default=4)
    parser.add_argument("--roster-provider")
    parser.add_argument("--roster-model")
    parser.add_argument(
        "--roster-thinking",
        choices=sorted(ROSTER_THINKING_TYPES),
        help="freeze the roster route thinking mode",
    )
    parser.add_argument(
        "--roster-reasoning-effort",
        choices=sorted(ROSTER_REASONING_EFFORTS),
        help="freeze GLM roster reasoning effort; requires thinking enabled",
    )
    parser.add_argument("--core-field-provider")
    parser.add_argument("--core-field-model")
    parser.add_argument(
        "--core-field-reasoning-effort",
        choices=sorted(CORE_FIELD_REASONING_EFFORTS),
        help="freeze the core-field route reasoning effort",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_id = args.run_id or "hvs-dev-" + datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    load_env_files(ROOT)
    api_key = env_value("LLM_API_KEY")
    base_url = env_value("LLM_BASE_URL")
    config = override_model_routes(
        default_hvs_extraction_method_config(ROOT),
        roster_provider=args.roster_provider,
        roster_model=args.roster_model,
        roster_thinking=args.roster_thinking,
        roster_reasoning_effort=args.roster_reasoning_effort,
        core_field_provider=args.core_field_provider,
        core_field_model=args.core_field_model,
        core_field_reasoning_effort=args.core_field_reasoning_effort,
    )
    manifest_path, manifest, manifest_sha256 = load_active_manifest(ROOT)
    scope, papers = select_run_papers(
        manifest,
        full_dev=args.dev,
        requested_ids=args.arxiv_id,
        allow_test_smoke=args.allow_test_smoke,
    )
    reporter = ProgressReporter()
    reporter(
        "preflight_start",
        run_id=run_id,
        scope=scope,
        papers=len(papers),
    )
    preflight = run_preflight(
        ROOT,
        run_id,
        papers,
        config=config,
        api_key=api_key,
        base_url=base_url,
    )
    for warning in preflight["worktree"]["warnings"]:
        reporter("preflight_warning", warning=warning)
    reporter(
        "preflight_ok",
        run_id=run_id,
        papers=len(papers),
        api_calls=0,
        run_created=False,
    )
    if args.preflight_only:
        print(json.dumps(preflight, ensure_ascii=False, indent=2), flush=True)
        return 0

    create_run_config(
        ROOT,
        run_id,
        papers,
        config=config,
        scope=scope,
        manifest_path=manifest_path.relative_to(ROOT).as_posix(),
        manifest_sha256=manifest_sha256,
        code=preflight["worktree"],
        paper_workers=args.paper_workers,
        candidate_workers=args.candidate_workers,
    )
    try:
        summary = run_papers(
            ROOT,
            run_id,
            config=config,
            transport=chat_completion_raw,
            api_key=api_key,
            base_url=base_url,
            progress=reporter,
        )
    except KeyboardInterrupt:
        print(
            "interrupted; immutable partial artifacts and run_summary.json were preserved",
            file=sys.stderr,
            flush=True,
        )
        return 130
    print(json.dumps(summary["totals"], ensure_ascii=False, indent=2), flush=True)
    print(
        f"run summary: benchmark/campaigns/hvs-extraction-v6/runs/{run_id}/run_summary.json",
        flush=True,
    )
    return 0


def cli() -> int:
    try:
        return main()
    except (FileExistsError, ValueError) as exc:
        print(f"extraction run refused: {exc}", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(cli())
