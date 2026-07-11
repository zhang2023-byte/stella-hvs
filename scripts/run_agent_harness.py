#!/usr/bin/env python3
"""Prepare, launch, and collect one tool-neutral method-A agent bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stella.benchmark.agent_harness import (
    collect_bundle,
    launch_adapter,
    load_bundle,
    prepare_bundle,
)
from stella.benchmark.extraction_run import load_frozen_validator
from stella.lit.arxiv_ids import validate_unversioned_arxiv_id

WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE_ROOT = Path("/tmp/stella-benchmark-agent-bundles")


def _load_config(run_dir: Path) -> dict:
    return json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Method-A isolated agent harness")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--run-dir", type=Path, required=True)
    prepare.add_argument("--arxiv-id", required=True, type=validate_unversioned_arxiv_id)
    prepare.add_argument("--bundle-root", type=Path, default=DEFAULT_BUNDLE_ROOT)
    launch = sub.add_parser("launch")
    launch.add_argument("--bundle", type=Path, required=True)
    launch.add_argument("argv", nargs=argparse.REMAINDER)
    collect = sub.add_parser("collect")
    collect.add_argument("--run-dir", type=Path, required=True)
    collect.add_argument("--bundle", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "prepare":
        run_dir = args.run_dir.expanduser().resolve()
        bundle = prepare_bundle(
            workspace=WORKSPACE,
            run_dir=run_dir,
            bundle_root=args.bundle_root.expanduser(),
            arxiv_id=args.arxiv_id,
            run_config=_load_config(run_dir),
        )
        print(bundle.root)
        return 0
    bundle = load_bundle(args.bundle)
    if args.command == "launch":
        argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
        result = launch_adapter(bundle=bundle, argv=argv)
        return result.returncode
    run_dir = args.run_dir.expanduser().resolve()
    result = collect_bundle(
        workspace=WORKSPACE,
        run_dir=run_dir,
        bundle=bundle,
        run_config=_load_config(run_dir),
        validator_module=load_frozen_validator(WORKSPACE),
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
