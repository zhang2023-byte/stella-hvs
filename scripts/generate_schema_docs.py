#!/usr/bin/env python3
"""Generate skill schema reference docs from Pydantic models."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
SRC = WORKSPACE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from high_velocity_lit.schema_docs import generated_schema_docs  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate skills/*/references/schema.md from code schema models.")
    parser.add_argument("--check", action="store_true", help="Exit non-zero if generated docs differ.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    changed: list[Path] = []
    for relative_path, content in generated_schema_docs().items():
        path = WORKSPACE / relative_path
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        if existing != content:
            changed.append(relative_path)
            if not args.check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

    if args.check and changed:
        for path in changed:
            print(f"schema doc is stale: {path}", file=sys.stderr)
        return 1

    for path in changed:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
