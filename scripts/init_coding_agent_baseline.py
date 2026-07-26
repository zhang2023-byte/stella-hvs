#!/usr/bin/env python3
"""Create or preflight one immutable coding-agent comparison run."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from stella.benchmark.coding_agent_baseline import (
    create_baseline_run_config,
)
from stella.hvs_extraction.method_config import (
    default_hvs_extraction_method_config,
)
from stella.hvs_extraction.prepare import STATUS_PREPARED, build_prepared_input
from stella.hvs_extraction.run_policy import (
    ensure_run_available,
    inspect_hvs_extraction_worktree,
    load_active_manifest,
    select_run_papers,
)


WORKSPACE = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id")
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--runtime-version", required=True)
    parser.add_argument("--model", required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--dev", action="store_true")
    selection.add_argument("--arxiv-id", action="append")
    parser.add_argument("--allow-test-smoke", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_id = args.run_id or "coding-baseline-" + datetime.now(
        timezone.utc
    ).strftime("%Y%m%dT%H%M%SZ")
    manifest_path, manifest, manifest_sha256 = load_active_manifest(WORKSPACE)
    scope, papers = select_run_papers(
        manifest,
        full_dev=args.dev,
        requested_ids=args.arxiv_id,
        allow_test_smoke=args.allow_test_smoke,
    )
    ensure_run_available(WORKSPACE, run_id)
    worktree = inspect_hvs_extraction_worktree(WORKSPACE)
    if not worktree["clean_for_dev"]:
        raise ValueError("baseline preflight requires a clean executable worktree")
    method = default_hvs_extraction_method_config(WORKSPACE)
    prepared: dict[str, str] = {}
    for arxiv_id in papers:
        artifact = build_prepared_input(
            WORKSPACE,
            arxiv_id,
            roster_budget=method.roster_context_budget,
            field_budget=method.field_context_budget,
        )
        prepared[arxiv_id] = artifact["status"]
        if artifact["status"] != STATUS_PREPARED:
            detail = (artifact.get("failure") or {}).get("detail") or "unknown"
            raise ValueError(f"{arxiv_id} input preflight failed: {detail}")
    result = {
        "run_id": run_id,
        "scope": scope,
        "papers": papers,
        "prepared": prepared,
        "run_created": False,
        "api_calls": 0,
        "warnings": worktree["warnings"],
    }
    if args.preflight_only:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    config = create_baseline_run_config(
        WORKSPACE,
        run_id=run_id,
        papers=papers,
        scope=scope,
        campaign_binding={
            "campaign_id": manifest["campaign_id"],
            "manifest_path": manifest_path.relative_to(WORKSPACE).as_posix(),
            "manifest_sha256": manifest_sha256,
        },
        runtime_name=args.runtime,
        runtime_release=args.runtime_version,
        model_id=args.model,
        code=worktree,
    )
    print(json.dumps(config, ensure_ascii=False, indent=2))
    return 0


def cli() -> int:
    try:
        return main()
    except (FileExistsError, ValueError) as exc:
        print(f"coding-agent baseline refused: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(cli())
