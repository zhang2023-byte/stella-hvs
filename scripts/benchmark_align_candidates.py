#!/usr/bin/env python3
"""Align benchmark extraction variants per paper and embed evidence excerpts."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
SRC = WORKSPACE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from high_velocity_lit.catalog_review import read_json, write_json  # noqa: E402
from stella_benchmark.alignment import build_alignment_record  # noqa: E402
from stella_benchmark.evidence import EvidenceResolver  # noqa: E402
from stella_benchmark.models import BenchmarkManifest  # noqa: E402
from stella_benchmark.paths import (  # noqa: E402
    adjudication_path,
    alignment_index_path,
    alignment_path,
    benchmark_root,
    manifest_path,
    variant_candidates_path,
    variants_dir,
)


def registered_variant_ids(root: Path) -> list[str]:
    base = variants_dir(root)
    if not base.exists():
        return []
    return sorted(path.parent.name for path in base.glob("*/variant_meta.json") if path.is_file())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write benchmark/alignment/<arxiv_id>.alignment.json for manifest papers."
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--all", action="store_true", help="Align every manifest paper.")
    selection.add_argument("--arxiv-id", help="Align one paper.")
    parser.add_argument(
        "--variants",
        nargs="*",
        help="Variant ids to align (default: all registered variants).",
    )
    parser.add_argument("--benchmark-root", type=Path, default=benchmark_root(WORKSPACE))
    parser.add_argument("--spot-check-fraction", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=20260610)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.benchmark_root.expanduser()
    manifest_file = manifest_path(root)
    if not manifest_file.exists():
        raise SystemExit(f"benchmark manifest does not exist: {manifest_file}")
    manifest = BenchmarkManifest.model_validate(read_json(manifest_file))

    variant_ids = args.variants or registered_variant_ids(root)
    if not variant_ids:
        raise SystemExit("no registered variants found")

    if args.all:
        arxiv_ids = [paper.arxiv_id for paper in manifest.papers]
    else:
        if args.arxiv_id not in {paper.arxiv_id for paper in manifest.papers}:
            raise SystemExit(f"paper is not in the benchmark manifest: {args.arxiv_id}")
        arxiv_ids = [args.arxiv_id]

    resolver = EvidenceResolver(WORKSPACE)
    index_items: list[dict[str, object]] = []
    skipped: list[str] = []
    stale: list[str] = []
    for arxiv_id in arxiv_ids:
        variant_payloads: dict[str, dict[str, object]] = {}
        for variant_id in variant_ids:
            path = variant_candidates_path(root, variant_id, arxiv_id)
            if path.exists():
                variant_payloads[variant_id] = read_json(path)
        if not variant_payloads:
            skipped.append(arxiv_id)
            print(f"skipping {arxiv_id}: no variant extraction found", file=sys.stderr)
            continue

        record = build_alignment_record(
            arxiv_id,
            variant_payloads,
            resolver,
            spot_check_fraction=args.spot_check_fraction,
            seed=args.seed,
        )
        write_json(alignment_path(root, arxiv_id), json.loads(record.model_dump_json()))

        adjudication_file = adjudication_path(root, arxiv_id)
        if adjudication_file.exists():
            existing = read_json(adjudication_file)
            if str(existing.get("alignment_digest") or "") != record.alignment_digest:
                stale.append(arxiv_id)
                print(
                    f"warning: adjudication for {arxiv_id} was made against a different "
                    "alignment digest; its verdicts are stale",
                    file=sys.stderr,
                )

        disagreement_count = sum(
            1 for cluster in record.clusters for field in cluster.fields if not field.agreement
        )
        index_items.append(
            {
                "arxiv_id": arxiv_id,
                "alignment_digest": record.alignment_digest,
                "variant_ids": sorted(variant_payloads),
                "cluster_count": len(record.clusters),
                "disagreement_field_count": disagreement_count,
                "status_agreement": record.paper_status.agreement,
                "spot_check_count": len(record.consensus_spot_checks),
                "uncovered_row_count": len(record.recall_assists.uncovered_ecsv_rows),
            }
        )
        print(
            f"{arxiv_id}: clusters={len(record.clusters)} "
            f"disagreements={disagreement_count} spot_checks={len(record.consensus_spot_checks)}"
        )

    write_json(
        alignment_index_path(root),
        {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "papers": index_items,
            "skipped": skipped,
            "stale_adjudications": stale,
        },
    )
    return 1 if skipped else 0


if __name__ == "__main__":
    raise SystemExit(main())
