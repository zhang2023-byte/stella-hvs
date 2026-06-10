#!/usr/bin/env python3
"""Apply expert verdicts to assemble and validate gold candidate records."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
SRC = WORKSPACE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from high_velocity_lit.catalog_review import read_json, relative_path, write_json  # noqa: E402
from stella_benchmark.adjudication import load_adjudication, missing_items  # noqa: E402
from stella_benchmark.gold import GoldAssemblyError, assemble_gold  # noqa: E402
from stella_benchmark.models import AlignmentRecord, BenchmarkManifest  # noqa: E402
from stella_benchmark.paths import (  # noqa: E402
    adjudication_path,
    alignment_path,
    benchmark_root,
    gold_candidates_path,
    gold_provenance_path,
    manifest_path,
    variant_candidates_path,
    variants_dir,
)


def _load_validator():
    script = WORKSPACE / "scripts" / "validate_hvs_candidates.py"
    spec = importlib.util.spec_from_file_location("validate_hvs_candidates", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def registered_variant_ids(root: Path) -> list[str]:
    base = variants_dir(root)
    if not base.exists():
        return []
    return sorted(path.parent.name for path in base.glob("*/variant_meta.json") if path.is_file())


def finalize_paper(arxiv_id: str, root: Path, validator) -> list[str]:
    """Assemble, validate, and write gold for one paper; returns blocking problems."""
    align_file = alignment_path(root, arxiv_id)
    if not align_file.exists():
        return [f"alignment does not exist: {align_file}"]
    alignment = AlignmentRecord.model_validate(read_json(align_file))

    adjudication_file = adjudication_path(root, arxiv_id)
    adjudication = load_adjudication(adjudication_file)
    if adjudication is None:
        return [f"adjudication does not exist: {adjudication_file}"]

    open_items = missing_items(alignment, adjudication)
    if open_items:
        preview = ", ".join(open_items[:5])
        suffix = "" if len(open_items) <= 5 else f" (+{len(open_items) - 5} more)"
        return [f"{len(open_items)} required verdicts are missing: {preview}{suffix}"]

    variant_payloads = {}
    for variant in alignment.variants:
        path = variant_candidates_path(root, variant.variant_id, arxiv_id)
        if path.exists():
            variant_payloads[variant.variant_id] = read_json(path)
    try:
        gold_payload, provenance = assemble_gold(
            alignment,
            adjudication,
            variant_payloads,
            adjudication_path=relative_path(adjudication_file, workspace=WORKSPACE),
        )
    except GoldAssemblyError as exc:
        return [f"gold assembly failed: {exc}"]

    report = validator.validate_hvs_candidates_report(
        gold_payload, workspace=WORKSPACE, require_complete=True
    )
    if report.errors:
        preview = "; ".join(report.errors[:5])
        suffix = "" if len(report.errors) <= 5 else f" (+{len(report.errors) - 5} more)"
        return [
            f"gold record fails v7 validation with {len(report.errors)} errors: {preview}{suffix}",
            "fix the corresponding fixed_payload/added_payload in the adjudication and re-run",
        ]

    write_json(gold_candidates_path(root, arxiv_id), gold_payload)
    write_json(gold_provenance_path(root, arxiv_id), json.loads(provenance.model_dump_json()))
    for warning in report.warnings:
        print(f"warning: {arxiv_id}: {warning}", file=sys.stderr)
    return []


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Assemble benchmark/gold/<arxiv_id>/ from expert adjudications."
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--all", action="store_true", help="Finalize every manifest paper.")
    selection.add_argument("--arxiv-id", help="Finalize one paper.")
    parser.add_argument("--benchmark-root", type=Path, default=benchmark_root(WORKSPACE))
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Continue past papers that are blocked instead of failing the run.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.benchmark_root.expanduser()
    manifest_file = manifest_path(root)
    if not manifest_file.exists():
        raise SystemExit(f"benchmark manifest does not exist: {manifest_file}")
    manifest = BenchmarkManifest.model_validate(read_json(manifest_file))

    if args.all:
        arxiv_ids = [paper.arxiv_id for paper in manifest.papers]
    else:
        if args.arxiv_id not in {paper.arxiv_id for paper in manifest.papers}:
            raise SystemExit(f"paper is not in the benchmark manifest: {args.arxiv_id}")
        arxiv_ids = [args.arxiv_id]

    validator = _load_validator()
    blocked = 0
    for arxiv_id in arxiv_ids:
        problems = finalize_paper(arxiv_id, root, validator)
        if problems:
            blocked += 1
            for problem in problems:
                print(f"{arxiv_id}: {problem}", file=sys.stderr)
            if not args.allow_partial:
                return 1
        else:
            print(f"{arxiv_id}: gold written to {gold_candidates_path(root, arxiv_id)}")
    if blocked:
        print(f"blocked papers: {blocked}/{len(arxiv_ids)}", file=sys.stderr)
    return 1 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
