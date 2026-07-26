#!/usr/bin/env python3
"""Prepare, launch, collect, or finalize a coding-agent comparison run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stella.benchmark.coding_agent_baseline import (
    collect_bundle,
    finalize_baseline_run,
    launch_adapter,
    load_bundle,
    prepare_bundle,
)
from stella.benchmark.validator_loader import load_hvs_validator
from stella.lit.arxiv_ids import validate_unversioned_arxiv_id


WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE_ROOT = Path("/tmp/stella-coding-agent-baseline")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--run-dir", type=Path, required=True)
    prepare.add_argument(
        "--arxiv-id", required=True, type=validate_unversioned_arxiv_id
    )
    prepare.add_argument(
        "--bundle-root", type=Path, default=DEFAULT_BUNDLE_ROOT
    )
    launch = sub.add_parser("launch")
    launch.add_argument("--bundle", type=Path, required=True)
    launch.add_argument("argv", nargs=argparse.REMAINDER)
    collect = sub.add_parser("collect")
    collect.add_argument("--run-dir", type=Path, required=True)
    collect.add_argument("--bundle", type=Path, required=True)
    finalize = sub.add_parser("finalize")
    finalize.add_argument("--run-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "prepare":
        bundle = prepare_bundle(
            workspace=WORKSPACE,
            run_dir=args.run_dir.expanduser().resolve(),
            bundle_root=args.bundle_root.expanduser().resolve(),
            arxiv_id=args.arxiv_id,
        )
        print(bundle.root)
        return 0
    if args.command == "finalize":
        summary, manifest = finalize_baseline_run(
            args.run_dir.expanduser().resolve()
        )
        print(
            json.dumps(
                {
                    "summary": summary["totals"],
                    "status": manifest["status"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    bundle = load_bundle(args.bundle)
    if args.command == "launch":
        argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
        return launch_adapter(bundle=bundle, argv=argv).returncode
    report = collect_bundle(
        workspace=WORKSPACE,
        run_dir=args.run_dir.expanduser().resolve(),
        bundle=bundle,
        validator_module=load_hvs_validator(WORKSPACE),
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] in {"complete", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
