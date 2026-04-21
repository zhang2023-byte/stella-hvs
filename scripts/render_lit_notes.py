#!/usr/bin/env python3
"""Render literature Markdown notes from canonical JSON records."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
SRC = WORKSPACE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from high_velocity_lit.markdown import render_index, render_month_note  # noqa: E402
from high_velocity_lit.indexing import refresh_index_outputs  # noqa: E402
from high_velocity_lit.note_paths import iter_month_json_paths, resolve_month_json_path  # noqa: E402


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def month_json_paths(notes_dir: Path, months: list[str]) -> list[Path]:
    if months:
        return [resolve_month_json_path(notes_dir, month) for month in months]
    return iter_month_json_paths(notes_dir)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Regenerate Markdown literature notes from JSON records.")
    parser.add_argument("--notes-dir", type=Path, default=WORKSPACE / "notes")
    parser.add_argument("--month", action="append", default=[], help="Month slug such as 2026-03. Can be repeated.")
    parser.add_argument("--index-only", action="store_true", help="Regenerate only notes/index.md from notes/index.json.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.notes_dir.exists():
        raise SystemExit(f"notes directory does not exist: {args.notes_dir}")

    index_json = args.notes_dir / "index.json"
    if args.index_only:
        refresh_index_outputs(args.notes_dir)
        print("Rebuilt yearly index.")
        return 0

    rendered = 0
    for json_path in month_json_paths(args.notes_dir, args.month):
        if not json_path.exists():
            raise SystemExit(f"month JSON does not exist: {json_path}")
        record = read_json(json_path)
        month = str(record.get("month") or json_path.stem)
        markdown_path = json_path.parent / f"{month}.md"
        markdown_path.write_text(render_month_note(record), encoding="utf-8")
        rendered += 1

    if index_json.exists():
        index_record = read_json(index_json)
        (args.notes_dir / "index.md").write_text(render_index(index_record), encoding="utf-8")

    print(f"Rendered {rendered} monthly note{'s' if rendered != 1 else ''}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
