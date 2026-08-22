#!/usr/bin/env python3
"""Validate one hvs_dynamics.input_selection record against its sources."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]

from stella.dyn.input_selection import (  # noqa: E402
    InputSelectionError,
    validate_input_selection,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fail-closed validation of an explicit dynamics input selection.",
    )
    parser.add_argument("selection", type=Path, help="Path to the selection JSON.")
    parser.add_argument(
        "--object-id",
        default=None,
        help="Expected catalog object id (optional cross-check).",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=WORKSPACE,
        help="Workspace root for resolving relative contribution paths.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        selection = json.loads(args.selection.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"unreadable selection: {exc}", file=sys.stderr)
        return 2
    try:
        validate_input_selection(
            selection,
            workspace=args.workspace,
            expected_object_id=args.object_id,
        )
    except InputSelectionError as exc:
        print(f"invalid selection: {exc}", file=sys.stderr)
        return 1
    selected = selection.get("selected") or {}
    print(
        f"valid selection: object={selection.get('object_id')} "
        f"field={selected.get('field')} record={selected.get('record_id')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
