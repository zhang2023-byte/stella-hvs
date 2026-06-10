"""Canonical path helpers for the benchmark directory tree."""

from __future__ import annotations

from pathlib import Path

CANDIDATES_FILENAME = "literature_hvs_candidates.json"


def benchmark_root(workspace: Path) -> Path:
    return workspace / "benchmark"


def manifest_path(root: Path) -> Path:
    return root / "manifest" / "benchmark_manifest.json"


def variants_dir(root: Path) -> Path:
    return root / "variants"


def variant_dir(root: Path, variant_id: str) -> Path:
    return variants_dir(root) / variant_id


def variant_meta_path(root: Path, variant_id: str) -> Path:
    return variant_dir(root, variant_id) / "variant_meta.json"


def variant_candidates_path(root: Path, variant_id: str, arxiv_id: str) -> Path:
    return variant_dir(root, variant_id) / arxiv_id / CANDIDATES_FILENAME


def alignment_dir(root: Path) -> Path:
    return root / "alignment"


def alignment_path(root: Path, arxiv_id: str) -> Path:
    return alignment_dir(root) / f"{arxiv_id}.alignment.json"


def alignment_index_path(root: Path) -> Path:
    return alignment_dir(root) / "alignment_index.json"


def adjudication_dir(root: Path) -> Path:
    return root / "adjudication"


def adjudication_path(root: Path, arxiv_id: str) -> Path:
    return adjudication_dir(root) / f"{arxiv_id}.adjudication.json"


def gold_dir(root: Path) -> Path:
    return root / "gold"


def gold_candidates_path(root: Path, arxiv_id: str) -> Path:
    return gold_dir(root) / arxiv_id / CANDIDATES_FILENAME


def gold_provenance_path(root: Path, arxiv_id: str) -> Path:
    return gold_dir(root) / arxiv_id / "gold_provenance.json"


def review_dir(root: Path) -> Path:
    return root / "review"


def reports_dir(root: Path) -> Path:
    return root / "reports"


def report_json_path(root: Path) -> Path:
    return reports_dir(root) / "benchmark_report.json"


def report_markdown_path(root: Path) -> Path:
    return reports_dir(root) / "benchmark_report.md"
