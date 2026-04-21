#!/usr/bin/env python3
"""Persist an agent adjudication and sync the effective result back to notes/index."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
SRC = WORKSPACE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from high_velocity_lit.literature_catalog import (  # noqa: E402
    apply_agent_adjudication,
    build_agent_adjudication,
    build_catalog_verification_summary,
    read_json,
    sync_verification_to_notes,
)

DEFAULT_SKILL_PATH = WORKSPACE / "skills" / "literature-catalog-verifier" / "SKILL.md"
FRONTMATTER_RE = re.compile(r"\A---\n(?P<body>.*?)\n---\n", re.DOTALL)


def parse_bool(text: str) -> bool:
    lowered = text.strip().lower()
    if lowered in {"1", "true", "yes", "y"}:
        return True
    if lowered in {"0", "false", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError("expected one of: true/false/yes/no/1/0")


def read_skill_frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}
    result: dict[str, str] = {}
    for raw_line in match.group("body").splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip().strip("'\"")
    return result


def relative_skill_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE.resolve()))
    except ValueError:
        return str(path.resolve())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write an agent adjudication into literature/<arxiv_id>/record.json and refresh notes/index."
    )
    parser.add_argument("--arxiv-id", required=True, help="Target arXiv ID.")
    parser.add_argument("--has-catalog", required=True, type=parse_bool, help="Whether the agent confirms catalog data.")
    parser.add_argument(
        "--catalog-scope",
        default="object_level_or_sample_level",
        help="Structured scope label. Default: object_level_or_sample_level.",
    )
    parser.add_argument(
        "--internal-delivery",
        required=True,
        help="One of full|partial|format_only|none|unclear.",
    )
    parser.add_argument(
        "--external-delivery",
        required=True,
        help="One of full|partial|reference_only|none|unclear.",
    )
    parser.add_argument(
        "--location-class",
        required=True,
        help="One of internal_only|external_only|mixed|unclear.",
    )
    parser.add_argument("--primary-host", default="", help="Primary host such as cds, vizier, china-vo, or none.")
    parser.add_argument("--confidence", default="high", help="high|medium|low")
    parser.add_argument("--overall-verdict", default="", help="Optional override for the stored effective verdict.")
    parser.add_argument("--evidence", action="append", default=[], help="Evidence sentence. Repeat this flag as needed.")
    parser.add_argument("--reasoning-notes", required=True, help="Short explanation for the adjudication.")
    parser.add_argument("--reviewed-by", default="agent", help="Reviewer label. Default: agent.")
    parser.add_argument("--reviewed-at", default="", help="ISO timestamp override. Default: now.")
    parser.add_argument(
        "--skill-path",
        type=Path,
        default=DEFAULT_SKILL_PATH,
        help="Repo-local SKILL.md used for this adjudication. Default: skills/literature-catalog-verifier/SKILL.md",
    )
    parser.add_argument("--skill-version", default="", help="Optional explicit skill version override.")
    parser.add_argument("--notes-dir", type=Path, default=WORKSPACE / "notes")
    parser.add_argument("--output-dir", type=Path, default=WORKSPACE / "literature")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    paper_dir = args.output_dir / args.arxiv_id
    record_path = paper_dir / "record.json"
    if not record_path.exists():
        raise SystemExit(f"Missing verification record: {record_path}")

    record = read_json(record_path)
    skill_frontmatter = read_skill_frontmatter(args.skill_path)
    skill_version = args.skill_version or skill_frontmatter.get("version") or ""
    adjudication = build_agent_adjudication(
        record=record,
        reviewed_at=args.reviewed_at,
        reviewed_by=args.reviewed_by,
        skill_path=relative_skill_path(args.skill_path),
        skill_version=skill_version,
        has_catalog_data=args.has_catalog,
        catalog_scope=args.catalog_scope,
        internal_delivery=args.internal_delivery,
        external_delivery=args.external_delivery,
        location_class=args.location_class,
        primary_host=args.primary_host,
        confidence=args.confidence,
        evidence=args.evidence,
        reasoning_notes=args.reasoning_notes,
        overall_verdict=args.overall_verdict,
    )
    updated_record = apply_agent_adjudication(
        record_path=record_path,
        adjudication=adjudication,
    )
    effective_summary = build_catalog_verification_summary(
        updated_record,
        paper_dir=paper_dir,
        workspace_root=WORKSPACE,
    )
    note_sync = sync_verification_to_notes(
        notes_dir=args.notes_dir,
        arxiv_id=args.arxiv_id,
        verification_record=updated_record,
        literature_root=args.output_dir,
        workspace_root=WORKSPACE,
    )
    print(
        json.dumps(
            {
                "arxiv_id": args.arxiv_id,
                "record_path": str(record_path),
                "summary_path": str(paper_dir / "summary.md"),
                "catalog_verification": effective_summary,
                "note_sync": note_sync,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
