#!/usr/bin/env python3
"""Create the persistent release record required for formal test scoring."""

from __future__ import annotations

import argparse
from pathlib import Path

from stella.benchmark.test_release import build_test_release, write_test_release
from stella.benchmark.paths import campaign_paths

WORKSPACE = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Release one sealed test run for scoring")
    parser.add_argument("--campaign-manifest", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--releases-root", type=Path, default=campaign_paths(WORKSPACE).releases)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    release = build_test_release(
        campaign_path=args.campaign_manifest.expanduser().resolve(),
        run_dir=args.run_dir.expanduser().resolve(),
    )
    path = write_test_release(release=release, releases_root=args.releases_root.expanduser())
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
