#!/usr/bin/env python3
"""Scan an archived extraction run for traces of the private gold store.

Post-run leak audit for the benchmark anti-contamination rules (AGENTS.md).
It collects leak markers from the external private gold store
(STELLA_GOLD_DIR) — per-file canary strings plus gold-specific metadata
patterns — and reports every occurrence inside the audited directory
(typically benchmark/runs/<run_id>/ or an agent transcript dump).

Scanned markers are gold-*specific* strings only: canaries, the gold schema
version, gold file-name stems, and gold store path fragments. Plain numeric
values are deliberately NOT scanned: gold values come from the papers
themselves, so a run legitimately extracting the same numbers would be
indistinguishable from a leak.

Exit status: 0 when clean, 1 when any marker is found, 2 on usage errors.

Usage:
    conda run -n stella-env python scripts/audit_extraction_run.py \
        benchmark/runs/<run_id>
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from stella.lit.env import load_env_files

WORKSPACE = Path(__file__).resolve().parents[1]
GOLD_DIR_ENV = "STELLA_GOLD_DIR"
MAX_FILE_BYTES = 50_000_000
AUDIT_SCHEMA_VERSION = "stella.benchmark_leakage_audit.v0.1"

# Gold-specific strings whose presence in run artifacts indicates that gold
# content (or the gold store itself) reached the extraction context.
STATIC_MARKERS = (
    "stella-gold-canary",
    "stella.benchmark_gold_annotation",
    "stella-hvs-gold",
    "benchmark/gold",
)


def default_gold_dir() -> Path | None:
    value = os.environ.get(GOLD_DIR_ENV, "").strip()
    return Path(value).expanduser() if value else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scan run artifacts for private gold store leak markers."
    )
    parser.add_argument(
        "run_dir",
        type=Path,
        help="Directory to audit, e.g. benchmark/runs/<run_id>.",
    )
    parser.add_argument(
        "--gold-dir",
        type=Path,
        default=None,
        help=f"External private gold annotation root. Default: ${GOLD_DIR_ENV}.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optional path to also write the JSON report to.",
    )
    return parser


def collect_markers(gold_dir: Path) -> dict[str, str]:
    """Return marker -> description for every gold-specific string."""

    markers: dict[str, str] = {
        marker: "static gold-store marker" for marker in STATIC_MARKERS
    }
    for path in sorted(gold_dir.glob("*/annotation_*.json")):
        relative = f"{path.parent.name}/{path.name}"
        markers.setdefault(path.stem, f"gold file stem ({relative})")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        canary = str(payload.get("canary") or "").strip()
        if canary:
            markers[canary] = f"canary ({relative})"
    return markers


def iter_audit_files(run_dir: Path) -> list[Path]:
    return [
        path
        for path in sorted(run_dir.rglob("*"))
        if path.is_file() and path.stat().st_size <= MAX_FILE_BYTES
    ]


def scan(run_dir: Path, markers: dict[str, str]) -> dict:
    hits: list[dict[str, str]] = []
    files = iter_audit_files(run_dir)
    for path in files:
        text = path.read_bytes().decode("utf-8", errors="ignore")
        for marker, description in markers.items():
            if marker in text:
                hits.append(
                    {
                        "file": path.as_posix(),
                        "marker": marker,
                        "marker_kind": description,
                    }
                )
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "run_dir": run_dir.as_posix(),
        "files_scanned": len(files),
        "markers_scanned": len(markers),
        "hits": hits,
        "status": "contaminated" if hits else "clean",
    }


def main() -> int:
    load_env_files(WORKSPACE)
    args = build_parser().parse_args()
    gold_dir = args.gold_dir if args.gold_dir is not None else default_gold_dir()
    if gold_dir is None:
        print(
            f"Set {GOLD_DIR_ENV} or pass --gold-dir to the external private "
            "gold annotation root."
        )
        return 2
    gold_dir = gold_dir.expanduser().resolve()
    if not gold_dir.is_dir():
        print(f"gold directory not found: {gold_dir}")
        return 2
    run_dir = args.run_dir.expanduser().resolve()
    if not run_dir.is_dir():
        print(f"run directory not found: {run_dir}")
        return 2

    report = scan(run_dir, collect_markers(gold_dir))
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    return 1 if report["hits"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
