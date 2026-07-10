#!/usr/bin/env python3
"""Seal an open benchmark run into an immutable run manifest."""

from __future__ import annotations

import argparse
from pathlib import Path

from stella.benchmark.extraction_run import load_frozen_validator
from stella.benchmark.run_contract import seal_run

WORKSPACE = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seal an open benchmark run")
    parser.add_argument("run_dir", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    manifest = seal_run(
        args.run_dir.expanduser().resolve(),
        workspace=WORKSPACE,
        validator_module=load_frozen_validator(WORKSPACE),
    )
    print(
        f"Sealed {manifest['run_id']}: "
        f"valid={len(manifest['papers']['valid'])}, "
        f"invalid={len(manifest['papers']['invalid'])}, "
        f"missing={len(manifest['papers']['missing'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
