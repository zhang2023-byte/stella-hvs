#!/usr/bin/env python3
"""Build the evidence review workbench for verification-role papers.

For each requested paper, anchors every AI assertion into the paper PDF and
writes a static review page under benchmark/workbench/<arxiv_id>/. Blind-role
papers are refused unconditionally (AGENTS.md, Benchmark Anti-Contamination
Rules). Papers outside the sampling manifest (e.g. Phase-2 pilots used to
exercise the tool) need --allow-unsampled.

Usage:
    python scripts/build_review_workbench.py --arxiv-id 1804.09677
    python scripts/build_review_workbench.py --all-verification
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

from stella.benchmark.workbench import (
    WorkbenchContaminationError,
    build_paper_workbench,
    ensure_reviewable,
)

WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = WORKSPACE / "benchmark" / "manifest" / "sampling_manifest.json"
DEFAULT_OUTPUT = WORKSPACE / "benchmark" / "workbench"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build static evidence review pages for verification papers."
    )
    parser.add_argument(
        "--arxiv-id",
        action="append",
        default=[],
        help="Paper to build (repeatable).",
    )
    parser.add_argument(
        "--all-verification",
        action="store_true",
        help="Build every verification-role paper in the manifest.",
    )
    parser.add_argument(
        "--literature-dir",
        type=Path,
        default=WORKSPACE / "literature",
        help="Archived literature root. Default: literature/",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Sampling manifest path. Default: benchmark/manifest/sampling_manifest.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Workbench output root. Default: benchmark/workbench/",
    )
    parser.add_argument(
        "--allow-unsampled",
        action="store_true",
        help="Allow papers outside the manifest (pilots). Blind papers stay refused.",
    )
    return parser


def write_index(output_dir: Path, reports: list[dict]) -> None:
    rows = "\n".join(
        f'<li><a href="{report["arxiv_id"]}/index.html">{report["arxiv_id"]}</a>'
        f' — {report["located"]}/{report["assertions"]} located</li>'
        for report in sorted(reports, key=lambda item: item["arxiv_id"])
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "index.html").write_text(
        "<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<title>Review workbench</title></head><body>"
        f"<h1>Review workbench</h1><ul>\n{rows}\n</ul></body></html>\n",
        encoding="utf-8",
    )


def main() -> int:
    args = build_parser().parse_args()
    manifest = json.loads(args.manifest.expanduser().read_text(encoding="utf-8"))

    requested = list(dict.fromkeys(args.arxiv_id))
    if args.all_verification:
        requested.extend(
            entry["arxiv_id"]
            for entry in manifest.get("papers", [])
            if entry.get("role") == "verification"
            and entry["arxiv_id"] not in requested
        )
    if not requested:
        raise SystemExit("nothing to build: pass --arxiv-id or --all-verification")

    literature_dir = args.literature_dir.expanduser()
    output_root = args.output_dir.expanduser()
    reports: list[dict] = []
    failures: list[str] = []
    for arxiv_id in requested:
        try:
            role = ensure_reviewable(
                manifest, arxiv_id, allow_unsampled=args.allow_unsampled
            )
        except WorkbenchContaminationError as error:
            raise SystemExit(f"REFUSED: {error}") from error
        extraction_path = (
            literature_dir / arxiv_id / "literature_hvs_candidates.json"
        )
        pdf_path = literature_dir / arxiv_id / "arxiv.pdf"
        missing = [
            str(path) for path in (extraction_path, pdf_path) if not path.is_file()
        ]
        if missing:
            failures.append(f"{arxiv_id}: missing {', '.join(missing)}")
            continue
        report = build_paper_workbench(
            arxiv_id,
            extraction_path,
            pdf_path,
            output_root / arxiv_id,
            pdf_href=html.escape(
                f"../../../literature/{arxiv_id}/arxiv.pdf", quote=True
            ),
        )
        report["role"] = role
        reports.append(report)
        print(
            f"{arxiv_id}: {report['located']}/{report['assertions']} "
            f"assertions located ({role})"
        )

    if reports:
        write_index(output_root, reports)
        print(f"Index: {output_root / 'index.html'}")
    for failure in failures:
        print(f"SKIPPED: {failure}")
    return 1 if failures and not reports else 0


if __name__ == "__main__":
    raise SystemExit(main())
