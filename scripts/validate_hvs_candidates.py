#!/usr/bin/env python3
"""Validate Stella per-paper HVS candidate extraction JSON files."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any

from astropy.io import ascii
from pydantic import ValidationError


WORKSPACE = Path(__file__).resolve().parents[1]
SRC = WORKSPACE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from high_velocity_lit.hvs_candidates_index import write_hvs_candidates_index_outputs  # noqa: E402
from high_velocity_lit.schema_specs import (  # noqa: E402
    LITERATURE_HVS_CANDIDATE_ASSESSMENT_STATUSES,
    LITERATURE_HVS_CANDIDATE_ORIGIN_TYPES,
    LITERATURE_HVS_CANDIDATE_STATUSES,
    LITERATURE_HVS_CANDIDATES_SCHEMA_VERSION,
)
from high_velocity_lit.schema_models import LiteratureHvsCandidatesRecord  # noqa: E402


LATEX_RESIDUE_RE = re.compile(r"(\\[A-Za-z]+|[{}$]|[\^_]|\+/-|\u00b1)")
SYMMETRIC_UNCERTAINTY_RE = re.compile(r"(\+/-|\u00b1|\\pm)")
ASYMMETRIC_UNCERTAINTY_RE = re.compile(
    r"(\^\s*\{?\s*\+[^}_\s]+\}?\s*_\s*\{?\s*-[^}\s]+|"
    r"_\s*\{?\s*-[^}^\s]+\}?\s*\^\s*\{?\s*\+[^}\s]+)"
)
CORE_GROUPS = ("observed_phase_space", "derived_kinematics", "probabilities")
NO_CANDIDATE_REVIEW_RE = re.compile(
    r"(classif\w+(?:\s+\w+){0,3}\s+as\s+HVSs?|HVS\s+status|"
    r"gravitationally\s+unbound|positive\s+(?:total\s+)?energ(?:y|ies))",
    re.IGNORECASE,
)
CANDIDATE_BOUND_CONFLICT_RE = re.compile(
    r"(\bbound\s+to\s+the\s+Galaxy|\bcurrently\s+bound|\bbound\s+trajectory|"
    r"remains?\s+Galaxy[- ]bound)",
    re.IGNORECASE,
)
WEAK_MATCH_STOPWORDS = {
    "and",
    "are",
    "caption",
    "context",
    "data",
    "description",
    "field",
    "fields",
    "for",
    "from",
    "line",
    "lines",
    "object",
    "objects",
    "paper",
    "reference",
    "references",
    "section",
    "source",
    "table",
    "text",
    "that",
    "the",
    "this",
    "value",
    "values",
    "were",
    "with",
}


class ValidationReport:
    def __init__(self, *, errors: list[str], warnings: list[str]) -> None:
        self.errors = errors
        self.warnings = warnings


class ValidationContext:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.ecsv_columns: dict[Path, list[str]] = {}
        self.file_lines: dict[Path, list[str]] = {}

    def error(self, location: str, message: str) -> None:
        self.errors.append(f"{location}: {message}")

    def warn(self, location: str, message: str) -> None:
        self.warnings.append(f"{location}: {message}")

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
        return

    selected_lines = lines[start_line - 1 : end_line]
    if not any(is_substantive_text_line(line) for line in selected_lines):
        ctx.error(f"{location}.line_range", "text reference points only at blank or comment lines")
        return

    warn_if_weak_text_match(
        selected_lines,
        f"{location}.context",
        [ref.get("context")],
        ctx,
    )


def validate_source_refs(value: Any, location: str, ctx: ValidationContext) -> None:
    refs = validate_required_list(value, location, ctx)
    if refs is None:
        return
    if not refs:
        ctx.error(location, "expected at least one source reference")
        return
    for index, ref in enumerate(refs):
        validate_source_ref(ref, f"{location}[{index}]", ctx)


def ref_path_suffix(ref: Any) -> str:
    if not is_dict(ref):
        return ""
    path = ref.get("path")
    if not isinstance(path, str):
        return ""
    return Path(path).suffix.lower()


def is_ecsv_source_ref(ref: Any) -> bool:
    if not is_dict(ref):
        return False
    path = ref.get("path")
    kind = ref.get("kind")
    return kind == "ecsv_cell" or (isinstance(path, str) and path.lower().endswith(".ecsv"))


def is_paper_text_source_ref(ref: Any) -> bool:
    if not is_dict(ref):
        return False
    if ref.get("kind") != "text":
        return False
    suffix = ref_path_suffix(ref)
    return suffix not in {".ecsv", ".json", ".bib", ".bbl"}


def has_paper_text_source_ref(value: Any) -> bool:
    return is_list(value) and any(is_paper_text_source_ref(ref) for ref in value)


def has_bibliography_source_ref(value: Any) -> bool:
    return is_list(value) and any(ref_path_suffix(ref) in {".bib", ".bbl"} for ref in value)


def validate_clean_machine_string(value: Any, location: str, ctx: ValidationContext) -> None:
    if not isinstance(value, str):
        ctx.error(location, "expected machine-readable string")
        return
    if LATEX_RESIDUE_RE.search(value):
        ctx.error(location, "contains LaTeX residue; keep it in raw_value and store a cleaned machine value here")


def is_substantive_text_line(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith(("%", "#"))


def has_non_empty_value(record: dict[str, Any], key: str) -> bool:
    value = record.get(key)
    return value not in (None, "")


def weak_match_terms(value: Any) -> set[str]:
    if not isinstance(value, str):
        return set()
    normalized = re.sub(r"\\[A-Za-z]+", " ", value.lower())
    terms = set()
    for token in re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", normalized):
        if token in WEAK_MATCH_STOPWORDS:
            continue
        if len(token) < 3 and not any(char.isdigit() for char in token):
            continue
        terms.add(token)
    return terms


def warn_if_weak_text_match(
    lines: list[str],
    location: str,
    needle_values: list[Any],
    ctx: ValidationContext,
) -> None:
    needle_terms: set[str] = set()
    for value in needle_values:
        needle_terms.update(weak_match_terms(value))
    if not needle_terms:
        return

    text = "\n".join(lines)
    text_terms = weak_match_terms(text)
    text_lower = text.lower()
    if any(term in text_terms or term in text_lower for term in needle_terms):
        return
    ctx.warn(location, "source reference context/value has no weak lexical overlap with referenced text")


def text_for_source_ref(ref: Any, ctx: ValidationContext) -> str:
    if not is_dict(ref) or is_ecsv_source_ref(ref):
        return ""
    path_value = ref.get("path")
    if not isinstance(path_value, str) or not path_value:
        return ""
    path = Path(path_value)
    if not path.is_absolute():
        path = ctx.workspace / path
    lines = ctx.file_lines.get(path)
    if lines is None:
        if not path.exists() or not path.is_file():
            return ""
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            return ""
        ctx.file_lines[path] = lines

    start_line = ref.get("start_line")
    end_line = ref.get("end_line")
    if not isinstance(start_line, int) or not isinstance(end_line, int):
        return ""
    if start_line < 1 or end_line < start_line or end_line > len(lines):
        return ""
    return "\n".join(lines[start_line - 1 : end_line])


def texts_for_source_refs(refs: Any, ctx: ValidationContext) -> list[str]:
    if not is_list(refs):
        return []
    return [text for ref in refs if (text := text_for_source_ref(ref, ctx))]


def validate_uncertainty_fields(record: dict[str, Any], raw_value: str, location: str, ctx: ValidationContext) -> None:
    if ASYMMETRIC_UNCERTAINTY_RE.search(raw_value):
        if not has_non_empty_value(record, "lower_error"):
            ctx.error(f"{location}.lower_error", "asymmetric raw_value must include lower_error")
        if not has_non_empty_value(record, "upper_error"):
            ctx.error(f"{location}.upper_error", "asymmetric raw_value must include upper_error")
    elif SYMMETRIC_UNCERTAINTY_RE.search(raw_value) and not has_non_empty_value(record, "error"):
        ctx.error(f"{location}.error", "symmetric raw_value must include error")


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
        validate_clean_machine_string(record.get("value"), f"{record_location}.value", ctx)
        raw_value = record.get("raw_value")
        if not isinstance(raw_value, str):
            ctx.error(f"{record_location}.raw_value", "quantity record with value must include raw_value")
        else:
            validate_uncertainty_fields(record, raw_value, record_location, ctx)
        for key in ("error", "lower_error", "upper_error"):
            if key in record and record.get(key) not in (None, ""):
                validate_clean_machine_string(record.get(key), f"{record_location}.{key}", ctx)
        if "source_refs" not in record:
            ctx.error(record_location, "quantity record with value must include source_refs")
            continue
        validate_source_refs(record["source_refs"], f"{record_location}.source_refs", ctx)
        refs = record.get("source_refs")
        if isinstance(raw_value, str) and isinstance(refs, list):
            for ref_index, ref in enumerate(refs):
                if is_ecsv_source_ref(ref):
                    ref_raw_value = ref.get("raw_value") if is_dict(ref) else None
                    if ref_raw_value != raw_value:
                        ctx.error(
                            f"{record_location}.source_refs[{ref_index}].raw_value",
                            "ECSV source raw_value must match the quantity record raw_value",
                        )
                else:
                    ref_text = text_for_source_ref(ref, ctx)
                    if ref_text:
                        warn_if_weak_text_match(
                            ref_text.splitlines(),
                            f"{record_location}.source_refs[{ref_index}]",
                            [ref.get("context") if is_dict(ref) else None, raw_value, record.get("value")],
                            ctx,
                        )


def validate_candidate_origin(origin: Any, location: str, ctx: ValidationContext) -> str | None:
    origin_obj = validate_required_mapping(origin, location, ctx)
    if origin_obj is None:
        return None

    origin_type = origin_obj.get("origin_type")
    if origin_type not in LITERATURE_HVS_CANDIDATE_ORIGIN_TYPES:
        ctx.error(
            f"{location}.origin_type",
            f"expected one of {sorted(LITERATURE_HVS_CANDIDATE_ORIGIN_TYPES)}",
        )
    if not isinstance(origin_obj.get("paper_reassesses_unbound_status"), bool):
        ctx.error(f"{location}.paper_reassesses_unbound_status", "expected boolean")

    source_refs = origin_obj.get("source_refs")
    validate_source_refs(source_refs, f"{location}.source_refs", ctx)
    if not has_paper_text_source_ref(source_refs):
        ctx.error(f"{location}.source_refs", "expected at least one paper text reference for origin evidence")

    citation = origin_obj.get("citation")
    if origin_type == "cited_from_literature":
        citation_obj = validate_required_mapping(citation, f"{location}.citation", ctx)
        if citation_obj is not None:
            if not isinstance(citation_obj.get("bibkey"), str) or not citation_obj.get("bibkey"):
                ctx.error(f"{location}.citation.bibkey", "expected non-empty bibkey for cited candidates")
            citation_refs = citation_obj.get("source_refs")
            validate_source_refs(citation_refs, f"{location}.citation.source_refs", ctx)
            if not has_paper_text_source_ref(citation_refs):
                ctx.error(
                    f"{location}.citation.source_refs",
                    "expected at least one paper text citation reference",
                )
            if not has_bibliography_source_ref(citation_refs):
                ctx.error(
                    f"{location}.citation.source_refs",
                    "expected at least one .bib or .bbl bibliography entry reference",
                )
    elif citation is not None:
        citation_obj = validate_required_mapping(citation, f"{location}.citation", ctx)
        if citation_obj is not None and "source_refs" in citation_obj:
            validate_source_refs(citation_obj["source_refs"], f"{location}.citation.source_refs", ctx)

    return origin_type if isinstance(origin_type, str) else None


def validate_candidate(candidate: Any, index: int, method_ids: set[str], ctx: ValidationContext) -> None:
    location = f"candidates[{index}]"
    candidate_obj = validate_required_mapping(candidate, location, ctx)
    if candidate_obj is None:
        return

    for key in (
        "candidate_id",
        "identifiers",
        "candidate_assessment",
        "candidate_origin",
        "method_chain_refs",
        "core",
        "extra",
    ):
        if key not in candidate_obj:
            ctx.error(f"{location}.{key}", "missing required field")

    candidate_id = candidate_obj.get("candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id:
        ctx.error(f"{location}.candidate_id", "expected non-empty string")

    identifiers = candidate_obj.get("identifiers")
    if not is_dict(identifiers):
        ctx.error(f"{location}.identifiers", "expected an object")
    elif not isinstance(identifiers.get("primary"), str) or not identifiers.get("primary").strip():
        ctx.error(f"{location}.identifiers.primary", "expected non-empty primary identifier")

    assessment = candidate_obj.get("candidate_assessment")
    if is_dict(assessment):
        if not assessment.get("summary"):
            ctx.error(f"{location}.candidate_assessment.summary", "expected non-empty candidate rationale")
        candidate_status = assessment.get("candidate_status")
        if candidate_status not in LITERATURE_HVS_CANDIDATE_ASSESSMENT_STATUSES:
            ctx.error(
                f"{location}.candidate_assessment.candidate_status",
                f"expected one of {sorted(LITERATURE_HVS_CANDIDATE_ASSESSMENT_STATUSES)}",
            )
        assessment_refs = assessment.get("source_refs")
        validate_source_refs(
            assessment_refs,
            f"{location}.candidate_assessment.source_refs",
            ctx,
        )
        if not has_paper_text_source_ref(assessment_refs):
            ctx.error(
                f"{location}.candidate_assessment.source_refs",
                "expected at least one paper text reference for Galactic-unbound candidate evidence",
            )
    else:
        ctx.error(f"{location}.candidate_assessment", "expected an object")

    origin_type = validate_candidate_origin(
        candidate_obj.get("candidate_origin"),
        f"{location}.candidate_origin",
        ctx,
    )
    warn_if_candidate_bound_conflict(candidate_obj, location, ctx)

    refs = candidate_obj.get("method_chain_refs", [])
    if refs is None:
        refs = []
    if not is_list(refs):
        ctx.error(f"{location}.method_chain_refs", "expected a list")
    else:
        if origin_type == "introduced_by_this_paper" and not refs:
            ctx.error(
                f"{location}.method_chain_refs",
                "introduced_by_this_paper candidates must reference at least one method_chain step",
            )
        for ref_index, ref in enumerate(refs):
            if ref not in method_ids:
                ctx.error(f"{location}.method_chain_refs[{ref_index}]", f"unknown method_chain id {ref!r}")

    core = candidate_obj.get("core")
    if is_dict(core):
        validate_core(core, f"{location}.core", ctx)
    else:
        ctx.error(f"{location}.core", "expected an object")

    extra = candidate_obj.get("extra")
    extra_list = validate_required_list(extra, f"{location}.extra", ctx)
    if extra_list is not None:
        validate_quantity_records(extra_list, f"{location}.extra", ctx)


def validate_core(core: dict[str, Any], location: str, ctx: ValidationContext) -> None:
    allowed = set(CORE_GROUPS)
    unexpected = sorted(set(core) - allowed)
    for key in unexpected:
        ctx.error(f"{location}.{key}", f"unexpected core group; expected only {list(CORE_GROUPS)}")
    for group in CORE_GROUPS:
        value = core.get(group)
        if not is_dict(value):
            ctx.error(f"{location}.{group}", "expected core schema group object")
    validate_quantity_records(core, location, ctx)


def warn_if_candidate_bound_conflict(candidate_obj: dict[str, Any], location: str, ctx: ValidationContext) -> None:
    texts: list[str] = []
    assessment = candidate_obj.get("candidate_assessment")
    if is_dict(assessment):
        summary = assessment.get("summary")
        if isinstance(summary, str):
            texts.append(summary)
        texts.extend(texts_for_source_refs(assessment.get("source_refs"), ctx))

    origin = candidate_obj.get("candidate_origin")
    if is_dict(origin):
        texts.extend(texts_for_source_refs(origin.get("source_refs"), ctx))

    for text in texts:
        match = CANDIDATE_BOUND_CONFLICT_RE.search(text)
        if match:
            ctx.warn(
                location,
                f"candidate evidence contains bound-status phrase {match.group(0)!r}; review inclusion boundary",
            )
            return


def validate_candidate_groups_considered(groups_value: Any, status: str | None, ctx: ValidationContext) -> None:
    if groups_value is None:
        if status == "no_candidates":
            ctx.error("$.candidate_groups_considered", "required when extraction.status is no_candidates")
        return

    groups = validate_required_list(groups_value, "$.candidate_groups_considered", ctx)
    if groups is None:
        return
    if status == "no_candidates" and not groups:
        ctx.error("$.candidate_groups_considered", "must be non-empty when extraction.status is no_candidates")
        return

    for index, group in enumerate(groups):
        location = f"$.candidate_groups_considered[{index}]"
        if not is_dict(group):
            ctx.error(location, "expected an object")
            continue
        if status == "no_candidates" and "source_refs" not in group:
            ctx.error(f"{location}.source_refs", "required when extraction.status is no_candidates")
            continue
        if "source_refs" in group:
            validate_source_refs(group["source_refs"], f"{location}.source_refs", ctx)
        warn_if_no_candidate_group_needs_review(group, location, ctx)


def warn_if_no_candidate_group_needs_review(group: dict[str, Any], location: str, ctx: ValidationContext) -> None:
    texts: list[str] = []
    for key in ("description", "reason", "decision"):
        value = group.get(key)
        if isinstance(value, str):
            texts.append(value)
    texts.extend(texts_for_source_refs(group.get("source_refs"), ctx))

    for text in texts:
        match = NO_CANDIDATE_REVIEW_RE.search(text)
        if match:
            ctx.warn(
                location,
                f"no_candidates group contains candidate-like phrase {match.group(0)!r}; review extraction.status",
            )
            return


def validate_completion_state(root: dict[str, Any], status: str | None, ctx: ValidationContext) -> None:
    extraction = root.get("extraction")
    if status == "needs_review":
        ctx.error("$.extraction.status", "expected a completed status, not 'needs_review'")
    if is_dict(extraction) and status != "source_missing" and not str(extraction.get("summary") or "").strip():
        ctx.error("$.extraction.summary", "expected a non-empty completion summary")


def validate_hvs_candidates_report(
    payload: Any,
    *,
    workspace: Path = WORKSPACE,
    require_complete: bool = False,
) -> ValidationReport:
    ctx = ValidationContext(workspace=workspace)
    root = validate_required_mapping(payload, "$", ctx)
    if root is None:
        return ValidationReport(errors=ctx.errors, warnings=ctx.warnings)
    try:
        LiteratureHvsCandidatesRecord.model_validate(payload)
    except ValidationError as exc:
        for error in exc.errors():
            path = ".".join(str(part) for part in error["loc"])
            location = f"$.{path}" if path else "$"
            ctx.error(location, error["msg"])

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

    validate_candidate_groups_considered(root.get("candidate_groups_considered"), status, ctx)

    if require_complete:
        validate_completion_state(root, status, ctx)

    return ValidationReport(errors=ctx.errors, warnings=ctx.warnings)


def validate_hvs_candidates(
    payload: Any,
    *,
    workspace: Path = WORKSPACE,
    require_complete: bool = False,
) -> list[str]:
    return validate_hvs_candidates_report(
        payload,
        workspace=workspace,
        require_complete=require_complete,
    ).errors


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
    parser.add_argument(
        "--rebuild-index",
        action="store_true",
        help="Rebuild the global HVS candidates index after successful validation.",
    )
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Fail if the file is still an unfilled needs_review skeleton.",
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

    report = validate_hvs_candidates_report(
        payload,
        workspace=workspace,
        require_complete=args.require_complete,
    )
    for warning in report.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    if report.errors:
        for error in report.errors:
            print(error, file=sys.stderr)
        return 1

    print(f"OK: {path}")

    if args.rebuild_index:
        literature_dir = args.literature_dir.expanduser()
        result = write_hvs_candidates_index_outputs(literature_dir, workspace=workspace)
        summary = result["index_record"]["summary"]
        print(
            "Rebuilt HVS candidates index: "
            f"{summary['paper_count']} papers, "
            f"{summary['total_candidate_count']} total candidates."
        )
        print(result["index_json_path"])
        print(result["index_markdown_path"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
