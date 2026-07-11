#!/usr/bin/env python3
"""Build the active campaign manifest."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from stella.benchmark.campaign import build_campaign, sha256_file
from stella.schema_registry import ACTIVE_BENCHMARK_CAMPAIGN, require_schema

WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = WORKSPACE / "benchmark" / "campaigns" / ACTIVE_BENCHMARK_CAMPAIGN
DEFAULT_SAMPLING = DEFAULT_ROOT / "manifest" / "sampling_manifest.json"
DEFAULT_OUTPUT = DEFAULT_ROOT / "manifest" / "campaign_manifest.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"Build {ACTIVE_BENCHMARK_CAMPAIGN} campaign manifest")
    parser.add_argument("--sampling-manifest", type=Path, default=DEFAULT_SAMPLING)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--reference-manifest",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=(
            "Existing immutable campaign contract whose code_commit is preserved "
            "during deterministic rebuilds. Default: the committed active manifest."
        ),
    )
    parser.add_argument(
        "--code-commit",
        default=None,
        help="Explicit 40-character freeze-base commit (new campaign initialization only).",
    )
    return parser


def current_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=WORKSPACE,
        check=True,
        capture_output=True,
        text=True,
    )
    commit = result.stdout.strip()
    if not commit:
        raise ValueError("HEAD does not resolve")
    return commit


def resolve_code_commit(reference_manifest: Path, explicit: str | None) -> str:
    """Resolve stable campaign metadata without binding rebuilds to moving HEAD."""

    if explicit is not None:
        value = explicit.strip().lower()
    elif reference_manifest.is_file():
        reference = json.loads(reference_manifest.read_text(encoding="utf-8"))
        try:
            require_schema(reference, "benchmark.campaign", require_current=True)
        except ValueError as exc:
            raise ValueError("reference manifest is not a current campaign contract") from exc
        if reference.get("campaign_id") != ACTIVE_BENCHMARK_CAMPAIGN:
            raise ValueError("reference manifest is for a different campaign")
        value = str(reference.get("code_commit") or "").strip().lower()
    else:
        value = current_commit().lower()
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValueError("code_commit must be a full 40-character Git commit")
    return value


def main() -> int:
    args = build_parser().parse_args()
    sampling_path = args.sampling_manifest.resolve()
    sampling = json.loads(sampling_path.read_text(encoding="utf-8"))
    try:
        display_path = str(sampling_path.relative_to(WORKSPACE))
    except ValueError:
        display_path = str(sampling_path)
    campaign = build_campaign(
        sampling,
        sampling_manifest_sha256=sha256_file(sampling_path),
        sampling_manifest_path=display_path,
        code_commit=resolve_code_commit(args.reference_manifest.expanduser(), args.code_commit),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(campaign, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Campaign: {campaign['campaign_id']}")
    print(f"Splits: {campaign['splits']}")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
