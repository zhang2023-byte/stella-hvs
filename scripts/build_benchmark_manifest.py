#!/usr/bin/env python3
"""Build the benchmark stratified sampling manifest.

Reads the archived literature corpus, applies the agreed stratified sampling
design (see stella.benchmark.sampling), runs the PDF/TeX arXiv version
consistency check on every sampled paper, and writes
benchmark/campaigns/hvs-extraction-v2/manifest/sampling_manifest.json. Deterministic given --seed: two
runs over the same corpus produce byte-identical output.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stella.benchmark.sampling import (
    DEFAULT_SEED,
    PILOT_PAPERS,
    SUPPLEMENTAL_ALLOCATION,
    FramePaper,
    build_manifest_entries,
    build_manifest,
    measure_tex_complexity,
)
from stella.benchmark.versions import check_paper_versions
from stella.benchmark.paths import campaign_paths

WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = campaign_paths(WORKSPACE).sampling_manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build benchmark/campaigns/hvs-extraction-v2/manifest/sampling_manifest.json from the literature corpus."
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
        help="Manifest output path. Default: benchmark/campaigns/hvs-extraction-v2/manifest/sampling_manifest.json",
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


def collect_version_results(
    frame: list[FramePaper], literature_dir: Path, *, supplemental_only: bool
) -> dict[str, dict]:
    base_ids: set[str] = set()
    if supplemental_only:
        # The legacy flag remains useful for quick development builds, but
        # supplemental eligibility can never skip its version gate.
        base_entries, _ = build_manifest_entries(
            frame,
            version_consistency={paper.arxiv_id: True for paper in frame},
        )
        base_ids = {
            entry["arxiv_id"]
            for entry in base_entries
            if entry["sampling_phase"] == "base"
        }
    results: dict[str, dict] = {}
    supplemental_cells = set(SUPPLEMENTAL_ALLOCATION)
    for paper in frame:
        if supplemental_only and (
            paper.arxiv_id in base_ids
            or (paper.stratum, paper.complexity_bin) not in supplemental_cells
        ):
            continue
        results[paper.arxiv_id] = check_paper_versions(
            literature_dir / paper.arxiv_id, paper.arxiv_id
        )
    return results


def main() -> int:
    args = build_parser().parse_args()
    literature_dir = args.literature_dir.expanduser()
    frame = load_frame(literature_dir)
    if not frame:
        raise SystemExit(f"no candidate files found under {literature_dir}")

    version_results = collect_version_results(
        frame,
        literature_dir,
        supplemental_only=args.skip_version_check,
    )
    version_consistency = {
        arxiv_id: result["version_consistent"]
        for arxiv_id, result in version_results.items()
    }
    manifest = build_manifest(
        frame,
        seed=args.seed,
        version_consistency=version_consistency,
    )
    for entry in manifest["papers"]:
        result = version_results.get(entry["arxiv_id"])
        if result is not None:
            entry.update(result)
    if not args.skip_version_check:
        for entry in manifest["papers"]:
            if entry["version_consistent"] is None:
                manifest["warnings"].append(
                    f"{entry['arxiv_id']}: arXiv version undecidable "
                    f"(pdf={entry['pdf_version']}, abs={entry['abs_version']})"
                )
            elif entry["version_consistent"] is False:
                manifest["warnings"].append(
                    f"{entry['arxiv_id']}: PDF version v{entry['pdf_version']} does not "
                    f"match abs page v{entry['abs_version']}"
                )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Frame: {manifest['frame']['size']} papers "
          f"({manifest['frame']['strata']})")
    for cell, info in manifest["frame"]["cells"].items():
        print(f"  {cell}: {info['sampled']}/{info['population']} "
              f"(weight {info['sampling_weight']:.3f})")
    print(f"Sampled: {len(manifest['papers'])} PDF-only expert papers")
    for warning in manifest["warnings"]:
        print(f"WARNING: {warning}")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
