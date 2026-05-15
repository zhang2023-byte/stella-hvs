#!/usr/bin/env python3
"""Validate Stella catalog_review.json files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

WORKSPACE = Path(__file__).resolve().parents[1]
SRC = WORKSPACE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from high_velocity_lit.schema_models import CatalogReviewRecord  # noqa: E402


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_path(value: str, *, workspace: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return workspace / path


def lines_for(path: Path, errors: list[str], location: str) -> list[str] | None:
    if not path.exists():
        errors.append(f"{location}: path does not exist: {path}")
        return None
    if not path.is_file():
        errors.append(f"{location}: path is not a file: {path}")
        return None
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        errors.append(f"{location}: could not read as UTF-8: {exc}")
        return None


def validate_line_range(
    *,
    path_text: str,
    start_line: int,
    end_line: int,
    location: str,
    workspace: Path,
    errors: list[str],
) -> str:
    path = resolve_path(path_text, workspace=workspace)
    lines = lines_for(path, errors, f"{location}.path")
    if lines is None:
        return ""
    if start_line < 1 or end_line < start_line or end_line > len(lines):
        errors.append(f"{location}.line_range: invalid line range {start_line}..{end_line} for {len(lines)} lines")
        return ""
    return "\n".join(lines[start_line - 1 : end_line])


def validate_complete_review(record: CatalogReviewRecord, errors: list[str]) -> None:
    if record.review.status == "needs_review":
        errors.append("review.status: expected a completed status, not 'needs_review'")
    if not record.review.summary.strip() and record.review.status != "source_missing":
        errors.append("review.summary: expected a non-empty completion summary")

    if record.review.status == "source_missing":
        return

    for index, table in enumerate(record.internal_tables):
        location = f"internal_tables[{index}]"
        if not table.asset_type.strip():
            errors.append(f"{location}.asset_type: expected Agent-filled asset type")
        if not table.role_in_paper.strip():
            errors.append(f"{location}.role_in_paper: expected Agent-filled paper role")
        if not table.evidence.strip():
            errors.append(f"{location}.evidence: expected paper-grounded evidence")
        for column_index, column in enumerate(table.columns):
            column_location = f"{location}.columns[{column_index}]"
            if not column.meaning.strip():
                errors.append(f"{column_location}.meaning: expected Agent-filled column meaning")

    for index, resource in enumerate(record.external_resources):
        location = f"external_resources[{index}]"
        if not resource.description.strip():
            errors.append(f"{location}.description: expected Agent-filled resource description")
        if not resource.evidence.strip() and resource.source_refs:
            errors.append(f"{location}.evidence: expected paper-grounded evidence")


def validate_catalog_review(
    payload: Any,
    *,
    workspace: Path = WORKSPACE,
    require_complete: bool = False,
) -> list[str]:
    errors: list[str] = []
    try:
        record = CatalogReviewRecord.model_validate(payload)
    except ValidationError as exc:
        return [f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()]

    table_ids: set[str] = set()
    for index, table in enumerate(record.internal_tables):
        location = f"internal_tables[{index}]"
        if table.id in table_ids:
            errors.append(f"{location}.id: duplicate internal table id {table.id!r}")
        table_ids.add(table.id)
        if not table.source_refs:
            errors.append(f"{location}.source_refs: expected at least one source reference")
        for ref_index, ref in enumerate(table.source_refs):
            validate_line_range(
                path_text=ref.path,
                start_line=ref.start_line,
                end_line=ref.end_line,
                location=f"{location}.source_refs[{ref_index}]",
                workspace=workspace,
                errors=errors,
            )

    resource_ids: set[str] = set()
    for index, resource in enumerate(record.external_resources):
        location = f"external_resources[{index}]"
        if resource.id in resource_ids:
            errors.append(f"{location}.id: duplicate external resource id {resource.id!r}")
        resource_ids.add(resource.id)
        if resource.url and not resource.url.startswith(("http://", "https://")):
            errors.append(f"{location}.url: expected verbatim http(s) URL or empty string")
        for ref_index, ref in enumerate(resource.source_refs):
            text = validate_line_range(
                path_text=ref.path,
                start_line=ref.start_line,
                end_line=ref.end_line,
                location=f"{location}.source_refs[{ref_index}]",
                workspace=workspace,
                errors=errors,
            )
            if resource.url and text and resource.url not in text:
                errors.append(f"{location}.url: URL is not present in referenced source lines")
    if require_complete:
        validate_complete_review(record, errors)
    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate one catalog_review.json file.")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--path", type=Path)
    selection.add_argument("--arxiv-id")
    parser.add_argument("--literature-dir", type=Path, default=WORKSPACE / "literature")
    parser.add_argument("--workspace", type=Path, default=WORKSPACE)
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Fail if the file is still an unfilled skeleton or lacks Agent-filled semantic fields.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    path = args.path.expanduser() if args.path else args.literature_dir.expanduser() / str(args.arxiv_id) / "catalog_review.json"
    if not path.exists():
        print(f"missing catalog review JSON: {path}", file=sys.stderr)
        return 1
    try:
        payload = load_json(path)
    except json.JSONDecodeError as exc:
        print(f"invalid JSON: {exc}", file=sys.stderr)
        return 1
    errors = validate_catalog_review(
        payload,
        workspace=args.workspace.expanduser(),
        require_complete=args.require_complete,
    )
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"OK: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
