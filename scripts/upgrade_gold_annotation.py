#!/usr/bin/env python3
"""Upgrade an expert annotation YAML into a private gold JSON document.

Part of the expert-led annotation workflow: this validates the expert YAML and
writes the generated JSON twin next to it. The gold directory normally lives in
the private benchmark-gold repository pointed to by STELLA_GOLD_DIR.

Usage:
    python scripts/upgrade_gold_annotation.py $STELLA_GOLD_DIR/<arxiv_id>/annotation_<annotator>.yaml

Validates the annotation against the gold schema (controlled vocabularies
are imported from the frozen extraction schema), cross-checks the paper
against the sampling manifest, and writes the JSON next to the input file.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from stella.benchmark.gold import (
    GoldAnnotation,
    gold_json_document,
    lint_annotation,
)
from stella.benchmark.paths import campaign_paths, require_external_path

WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = campaign_paths(WORKSPACE).sampling_manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and upgrade an expert annotation YAML into gold JSON."
    )
    parser.add_argument(
        "annotation",
        type=Path,
        help="Annotation YAML path, e.g. $STELLA_GOLD_DIR/<arxiv_id>/annotation_<annotator>.yaml",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON path. Default: input path with .yaml replaced by .json.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Sampling manifest used for cross-checks. Default: the active campaign sampling_manifest.json",
    )
    return parser


def manifest_entry(manifest_path: Path, arxiv_id: str) -> dict | None:
    if not manifest_path.is_file():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest.get("papers", []):
        if entry.get("arxiv_id") == arxiv_id:
            return entry
    return None


def main() -> int:
    args = build_parser().parse_args()
    try:
        annotation_path = require_external_path(
            args.annotation, workspace=WORKSPACE, label="gold annotation"
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    payload = yaml.safe_load(annotation_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"{annotation_path}: annotation must be a YAML mapping")

    annotation = GoldAnnotation.model_validate(payload)
    for warning in lint_annotation(annotation):
        print(f"LINT WARNING: {warning}")
    document = gold_json_document(annotation)

    arxiv_id = document["arxiv_id"]
    parent = annotation_path.parent.name
    if parent != arxiv_id:
        raise SystemExit(
            f"{annotation_path}: arxiv_id {arxiv_id} does not match "
            f"directory {parent}"
        )
    entry = manifest_entry(args.manifest.expanduser(), arxiv_id)
    if entry is None:
        print(f"WARNING: {arxiv_id} is not in the sampling manifest")
    else:
        print(
            "Manifest sample: "
            f"{entry.get('stratum', 'unknown')}, "
            f"{entry.get('complexity_bin', 'unknown')}, "
            f"legacy_status={entry.get('legacy_status', 'unknown')}, "
            f"weight={entry.get('sampling_weight', 'unknown')}"
        )

    output = (
        args.output.expanduser()
        if args.output is not None
        else annotation_path.with_suffix(".json")
    )
    try:
        output = require_external_path(
            output, workspace=WORKSPACE, label="gold JSON output"
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
