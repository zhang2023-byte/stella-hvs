#!/usr/bin/env python3
"""Build the evidence review workbench for verification-role papers.

For each requested paper, anchors every AI assertion into the paper PDF and
writes a static review page under benchmark/workbench/<arxiv_id>/. Blind-role
papers are refused unconditionally (AGENTS.md, Benchmark Anti-Contamination
Rules). Papers outside the sampling manifest (e.g. Phase-2 pilots used to
exercise the tool) need --allow-unsampled.

Assertions are sourced from a pipeline run with --run-id (the
model-under-test's output, benchmark/runs/<run-id>/<arxiv-id>/) and the
output is namespaced per run so repeated or multi-model runs never overwrite
each other. Without --run-id the legacy literature/ extraction is used, which
is only appropriate for tooling smoke tests, not verification review.

Usage:
    python scripts/build_review_workbench.py --run-id pilot-07-parallel-deepseek --all-verification
    python scripts/build_review_workbench.py --run-id pilot-08-mimo-smoke --arxiv-id 1901.04559 --allow-unsampled
    python scripts/build_review_workbench.py --arxiv-id 1804.09677  # legacy literature/ source
"""

from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path

from stella.benchmark.workbench import (
    WorkbenchContaminationError,
    build_paper_workbench,
    ensure_reviewable,
)

WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = WORKSPACE / "benchmark" / "manifest" / "sampling_manifest.json"
DEFAULT_OUTPUT = WORKSPACE / "benchmark" / "workbench"
DEFAULT_RUNS = WORKSPACE / "benchmark" / "runs"


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
    parser.add_argument(
        "--run-id",
        default=None,
        help=(
            "Source assertions from this pipeline run "
            "(benchmark/runs/<run-id>/<arxiv-id>/) instead of the legacy "
            "literature/ extraction. Output is namespaced under the run."
        ),
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=DEFAULT_RUNS,
        help="Pipeline runs root. Default: benchmark/runs/",
    )
    return parser


def run_provenance(runs_dir: Path, run_id: str) -> str:
    """Human-readable 'which run/model produced this' label for the header."""

    config_path = runs_dir / run_id / "run_config.json"
    if not config_path.is_file():
        return f"run {run_id}"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    parts = [f"run {run_id}"]
    if config.get("model"):
        parts.append(f"model {config['model']}")
    if config.get("pipeline"):
        parts.append(f"pipeline {config['pipeline']}")
    return " · ".join(parts)


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
    runs_dir = args.runs_dir.expanduser()
    run_id = args.run_id
    # Verification experts must review the model-under-test's output, not the
    # legacy interactive extraction; --run-id sources from the pipeline run and
    # namespaces the output so repeated/multi-model runs never overwrite.
    output_root = args.output_dir.expanduser()
    output_base = output_root / run_id if run_id else output_root
    provenance = run_provenance(runs_dir, run_id) if run_id else ""

    reports: list[dict] = []
    failures: list[str] = []
    for arxiv_id in requested:
        try:
            role = ensure_reviewable(
                manifest, arxiv_id, allow_unsampled=args.allow_unsampled
            )
        except WorkbenchContaminationError as error:
            raise SystemExit(f"REFUSED: {error}") from error
        if run_id:
            extraction_path = (
                runs_dir / run_id / arxiv_id / "literature_hvs_candidates.json"
            )
        else:
            extraction_path = (
                literature_dir / arxiv_id / "literature_hvs_candidates.json"
            )
        # The PDF is the normative evidence source; always from the archive,
        # never from the run output.
        pdf_path = literature_dir / arxiv_id / "arxiv.pdf"
        missing = [
            str(path) for path in (extraction_path, pdf_path) if not path.is_file()
        ]
        if missing:
            failures.append(f"{arxiv_id}: missing {', '.join(missing)}")
            continue
        paper_output_dir = output_base / arxiv_id
        # relpath keeps the PDF href correct regardless of how deep the output
        # directory is nested (the per-run namespace adds a level).
        pdf_href = Path(
            os.path.relpath(pdf_path.resolve(), paper_output_dir.resolve())
        ).as_posix()
        report = build_paper_workbench(
            arxiv_id,
            extraction_path,
            pdf_path,
            paper_output_dir,
            pdf_href=html.escape(pdf_href, quote=True),
            provenance=provenance,
        )
        report["role"] = role
        reports.append(report)
        print(
            f"{arxiv_id}: {report['located']}/{report['assertions']} "
            f"assertions located ({role})"
        )

    if reports:
        write_index(output_base, reports)
        print(f"Index: {output_base / 'index.html'}")
    for failure in failures:
        print(f"SKIPPED: {failure}")
    return 1 if failures and not reports else 0


if __name__ == "__main__":
    raise SystemExit(main())
