#!/usr/bin/env python3
"""Generate the human-facing version reference from the central registry."""

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
    output = ROOT / "docs" / "versions.md"
    output.write_text(render(), encoding="utf-8")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
