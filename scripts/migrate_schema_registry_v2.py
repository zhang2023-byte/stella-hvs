#!/usr/bin/env python3
"""Migrate active canonical Stella JSON to the 0.2 structured schema envelope.

Dry-run is the default. Historical benchmark runs, scorecards, and logs are
intentionally outside the migration scope and remain byte-identical.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from stella.legacy_versions import normalize_legacy_schema
from stella.schema_registry import STELLA_RELEASE, require_schema, schema_ref

WORKSPACE = Path(__file__).resolve().parents[1]
ACTIVE_GLOBS = (
    "notes/*.json",
    "notes/[0-9][0-9][0-9][0-9]/*/*.json",
    "literature/*/audit.json",
    "literature/*/catalog_review.json",
    "literature/*/catalog_extraction.json",
    "literature/*/literature_hvs_candidates.json",
    "literature/*.json",
    "catalog/candidates/*.json",
    "catalog/*.json",
)


def _normalize_provenance(payload: dict[str, Any]) -> None:
    extraction = payload.get("extraction")
    if not isinstance(extraction, dict) or "tooling" not in extraction:
        return
    tooling = extraction.pop("tooling")
    if not isinstance(tooling, dict):
        tooling = {}
    legacy = "unknown_legacy"
    extraction["provenance"] = {
        "stella_release": legacy if tooling.get("model_id") == legacy else STELLA_RELEASE,
        "producer": str(tooling.get("agent_runtime") or extraction.get("extractor") or legacy),
        "git_commit": str(tooling.get("prompt_version") or legacy),
        "runtime": str(tooling.get("agent_runtime") or legacy),
        "model_id": str(tooling.get("model_id") or legacy),
        "component_hashes": {},
        "parameters": tooling.get("request_parameters") if isinstance(tooling.get("request_parameters"), dict) else {},
    }


def migrate_payload(payload: Any, *, path: Path | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("top-level JSON must be an object")
    if "schema" in payload:
        result = deepcopy(payload)
    elif payload.get("schema_version") is not None:
        result = normalize_legacy_schema(payload)
    elif path is not None and path.name == "audit.json":
        result = deepcopy(payload)
        result["schema"] = schema_ref("literature.assets_audit")
    else:
        raise ValueError("schema-less artifact cannot be inferred safely")
    name, _ = require_schema(result, str((result.get("schema") or {}).get("name") or ""))
    if name == "article_data_assets.extraction":
        review = result.get("review")
        if isinstance(review, dict):
            review.pop("schema_version", None)
    if name in {"article_data_assets.index", "literature.index"}:
        result.pop("review_schema_version", None)
        result.pop("month_schema_version", None)
    if name == "hvs_candidate_catalog.object":
        dynamics = result.get("dynamics")
        if isinstance(dynamics, dict):
            dynamics.pop("schema_version", None)
    if name == "literature_hvs_candidates":
        _normalize_provenance(result)
    return result


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def iter_paths(workspace: Path) -> list[Path]:
    return sorted({path for pattern in ACTIVE_GLOBS for path in workspace.glob(pattern) if path.is_file()})


def migrate(workspace: Path, *, write: bool) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for path in iter_paths(workspace):
        relative = path.relative_to(workspace).as_posix()
        try:
            original = json.loads(path.read_text(encoding="utf-8"))
            migrated = migrate_payload(original, path=path)
            changed = original != migrated
            if changed and write:
                _atomic_write(path, migrated)
            records.append({"path": relative, "status": "changed" if changed else "unchanged"})
        except Exception as exc:
            records.append({"path": relative, "status": "error", "error": f"{type(exc).__name__}: {exc}"})
    return {
        "write": write,
        "files_seen": len(records),
        "changed": sum(record["status"] == "changed" for record in records),
        "unchanged": sum(record["status"] == "unchanged" for record in records),
        "errors": sum(record["status"] == "error" for record in records),
        "files": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=WORKSPACE)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = migrate(args.workspace.resolve(), write=args.write)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print(text, end="")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
