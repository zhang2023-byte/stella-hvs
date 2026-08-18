#!/usr/bin/env python3
"""Manually recover network-terminal nodes inside one network debug run."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stella.hvs_extraction.network_debug import (
    debug_run_dir,
    derive_debug_state,
    finalize_network_debug_run,
    init_network_debug_run,
    retry_network_nodes,
)
from stella.lit.env import env_value, load_env_files
from stella.lit.llm_batch import chat_completion_raw


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--debug-run-id",
        required=True,
        help="debug container identity under benchmark debug root",
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="create the container from a terminal formal run (no API calls)",
    )
    parser.add_argument(
        "--source-run",
        help="source formal run id; required with --init",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="print the current node transport states (no API calls)",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="manually retry every currently network-terminal node "
        "(real provider calls)",
    )
    parser.add_argument(
        "--retry-node",
        action="append",
        default=None,
        metavar="ARXIV:NODE",
        help="retry one node: <arxiv_id>:roster | <arxiv_id>:candidate-NNN "
        "| <arxiv_id>:peer-review (real provider calls)",
    )
    parser.add_argument(
        "--paper",
        action="append",
        default=None,
        help="with --retry-failed, restrict the batch to one paper",
    )
    parser.add_argument(
        "--finalize",
        action="store_true",
        help="certify the transport-clean container (no API calls)",
    )
    parser.add_argument(
        "--pricing-snapshot-id",
        default=None,
        help="must match the source run snapshot when provided",
    )
    parser.add_argument("--candidate-workers", type=int, default=4)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    actions = [
        bool(args.init),
        bool(args.status),
        bool(args.retry_failed),
        bool(args.retry_node),
        bool(args.finalize),
    ]
    if sum(actions) != 1:
        print("choose exactly one action: --init, --status, --retry-failed, --retry-node, --finalize", file=sys.stderr)
        return 2
    load_env_files(ROOT)
    api_key = env_value("LLM_API_KEY")
    base_url = env_value("LLM_BASE_URL")

    if args.init:
        if not args.source_run:
            print("--init requires --source-run", file=sys.stderr)
            return 2
        state = init_network_debug_run(
            ROOT,
            source_run_id=args.source_run,
            debug_run_id=args.debug_run_id,
            pricing_snapshot_id=args.pricing_snapshot_id,
        )
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0

    if args.status:
        state = derive_debug_state(ROOT, args.debug_run_id)
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0

    if args.finalize:
        result = finalize_network_debug_run(ROOT, args.debug_run_id)
        printable = dict(result)
        printable["debug_dir"] = str(debug_run_dir(ROOT, args.debug_run_id))
        print(json.dumps(printable, ensure_ascii=False, indent=2))
        return 0

    # Retry actions need real provider credentials and explicit authority.
    if not api_key or not base_url:
        print("network debug retries require LLM_API_KEY and LLM_BASE_URL", file=sys.stderr)
        return 2
    summary = retry_network_nodes(
        ROOT,
        args.debug_run_id,
        transport=chat_completion_raw,
        api_key=api_key,
        base_url=base_url,
        papers=args.paper,
        nodes=args.retry_node,
        candidate_workers=args.candidate_workers,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def cli() -> int:
    try:
        return main()
    except (FileExistsError, ValueError) as exc:
        print(f"network debug run refused: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(
            "network debug retry interrupted; the container stays recoverable",
            file=sys.stderr,
        )
        return 130


if __name__ == "__main__":
    raise SystemExit(cli())
