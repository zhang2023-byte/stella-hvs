#!/usr/bin/env python3
"""Select a stratified benchmark paper sample and write the benchmark manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
SRC = WORKSPACE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from high_velocity_lit.catalog_review import read_json, relative_path, write_json  # noqa: E402
from high_velocity_lit.hvs_candidates_index import rebuild_hvs_candidates_index  # noqa: E402
from stella_benchmark.paths import benchmark_root, manifest_path  # noqa: E402
from stella_benchmark.sampling import build_manifest, manifest_is_frozen  # noqa: E402

DEFAULT_SEED = 20260610


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write benchmark/manifest/benchmark_manifest.json from a stratified sample."
    )
    parser.add_argument("--size", type=int, required=True, help="Number of papers to sample.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--literature-dir", type=Path, default=WORKSPACE / "literature")
    parser.add_argument("--output", type=Path, default=manifest_path(benchmark_root(WORKSPACE)))
    parser.add_argument(
        "--no-freeze",
        action="store_true",
        help="Write the manifest with frozen=false (default manifests are frozen).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing frozen manifest.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    literature_dir = args.literature_dir.expanduser()
    if not literature_dir.exists():
        raise SystemExit(f"literature directory does not exist: {literature_dir}")
    if args.size <= 0:
        raise SystemExit("--size must be a positive integer")

    output_path = args.output.expanduser()
    if output_path.exists():
        existing = read_json(output_path)
        if manifest_is_frozen(existing) and not args.force:
            raise SystemExit(
                f"refusing to overwrite frozen manifest: {output_path} (use --force to replace)"
            )

    index_record = rebuild_hvs_candidates_index(literature_dir, workspace=WORKSPACE)
    manifest = build_manifest(
        index_record,
        size=args.size,
        seed=args.seed,
        source_index_path=relative_path(literature_dir, workspace=WORKSPACE),
        frozen=not args.no_freeze,
    )
    if not manifest.papers:
        raise SystemExit("no eligible papers found; nothing to sample")
    if len(manifest.papers) < args.size:
        print(
            f"warning: only {len(manifest.papers)} eligible papers available "
            f"(requested {args.size})",
            file=sys.stderr,
        )

    write_json(output_path, json.loads(manifest.model_dump_json()))

    by_stratum: dict[str, int] = {}
    for paper in manifest.papers:
        by_stratum[paper.stratum] = by_stratum.get(paper.stratum, 0) + 1
    print(f"manifest: {output_path}")
    print(f"papers: {len(manifest.papers)} (seed={args.seed}, frozen={manifest.frozen})")
    for stratum in sorted(by_stratum):
        print(f"  {stratum}: {by_stratum[stratum]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
