#!/usr/bin/env python3
"""Validate Stella per-paper HVS candidate extraction JSON files."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from typing import Any

from astropy.io import ascii


WORKSPACE = Path(__file__).resolve().parents[1]
SRC = WORKSPACE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from high_velocity_lit.schema_specs import (  # noqa: E402
    LITERATURE_HVS_CANDIDATE_STATUSES,
    LITERATURE_HVS_CANDIDATES_SCHEMA_VERSION,
)


class ValidationContext:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.errors: list[str] = []
        self.ecsv_columns: dict[Path, list[str]] = {}
        self.file_lines: dict[Path, list[str]] = {}

    def error(self, location: str, message: str) -> None:
        self.errors.append(f"{location}: {message}")

    def resolve_path(self, value: Any, location: str) -> Path | None:
        if not isinstance(value, str) or not value:
            self.error(location, "expected a non-empty path string")
            return None
        path = Path(value)
        if not path.is_absolute():
            path = self.workspace / path
        return path

    def lines_for(self, path: Path, location: str) -> list[str] | None:
        if path in self.file_lines:
            return self.file_lines[path]
        if not path.exists():
            self.error(location, f"path does not exist: {path}")
            return None
        if not path.is_file():
            self.error(location, f"path is not a file: {path}")
            return None
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError as exc:
            self.error(location, f"could not read as UTF-8: {exc}")
            return None
        self.file_lines[path] = lines
        return lines

    def columns_for_ecsv(self, path: Path, location: str) -> list[str] | None:
        if path in self.ecsv_columns:
            return self.ecsv_columns[path]
        if not path.exists():
            self.error(location, f"ECSV path does not exist: {path}")
            return None
        try:
            table = ascii.read(path, format="ecsv")
        except Exception as exc:  # pragma: no cover - astropy exception types vary.
            self.error(location, f"could not parse ECSV: {exc}")
            return None
        columns = list(table.colnames)
        self.ecsv_columns[path] = columns
        return columns


def is_dict(value: Any) -> bool:
    return isinstance(value, dict)


def is_list(value: Any) -> bool:
    return isinstance(value, list)


def validate_required_mapping(value: Any, location: str, ctx: ValidationContext) -> dict[str, Any] | None:
    if not is_dict(value):
        ctx.error(location, "expected an object")
        return None
    return value


def validate_required_list(value: Any, location: str, ctx: ValidationContext) -> list[Any] | None:
    if not is_list(value):
        ctx.error(location, "expected a list")
        return None
    return value


def validate_source_ref(ref: Any, location: str, ctx: ValidationContext) -> None:
    if not is_dict(ref):
        ctx.error(location, "expected a source reference object")
        return

    path = ctx.resolve_path(ref.get("path"), f"{location}.path")
    if path is None:
        return

    kind = ref.get("kind", "")
    if kind == "ecsv_cell" or str(path).endswith(".ecsv"):
        validate_ecsv_cell_ref(ref, path, location, ctx)
        return

    validate_text_ref(ref, path, location, ctx)


def validate_ecsv_cell_ref(ref: dict[str, Any], path: Path, location: str, ctx: ValidationContext) -> None:
    columns = ctx.columns_for_ecsv(path, f"{location}.path")
    lines = ctx.lines_for(path, f"{location}.path")
    if columns is None or lines is None:
        return

    line = ref.get("line")
    column = ref.get("column")
    raw_value = ref.get("raw_value")
    column_header = ref.get("column_header")

    if not isinstance(line, int):
        ctx.error(f"{location}.line", "expected integer ECSV file line number")
        return
    if line < 1 or line > len(lines):
        ctx.error(f"{location}.line", f"line {line} is outside file bounds 1..{len(lines)}")
        return
    if not isinstance(column, str) or not column:
        ctx.error(f"{location}.column", "expected ECSV machine column name")
        return
    if column not in columns:
        ctx.error(f"{location}.column", f"column {column!r} not found in ECSV columns {columns}")
        return
    if not isinstance(raw_value, str):
        ctx.error(f"{location}.raw_value", "expected raw ECSV cell text string")
    if not isinstance(column_header, str):
        ctx.error(f"{location}.column_header", "expected original or machine column header string")

    line_text = lines[line - 1]
    if line_text.startswith("#"):
        ctx.error(f"{location}.line", "ECSV cell reference points at metadata, not a data row")
        return
    try:
        tokens = shlex.split(line_text)
    except ValueError as exc:
        ctx.error(f"{location}.line", f"could not parse ECSV row tokens: {exc}")
        return
    if tokens == columns:
        ctx.error(f"{location}.line", "ECSV cell reference points at the header row, not a data row")
        return
    column_index = columns.index(column)
    if column_index >= len(tokens):
        ctx.error(f"{location}.line", f"row has {len(tokens)} cells but column index is {column_index + 1}")
        return
    if isinstance(raw_value, str) and tokens[column_index] != raw_value:
        ctx.error(
            f"{location}.raw_value",
            f"raw value {raw_value!r} does not match ECSV cell {tokens[column_index]!r}",
        )


def validate_text_ref(ref: dict[str, Any], path: Path, location: str, ctx: ValidationContext) -> None:
    lines = ctx.lines_for(path, f"{location}.path")
    if lines is None:
        return

    start_line = ref.get("start_line")
    end_line = ref.get("end_line")
    if not isinstance(start_line, int):
        ctx.error(f"{location}.start_line", "expected integer start line")
        return
    if not isinstance(end_line, int):
        ctx.error(f"{location}.end_line", "expected integer end line")
        return
    if start_line < 1 or end_line < start_line or end_line > len(lines):
        ctx.error(f"{location}.line_range", f"invalid line range {start_line}..{end_line} for {len(lines)} lines")


def validate_source_refs(value: Any, location: str, ctx: ValidationContext) -> None:
    refs = validate_required_list(value, location, ctx)
    if refs is None:
        return
    if not refs:
        ctx.error(location, "expected at least one source reference")
        return
    for index, ref in enumerate(refs):
        validate_source_ref(ref, f"{location}[{index}]", ctx)


def iter_quantity_records(node: Any, location: str):
    if is_dict(node):
        if "value" in node:
            yield node, location
            return
        for key, value in node.items():
            if key == "source_refs":
                continue
            yield from iter_quantity_records(value, f"{location}.{key}")
    elif is_list(node):
        for index, item in enumerate(node):
            yield from iter_quantity_records(item, f"{location}[{index}]")


def validate_quantity_records(node: Any, location: str, ctx: ValidationContext) -> None:
    for record, record_location in iter_quantity_records(node, location):
        if not is_dict(record):
            continue
        if "source_refs" not in record:
            ctx.error(record_location, "quantity record with value must include source_refs")
            continue
        validate_source_refs(record["source_refs"], f"{record_location}.source_refs", ctx)


def validate_candidate(candidate: Any, index: int, method_ids: set[str], ctx: ValidationContext) -> None:
    location = f"candidates[{index}]"
    candidate_obj = validate_required_mapping(candidate, location, ctx)
    if candidate_obj is None:
        return

    for key in ("candidate_id", "identifiers", "candidate_assessment", "core", "extra"):
        if key not in candidate_obj:
            ctx.error(f"{location}.{key}", "missing required field")

    candidate_id = candidate_obj.get("candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id:
        ctx.error(f"{location}.candidate_id", "expected non-empty string")

    assessment = candidate_obj.get("candidate_assessment")
    if is_dict(assessment):
        if not assessment.get("summary"):
            ctx.error(f"{location}.candidate_assessment.summary", "expected non-empty candidate rationale")
        validate_source_refs(
            assessment.get("source_refs"),
            f"{location}.candidate_assessment.source_refs",
            ctx,
        )
    elif assessment is not None:
        ctx.error(f"{location}.candidate_assessment", "expected an object")

    refs = candidate_obj.get("method_chain_refs", [])
    if refs is None:
        refs = []
    if not is_list(refs):
        ctx.error(f"{location}.method_chain_refs", "expected a list")
    else:
        for ref_index, ref in enumerate(refs):
            if ref not in method_ids:
                ctx.error(f"{location}.method_chain_refs[{ref_index}]", f"unknown method_chain id {ref!r}")

    core = candidate_obj.get("core")
    if core is not None:
        validate_quantity_records(core, f"{location}.core", ctx)

    extra = candidate_obj.get("extra")
    if extra is not None:
        extra_list = validate_required_list(extra, f"{location}.extra", ctx)
        if extra_list is not None:
            validate_quantity_records(extra_list, f"{location}.extra", ctx)


def validate_hvs_candidates(payload: Any, *, workspace: Path = WORKSPACE) -> list[str]:
    ctx = ValidationContext(workspace=workspace)
    root = validate_required_mapping(payload, "$", ctx)
    if root is None:
        return ctx.errors

    if root.get("schema_version") != LITERATURE_HVS_CANDIDATES_SCHEMA_VERSION:
        ctx.error("$.schema_version", f"expected {LITERATURE_HVS_CANDIDATES_SCHEMA_VERSION!r}")

    paper = root.get("paper")
    if not is_dict(paper):
        ctx.error("$.paper", "expected an object")
    elif not paper.get("arxiv_id"):
        ctx.error("$.paper.arxiv_id", "expected non-empty arXiv ID")
    else:
        bibcode = paper.get("bibcode")
        if bibcode is not None and (not isinstance(bibcode, str) or not bibcode.strip()):
            ctx.error("$.paper.bibcode", "expected non-empty string when present")

    inputs = root.get("inputs")
    if is_dict(inputs):
        for key in ("catalog_review_path", "catalog_extraction_path"):
            if key in inputs:
                path = ctx.resolve_path(inputs.get(key), f"$.inputs.{key}")
                if path is not None and not path.exists():
                    ctx.error(f"$.inputs.{key}", f"path does not exist: {path}")
    elif inputs is not None:
        ctx.error("$.inputs", "expected an object")

    extraction = root.get("extraction")
    status = None
    if not is_dict(extraction):
        ctx.error("$.extraction", "expected an object")
    else:
        status = extraction.get("status")
        if status not in LITERATURE_HVS_CANDIDATE_STATUSES:
            ctx.error("$.extraction.status", f"expected one of {sorted(LITERATURE_HVS_CANDIDATE_STATUSES)}")

    method_chain = root.get("method_chain")
    method_ids: set[str] = set()
    if not is_list(method_chain):
        ctx.error("$.method_chain", "expected a list")
    else:
        for index, step in enumerate(method_chain):
            if not is_dict(step):
                ctx.error(f"$.method_chain[{index}]", "expected an object")
                continue
            step_id = step.get("id")
            if not isinstance(step_id, str) or not step_id:
                ctx.error(f"$.method_chain[{index}].id", "expected non-empty string")
                continue
            if step_id in method_ids:
                ctx.error(f"$.method_chain[{index}].id", f"duplicate method_chain id {step_id!r}")
            method_ids.add(step_id)
            if "source_refs" in step:
                validate_source_refs(step["source_refs"], f"$.method_chain[{index}].source_refs", ctx)

    candidates = root.get("candidates")
    if not is_list(candidates):
        ctx.error("$.candidates", "expected a list")
    else:
        if status == "no_candidates" and candidates:
            ctx.error("$.candidates", "must be empty when extraction.status is no_candidates")
        if status == "candidates_found" and not candidates:
            ctx.error("$.candidates", "must contain at least one candidate when extraction.status is candidates_found")
        for index, candidate in enumerate(candidates):
            validate_candidate(candidate, index, method_ids, ctx)

    if "candidate_groups_considered" in root:
        groups = validate_required_list(root["candidate_groups_considered"], "$.candidate_groups_considered", ctx)
        if groups is not None:
            for index, group in enumerate(groups):
                if is_dict(group) and "source_refs" in group:
                    validate_source_refs(group["source_refs"], f"$.candidate_groups_considered[{index}].source_refs", ctx)

    return ctx.errors


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate literature_hvs_candidates.json files.")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--path", type=Path, help="Path to one literature_hvs_candidates.json file.")
    selection.add_argument("--arxiv-id", help="Validate literature/<arxiv-id>/literature_hvs_candidates.json.")
    parser.add_argument("--literature-dir", type=Path, default=WORKSPACE / "literature")
    parser.add_argument(
        "--workspace",
        type=Path,
        default=WORKSPACE,
        help="Workspace root used to resolve relative provenance paths.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    workspace = args.workspace.expanduser()
    if args.path:
        path = args.path.expanduser()
    else:
        path = args.literature_dir.expanduser() / str(args.arxiv_id) / "literature_hvs_candidates.json"

    if not path.exists():
        print(f"missing candidate extraction JSON: {path}", file=sys.stderr)
        return 1

    try:
        payload = load_json(path)
    except json.JSONDecodeError as exc:
        print(f"invalid JSON: {exc}", file=sys.stderr)
        return 1

    errors = validate_hvs_candidates(payload, workspace=workspace)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print(f"OK: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
