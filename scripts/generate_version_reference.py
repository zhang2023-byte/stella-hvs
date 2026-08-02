#!/usr/bin/env python3
"""Generate the human-facing version reference from the central registry."""

import argparse
from pathlib import Path

from stella.schema_registry import ACTIVE_BENCHMARK_CAMPAIGN, STELLA_RELEASE, list_schema_status

ROOT = Path(__file__).resolve().parents[1]


def render() -> str:
    lines = [
        "# Version reference",
        "",
        "This page is generated from `src/stella/schema_registry.py`; do not edit its table by hand.",
        "",
        f"- Stella release: `{STELLA_RELEASE}`",
        f"- Active benchmark campaign: `{ACTIVE_BENCHMARK_CAMPAIGN}`",
        "",
        "| Artifact | Current | Readable | Lifecycle |",
        "|---|---:|---|---|",
    ]
    for row in list_schema_status():
        readable = ", ".join(str(item) for item in row["readable_versions"])
        lines.append(f'| `{row["name"]}` | {row["current_version"]} | {readable} | {row["lifecycle"]} |')
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if docs/versions.md is not the current generated view.",
    )
    args = parser.parse_args()
    output = ROOT / "docs" / "versions.md"
    expected = render()
    if args.check:
        if not output.is_file() or output.read_text(encoding="utf-8") != expected:
            raise SystemExit("docs/versions.md is stale; regenerate it")
        print(f"Verified {output}")
        return 0
    output.write_text(expected, encoding="utf-8")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
