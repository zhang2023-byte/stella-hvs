#!/usr/bin/env python3
"""Build the benchmark stratified sampling manifest.

Reads the archived literature corpus, applies the agreed stratified sampling
design (see stella.benchmark.sampling), runs the PDF/TeX arXiv version
consistency check on every sampled paper, and writes
benchmark/manifest/sampling_manifest.json. Deterministic given --seed: two
runs over the same corpus produce byte-identical output.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stella.benchmark.sampling import (
    DEFAULT_SEED,
    PILOT_PAPERS,
    FramePaper,
    build_manifest,
    measure_tex_complexity,
)
from stella.benchmark.versions import check_paper_versions

WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = WORKSPACE / "benchmark" / "manifest" / "sampling_manifest.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build benchmark/manifest/sampling_manifest.json from the literature corpus."
    )
    parser.add_argument(
        "--literature-dir",
        type=Path,
        default=WORKSPACE / "literature",
        help="Archived literature root. Default: literature/",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Manifest output path. Default: benchmark/manifest/sampling_manifest.json",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"Sampling seed. Default: {DEFAULT_SEED}",
    )
    parser.add_argument(
        "--skip-version-check",
        action="store_true",
        help="Skip the PDF/abs arXiv version consistency check (faster).",
    )
    return parser


def load_frame(literature_dir: Path) -> list[FramePaper]:
    frame: list[FramePaper] = []
    for candidates_path in sorted(
        literature_dir.glob("*/literature_hvs_candidates.json")
    ):
        arxiv_id = candidates_path.parent.name
        if arxiv_id in PILOT_PAPERS:
            continue
        payload = json.loads(candidates_path.read_text(encoding="utf-8"))
        status = payload.get("extraction", {}).get("status", "")
        source_dir = candidates_path.parent / "arxiv_source"
        n_tables, max_rows = measure_tex_complexity(source_dir)
        frame.append(
            FramePaper(
                arxiv_id=arxiv_id,
                status=status,
                n_tables=n_tables,
                max_table_rows=max_rows,
                has_tex_source=source_dir.is_dir(),
            )
        )
    return frame


def annotate_versions(manifest: dict, literature_dir: Path) -> None:
    for entry in manifest["papers"]:
        arxiv_id = entry["arxiv_id"]
        result = check_paper_versions(literature_dir / arxiv_id, arxiv_id)
        entry.update(result)
        if result["version_consistent"] is None:
            manifest["warnings"].append(
                f"{arxiv_id}: arXiv version undecidable "
                f"(pdf={result['pdf_version']}, abs={result['abs_version']})"
            )
        elif result["version_consistent"] is False:
            manifest["warnings"].append(
                f"{arxiv_id}: PDF version v{result['pdf_version']} does not "
                f"match abs page v{result['abs_version']}"
            )


def main() -> int:
    args = build_parser().parse_args()
    literature_dir = args.literature_dir.expanduser()
    frame = load_frame(literature_dir)
    if not frame:
        raise SystemExit(f"no candidate files found under {literature_dir}")

    manifest = build_manifest(frame, seed=args.seed)
    if not args.skip_version_check:
        annotate_versions(manifest, literature_dir)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    roles: dict[str, int] = {}
    overlap = 0
    for entry in manifest["papers"]:
        roles[entry["role"]] = roles.get(entry["role"], 0) + 1
        overlap += 1 if entry["overlap"] else 0
    print(f"Frame: {manifest['frame']['size']} papers "
          f"({manifest['frame']['strata']})")
    for cell, info in manifest["frame"]["cells"].items():
        print(f"  {cell}: {info['sampled']}/{info['population']} "
              f"(weight {info['sampling_weight']:.3f})")
    print(f"Sampled: {len(manifest['papers'])} papers, roles {roles}, "
          f"overlap {overlap}")
    for warning in manifest["warnings"]:
        print(f"WARNING: {warning}")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
