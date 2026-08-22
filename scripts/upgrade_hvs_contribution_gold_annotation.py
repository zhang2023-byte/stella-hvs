#!/usr/bin/env python3
"""Upgrade a contribution annotation YAML into its private gold JSON twin.

This validates an expert-approved contribution annotation YAML and writes the
canaried JSON twin next to it. Campaign binding and public hash manifests are
separate later operations.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from stella.benchmark.hvs_contribution_gold import (
    lint_contribution_annotation,
    upgrade_contribution_annotation,
)
from stella.benchmark.paths import require_external_path

WORKSPACE = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and upgrade an expert-approved contribution annotation YAML into gold JSON.",
    )
    parser.add_argument(
        "annotation",
        type=Path,
        help="Annotation YAML path in the private gold repository.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON path. Default: input path with .yaml replaced by .json.",
    )
    return parser


def main(argv: list[str] | None = None, workspace: Path | None = None) -> int:
    args = build_parser().parse_args(argv)
    workspace = workspace or WORKSPACE
    try:
        annotation_path = require_external_path(
            args.annotation, workspace=workspace, label="contribution gold annotation"
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    payload = yaml.safe_load(annotation_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"{annotation_path}: annotation must be a YAML mapping")

    from stella.benchmark.hvs_contribution_gold import HvsContributionGoldAnnotation

    document = upgrade_contribution_annotation(payload)
    annotation = HvsContributionGoldAnnotation.model_validate(payload)
    for warning in lint_contribution_annotation(annotation):
        print(f"LINT WARNING: {warning}")

    arxiv_id = document["arxiv_id"]
    if annotation_path.parent.name != arxiv_id:
        raise SystemExit(
            f"{annotation_path}: arxiv_id {arxiv_id} does not match "
            f"directory {annotation_path.parent.name}"
        )
    print("Validated expert-approved contribution gold; campaign binding is separate.")

    output = (
        args.output.expanduser()
        if args.output is not None
        else annotation_path.with_suffix(".json")
    )
    try:
        output = require_external_path(
            output, workspace=workspace, label="contribution gold JSON output"
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
