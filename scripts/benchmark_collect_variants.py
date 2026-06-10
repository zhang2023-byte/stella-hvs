#!/usr/bin/env python3
"""Manage benchmark extraction variants: register, snapshot, init, status."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
SRC = WORKSPACE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from high_velocity_lit.catalog_review import read_json, write_json  # noqa: E402
from high_velocity_lit.schema_templates import build_hvs_candidates_template  # noqa: E402
from stella_benchmark.models import (  # noqa: E402
    BENCHMARK_VARIANT_META_SCHEMA_VERSION,
    BenchmarkManifest,
    VariantMeta,
)
from stella_benchmark.paths import (  # noqa: E402
    CANDIDATES_FILENAME,
    benchmark_root,
    manifest_path,
    variant_candidates_path,
    variant_dir,
    variant_meta_path,
    variants_dir,
)

EXTRACTION_SCHEMA_DOC = WORKSPACE / "skills" / "hvs-candidates-extraction" / "references" / "schema.md"


def _load_validator():
    script = WORKSPACE / "scripts" / "validate_hvs_candidates.py"
    spec = importlib.util.spec_from_file_location("validate_hvs_candidates", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def skill_digest() -> str:
    if not EXTRACTION_SCHEMA_DOC.exists():
        return ""
    digest = hashlib.sha256(EXTRACTION_SCHEMA_DOC.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def load_manifest(root: Path) -> BenchmarkManifest:
    path = manifest_path(root)
    if not path.exists():
        raise SystemExit(f"benchmark manifest does not exist: {path}")
    return BenchmarkManifest.model_validate(read_json(path))


def load_variant_meta(root: Path, variant_id: str) -> VariantMeta:
    path = variant_meta_path(root, variant_id)
    if not path.exists():
        raise SystemExit(f"variant is not registered: {path}")
    return VariantMeta.model_validate(read_json(path))


def registered_variant_ids(root: Path) -> list[str]:
    base = variants_dir(root)
    if not base.exists():
        return []
    return sorted(
        path.parent.name for path in base.glob("*/variant_meta.json") if path.is_file()
    )


def cmd_register(args: argparse.Namespace, root: Path) -> int:
    meta_path = variant_meta_path(root, args.variant_id)
    if meta_path.exists() and not args.force:
        raise SystemExit(f"variant already registered: {meta_path} (use --force to replace)")
    meta = VariantMeta(
        schema_version=BENCHMARK_VARIANT_META_SCHEMA_VERSION,
        variant_id=args.variant_id,
        kind=args.kind,
        model=args.model,
        created_at=datetime.now().isoformat(timespec="seconds"),
        skill_digest=skill_digest(),
        notes=args.notes,
    )
    write_json(meta_path, json.loads(meta.model_dump_json()))
    print(meta_path)
    return 0


def cmd_snapshot_canonical(args: argparse.Namespace, root: Path) -> int:
    manifest = load_manifest(root)
    meta = load_variant_meta(root, args.variant_id)
    if meta.kind != "canonical_snapshot":
        raise SystemExit(
            f"variant {args.variant_id!r} has kind {meta.kind!r}; "
            "snapshot-canonical requires kind canonical_snapshot"
        )
    literature_dir = args.literature_dir.expanduser()
    copied: list[str] = []
    missing: list[str] = []
    for paper in manifest.papers:
        source = literature_dir / paper.arxiv_id / CANDIDATES_FILENAME
        if not source.exists():
            missing.append(paper.arxiv_id)
            continue
        target = variant_candidates_path(root, args.variant_id, paper.arxiv_id)
        if target.exists() and not args.force:
            raise SystemExit(f"refusing to overwrite existing snapshot: {target} (use --force)")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        copied.append(paper.arxiv_id)
    print(f"copied: {len(copied)}")
    for arxiv_id in missing:
        print(f"missing canonical extraction: {arxiv_id}", file=sys.stderr)
    return 1 if missing else 0


def cmd_init(args: argparse.Namespace, root: Path) -> int:
    load_variant_meta(root, args.variant_id)
    literature_dir = args.literature_dir.expanduser()
    paper_dir = literature_dir / args.arxiv_id
    if not paper_dir.exists():
        raise SystemExit(f"paper directory does not exist: {paper_dir}")
    target = variant_candidates_path(root, args.variant_id, args.arxiv_id)
    if target.exists() and not args.overwrite:
        raise SystemExit(f"refusing to overwrite existing file: {target} (use --overwrite)")
    payload = build_hvs_candidates_template(
        literature_dir=literature_dir,
        arxiv_id=args.arxiv_id,
        workspace=WORKSPACE,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target)
    return 0


def cmd_status(args: argparse.Namespace, root: Path) -> int:
    manifest = load_manifest(root)
    variant_ids = args.variants or registered_variant_ids(root)
    if not variant_ids:
        raise SystemExit("no registered variants found")
    validator = _load_validator()
    incomplete = 0
    print(f"papers: {len(manifest.papers)}  variants: {', '.join(variant_ids)}")
    for paper in manifest.papers:
        cells: list[str] = []
        for variant_id in variant_ids:
            path = variant_candidates_path(root, variant_id, paper.arxiv_id)
            if not path.exists():
                cells.append(f"{variant_id}: missing")
                incomplete += 1
                continue
            try:
                payload = read_json(path)
            except (OSError, json.JSONDecodeError) as exc:
                cells.append(f"{variant_id}: unreadable ({type(exc).__name__})")
                incomplete += 1
                continue
            report = validator.validate_hvs_candidates_report(
                payload, workspace=WORKSPACE, require_complete=True
            )
            if report.errors:
                cells.append(f"{variant_id}: invalid ({len(report.errors)} errors)")
                incomplete += 1
            else:
                cells.append(f"{variant_id}: ok")
        print(f"  {paper.arxiv_id}  " + "  ".join(cells))
    print(f"incomplete cells: {incomplete}")
    return 1 if incomplete else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage benchmark extraction variants.")
    parser.add_argument("--benchmark-root", type=Path, default=benchmark_root(WORKSPACE))
    subparsers = parser.add_subparsers(dest="command", required=True)

    register = subparsers.add_parser("register", help="Register a variant (writes variant_meta.json).")
    register.add_argument("--variant-id", required=True)
    register.add_argument("--kind", required=True, choices=["canonical_snapshot", "fresh_rerun"])
    register.add_argument("--model", required=True)
    register.add_argument("--notes", default="")
    register.add_argument("--force", action="store_true")
    register.set_defaults(func=cmd_register)

    snapshot = subparsers.add_parser(
        "snapshot-canonical",
        help="Copy production literature_hvs_candidates.json for every manifest paper.",
    )
    snapshot.add_argument("--variant-id", required=True)
    snapshot.add_argument("--literature-dir", type=Path, default=WORKSPACE / "literature")
    snapshot.add_argument("--force", action="store_true")
    snapshot.set_defaults(func=cmd_snapshot_canonical)

    init = subparsers.add_parser("init", help="Write a v7 skeleton into the variant directory.")
    init.add_argument("--variant-id", required=True)
    init.add_argument("--arxiv-id", required=True)
    init.add_argument("--literature-dir", type=Path, default=WORKSPACE / "literature")
    init.add_argument("--overwrite", action="store_true")
    init.set_defaults(func=cmd_init)

    status = subparsers.add_parser("status", help="Show the manifest x variants completion matrix.")
    status.add_argument(
        "--variants",
        nargs="*",
        help="Variant ids to check (default: all registered variants).",
    )
    status.set_defaults(func=cmd_status)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.benchmark_root.expanduser()
    return args.func(args, root)


if __name__ == "__main__":
    raise SystemExit(main())
