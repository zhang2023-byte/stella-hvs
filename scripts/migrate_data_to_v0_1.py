#!/usr/bin/env python3
"""Migrate on-disk Stella data files to the unified v0.1 schema versions.

Mechanical and idempotent: rewrites exact known pre-v0.1 schema version
strings wherever they appear as JSON string values, and fills
extraction.tooling with explicit "unknown_legacy" provenance in
literature_hvs_candidates.json files that predate the tooling field. File
shapes are unchanged; no scientific content is touched.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

WORKSPACE = Path(__file__).resolve().parents[1]

VERSION_MAP = {
    "stella.literature_hvs_candidates.v7": "stella.literature_hvs_candidates.v0.1",
    "stella.literature_hvs_candidates.index.v3": "stella.literature_hvs_candidates.index.v0.1",
    "stella.article_data_assets.review.v1": "stella.article_data_assets.review.v0.1",
    "stella.article_data_assets.extraction.v2": "stella.article_data_assets.extraction.v0.1",
    "stella.article_data_assets.inventory.v1": "stella.article_data_assets.inventory.v0.1",
    "stella.article_data_assets.index.v1": "stella.article_data_assets.index.v0.1",
    "stella.hvs_candidate_catalog.object.v6": "stella.hvs_candidate_catalog.object.v0.1",
    "stella.hvs_candidate_catalog.index.v3": "stella.hvs_candidate_catalog.index.v0.1",
    "stella.hvs_dynamics.v1": "stella.hvs_dynamics.v0.1",
    "stella.literature.month.v3": "stella.literature.month.v0.1",
    "stella.literature.index.v4": "stella.literature.index.v0.1",
    "stella.literature.title_triage.v1": "stella.literature.title_triage.v0.1",
    "stella.literature.assets_audit.v2": "stella.literature.assets_audit.v0.1",
    "stella.hvs_catalog_site.snapshot.v2": "stella.hvs_catalog_site.snapshot.v0.1",
    "stella.arxiv.metadata.report.v1": "stella.arxiv.metadata.report.v0.1",
}

LEGACY_TOOLING = {
    "agent_runtime": "unknown_legacy",
    "model_id": "unknown_legacy",
    "prompt_version": "unknown_legacy",
    "request_parameters": {},
}

DATA_GLOBS = (
    "literature/*/audit.json",
    "literature/*/catalog_review.json",
    "literature/*/catalog_extraction.json",
    "literature/*/literature_hvs_candidates.json",
    "literature/*.json",
    "catalog/candidates/*.json",
    "catalog/*.json",
    "notes/[0-9][0-9][0-9][0-9]/*/*.json",
    "notes/*.json",
)


def rewrite_versions(node: Any) -> tuple[Any, int]:
    if isinstance(node, str):
        replacement = VERSION_MAP.get(node)
        return (replacement, 1) if replacement is not None else (node, 0)
    if isinstance(node, list):
        replaced = 0
        items = []
        for item in node:
            new_item, count = rewrite_versions(item)
            items.append(new_item)
            replaced += count
        return items, replaced
    if isinstance(node, dict):
        replaced = 0
        mapping = {}
        for key, value in node.items():
            new_value, count = rewrite_versions(value)
            mapping[key] = new_value
            replaced += count
        return mapping, replaced
    return node, 0


def ensure_legacy_tooling(payload: Any, path: Path) -> int:
    if path.name != "literature_hvs_candidates.json" or not isinstance(payload, dict):
        return 0
    extraction = payload.get("extraction")
    if not isinstance(extraction, dict) or extraction.get("tooling") is not None:
        return 0
    extraction["tooling"] = dict(LEGACY_TOOLING)
    return 1


def migrate(workspace: Path, *, dry_run: bool) -> dict[str, int]:
    stats = {"files_seen": 0, "files_changed": 0, "version_strings": 0, "tooling_filled": 0, "unparseable": 0}
    seen: set[Path] = set()
    for pattern in DATA_GLOBS:
        for path in sorted(workspace.glob(pattern)):
            if path in seen:
                continue
            seen.add(path)
            stats["files_seen"] += 1
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                stats["unparseable"] += 1
                print(f"SKIP unparseable: {path.relative_to(workspace)}")
                continue
            payload, replaced = rewrite_versions(payload)
            filled = ensure_legacy_tooling(payload, path)
            if replaced == 0 and filled == 0:
                continue
            stats["files_changed"] += 1
            stats["version_strings"] += replaced
            stats["tooling_filled"] += filled
            if not dry_run:
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=WORKSPACE)
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing files.")
    args = parser.parse_args()
    stats = migrate(args.workspace.resolve(), dry_run=args.dry_run)
    print(json.dumps({"dry_run": args.dry_run, **stats}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
