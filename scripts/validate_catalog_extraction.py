#!/usr/bin/env python3
"""Validate Stella catalog_extraction.json files."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from astropy.io import ascii
from pydantic import ValidationError

WORKSPACE = Path(__file__).resolve().parents[1]
SRC = WORKSPACE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from high_velocity_lit.schema_models import CatalogExtractionRecord  # noqa: E402


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def resolve_path(value: str, *, workspace: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return workspace / path


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_catalog_extraction(
    payload: Any,
    *,
    workspace: Path = WORKSPACE,
    require_reviewed: bool = False,
) -> list[str]:
    errors: list[str] = []
    try:
        record = CatalogExtractionRecord.model_validate(payload)
    except ValidationError as exc:
        return [f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()]

    review_path = resolve_path(record.review.path, workspace=workspace)
    if not review_path.exists():
        errors.append(f"review.path: path does not exist: {review_path}")
    if require_reviewed and record.review.review_status == "needs_review":
        errors.append("review.review_status: expected a completed catalog review, not 'needs_review'")

    excerpt_hashes: dict[str, str] = {}
    for index, file_record in enumerate(record.files):
        location = f"files[{index}]"
        if file_record.status in {"written", "skipped_existing"}:
            excerpt_path = resolve_path(file_record.excerpt_path, workspace=workspace)
            if not excerpt_path.exists():
                errors.append(f"{location}.excerpt_path: path does not exist: {excerpt_path}")
            else:
                text = excerpt_path.read_text(encoding="utf-8")
                digest = sha256_text(text)
                excerpt_hashes[file_record.internal_table_id] = digest
                if file_record.sha256 and digest != file_record.sha256:
                    errors.append(f"{location}.sha256: does not match excerpt file")

    for index, table in enumerate(record.tables):
        location = f"tables[{index}]"
        if table.internal_table_id in excerpt_hashes and table.source_sha256 != excerpt_hashes[table.internal_table_id]:
            errors.append(f"{location}.source_sha256: does not match corresponding excerpt")
        if table.status in {"success", "skipped_existing"}:
            ecsv_path = resolve_path(table.ecsv_path, workspace=workspace)
            if not ecsv_path.exists():
                errors.append(f"{location}.ecsv_path: path does not exist: {ecsv_path}")
                continue
            try:
                parsed = ascii.read(ecsv_path, format="ecsv")
            except Exception as exc:  # pragma: no cover - astropy exception types vary.
                errors.append(f"{location}.ecsv_path: could not parse ECSV: {exc}")
                continue
            if len(parsed) != table.row_count:
                errors.append(f"{location}.row_count: expected {len(parsed)} from ECSV")
            if len(parsed.colnames) != table.column_count:
                errors.append(f"{location}.column_count: expected {len(parsed.colnames)} from ECSV")
    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate one catalog_extraction.json file.")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--path", type=Path)
    selection.add_argument("--arxiv-id")
    parser.add_argument("--literature-dir", type=Path, default=WORKSPACE / "literature")
    parser.add_argument("--workspace", type=Path, default=WORKSPACE)
    parser.add_argument(
        "--require-reviewed",
        action="store_true",
        help="Fail if catalog_extraction.json was generated from a review still marked needs_review.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    path = args.path.expanduser() if args.path else args.literature_dir.expanduser() / str(args.arxiv_id) / "catalog_extraction.json"
    if not path.exists():
        print(f"missing catalog extraction JSON: {path}", file=sys.stderr)
        return 1
    try:
        payload = load_json(path)
    except json.JSONDecodeError as exc:
        print(f"invalid JSON: {exc}", file=sys.stderr)
        return 1
    errors = validate_catalog_extraction(
        payload,
        workspace=args.workspace.expanduser(),
        require_reviewed=args.require_reviewed,
    )
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"OK: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
