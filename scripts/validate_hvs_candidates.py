#!/usr/bin/env python3
"""Validate Stella per-paper HVS candidate extraction JSON files."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from astropy.io import ascii
from pydantic import ValidationError


WORKSPACE = Path(__file__).resolve().parents[1]
SRC = WORKSPACE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from high_velocity_lit.hvs_candidates_index import (  # noqa: E402
    iter_hvs_candidates_paths,
    write_hvs_candidates_index_outputs,
)
from high_velocity_lit.hvs_method_provenance import (  # noqa: E402
    REPORTED_VALUE_STEP_TYPE,
    allowed_direct_step_types,
    categories_have_compatible_direct_types,
    classify_quantity_record,
    coarse_step_warnings,
    lineage_for_step,
    required_lineage_step_type_groups,
)
from high_velocity_lit.schema_specs import (  # noqa: E402
    LITERATURE_HVS_EXTRACTION_CONFIDENCE,
    LITERATURE_HVS_EXTRACTION_STATUSES,
    LITERATURE_HVS_GALACTIC_BOUND_CLAIMS,
    LITERATURE_HVS_INCLUSION_BASES,
    LITERATURE_HVS_CANDIDATE_ORIGIN_TYPES,
    LITERATURE_HVS_CANDIDATES_SCHEMA_VERSION,
    LITERATURE_HVS_METHOD_STEP_TYPES,
    LITERATURE_HVS_PAPER_LABELS,
)
from high_velocity_lit.schema_models import LiteratureHvsCandidatesRecord  # noqa: E402


LATEX_RESIDUE_RE = re.compile(r"(\\[A-Za-z]+|[{}$]|[\^_]|\+/-|\u00b1)")
MACHINE_NUMBER_RE = re.compile(r"^[+-]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:[eE][+-]?\d+)?$")
PAGE_MARKER_RE = re.compile(r"^---\s*Page\s+\d+\s*---$", re.IGNORECASE)
LATEX_STRUCTURE_ONLY_RE = re.compile(
    r"^\\(?:"
    r"section|subsection|subsubsection|paragraph|chapter|part|"
    r"begin|end|maketitle|keywords|label|bibliography|bibliographystyle"
    r")\*?(?:\[[^\]]*\])?(?:\{[^{}]*\})?\s*$"
)
LATEX_PREAMBLE_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\s*=\s*[^,]+,?\s*$")
SYMMETRIC_UNCERTAINTY_RE = re.compile(r"(\+/-|\u00b1|\\pm)")
ASYMMETRIC_UNCERTAINTY_RE = re.compile(
    r"(\^\s*\{?\s*\+[^}_\s]+\}?\s*_\s*\{?\s*-[^}\s]+|"
    r"_\s*\{?\s*-[^}^\s]+\}?\s*\^\s*\{?\s*\+[^}\s]+)"
)
CORE_GROUPS = ("observed_phase_space", "derived_kinematics", "bound_assessment")
CORE_OBSERVED_NUMERIC_FIELDS = {"distance", "parallax", "proper_motion_ra", "proper_motion_dec", "radial_velocity"}
MACHINE_NUMERIC_FIELDS = ("value", "error", "lower_error", "upper_error")
COORDINATE_FIELDS = {"ra", "dec"}
COORDINATE_FORMATS = {"decimal_degrees", "sexagesimal_hms", "sexagesimal_dms", "sexagesimal_colon"}
COORDINATE_CONTEXT_KEYS = {"reference_frame", "epoch"}
COORDINATE_CONTEXT_RE = re.compile(r"\b(?:ICRS|FK[45]|J\d{4}(?:\.\d+)?|epoch|equinox)\b", re.IGNORECASE)
COORDINATE_DECIMAL_UNITS = {"deg", "degree", "degrees"}
COORDINATE_HOURANGLE_UNITS = {"hourangle"}
SEXAGESIMAL_HMS_RE = re.compile(r"^[+-]?\d{1,2}h\d{1,2}m\d{1,2}(?:\.\d+)?s?$")
SEXAGESIMAL_DMS_RE = re.compile(r"^[+-]?\d{1,3}(?:d|°)\d{1,2}(?:m|')\d{1,2}(?:\.\d+)?(?:s|\")?$")
SEXAGESIMAL_COLON_RE = re.compile(r"^[+-]?\d{1,3}:\d{1,2}:\d{1,2}(?:\.\d+)?$")
EPOCH_KIND_VALUES = {"reference_epoch", "equinox", "ambiguous", "not_reported"}
UNKNOWN_CONTEXT_VALUES = {"", "unknown"}
METHOD_STEP_ID_RE = re.compile(r"^step-\d{2}$")
GAIA_SOURCE_ID_RE = re.compile(r"^Gaia (?:DR[0-9]+|EDR[0-9]+) [0-9]+$")
NO_CANDIDATE_REVIEW_RE = re.compile(
    r"(classif\w+(?:\s+\w+){0,3}\s+as\s+HVSs?|HVS\s+status|"
    r"gravitationally\s+unbound|positive\s+(?:total\s+)?energ(?:y|ies))",
    re.IGNORECASE,
)
NO_CANDIDATE_NEGATION_RE = re.compile(
    r"(\b(?:does|do|did)\s+not\b|\bnot\b|\bno\b|\bwithout\b)"
    r".{0,120}\b(?:HVS|hypervelocity|unbound|escaping|positive\s+(?:total\s+)?energ(?:y|ies))\b|"
    r"\b(?:HVS|hypervelocity|unbound|escaping|positive\s+(?:total\s+)?energ(?:y|ies))\b"
    r".{0,120}(\b(?:does|do|did)\s+not\b|\bnot\b|\bno\b|\bwithout\b)",
    re.IGNORECASE,
)
CANDIDATE_BOUND_CONFLICT_RE = re.compile(
    r"(\bbound\s+to\s+the\s+Galaxy|\bcurrently\s+bound|\bbound\s+trajectory|"
    r"remains?\s+Galaxy[- ]bound)",
    re.IGNORECASE,
)
LEGACY_CANDIDATE_FIELDS = ("candidate_id",)
LEGACY_IDENTIFIER_FIELDS = (
    "primary",
    "paper_id",
    "gaia_dr2_source_id",
    "gaia_edr3_source_id",
    "gaia_dr3_source_id",
    "aliases",
)
QUANTITATIVE_EXTRA_RE = re.compile(
    r"(velocity|speed|distance|parallax|proper[_ -]?motion|radial[_ -]?velocity|"
    r"escape|energy|eccentricity|mass|age|magnitude|luminosity|temperature|teff|"
    r"log[_ -]?g|metallicity|\[?fe/h\]?|probability|ratio|angular[_ -]?momentum|"
    r"\blz\b|transit|count|period|time[_ -]?of[_ -]?flight|flight[_ -]?time|"
    r"ruwe|gof|chi|signal[_ -]?to[_ -]?noise|\bs/?n\b|snr)",
    re.IGNORECASE,
)
STANDARD_EXTRA_RE = re.compile(
    r"(probab|p[_ -]?(?:esc|ub|unbound|bound|mw|lmc)|likelihood|photometr|magnitude|colour|color|"
    r"spectr|abundance|\[?[a-z]{1,2}/h\]?|orbit|eccentricity|pericentre|pericenter|"
    r"apocentre|apocenter|origin|ejection|flight[_ -]?time|disk[_ -]?cross|"
    r"ruwe|quality|flag|teff|log[_ -]?g|metallicity|mass|luminosity)",
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


CANDIDATE_LOCATION_RE = re.compile(r"candidates\[(\d+)\]")


def compact_integer_ranges(values: list[int]) -> str:
    if not values:
        return ""
    ranges: list[str] = []
    start = previous = values[0]
    for value in values[1:]:
        if value == previous + 1:
            previous = value
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = value
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(ranges)


def grouped_warning_lines(warnings: list[str]) -> list[str]:
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    ordered_keys: list[tuple[str, str]] = []
    for warning in warnings:
        location, separator, message = warning.partition(": ")
        if not separator:
            location = warning
            message = ""
        candidate_indexes = [int(match.group(1)) for match in CANDIDATE_LOCATION_RE.finditer(location)]
        normalized_location = CANDIDATE_LOCATION_RE.sub("candidates[]", location)
        key = (normalized_location, message)
        if key not in groups:
            groups[key] = {
                "location": location,
                "message": message,
                "candidate_indexes": [],
                "count": 0,
            }
            ordered_keys.append(key)
        groups[key]["count"] += 1
        groups[key]["candidate_indexes"].extend(candidate_indexes)

    lines: list[str] = []
    for key in ordered_keys:
        group = groups[key]
        count = int(group["count"])
        location = str(group["location"])
        message = str(group["message"])
        if count == 1:
            lines.append(f"{location}: {message}" if message else location)
            continue
        indexes = sorted(set(group["candidate_indexes"]))
        if indexes:
            compact_indexes = compact_integer_ranges(indexes)
            location = CANDIDATE_LOCATION_RE.sub(f"candidates[{compact_indexes}]", location, count=1)
        prefix = f"{location}: " if message else f"{location} "
        lines.append(f"{prefix}{count} occurrences: {message}" if message else f"{location}: {count} occurrences")
    return lines


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
    suffix = path.suffix.lower()
    if kind == "ecsv_cell":
        if suffix != ".ecsv":
            ctx.error(f"{location}.path", "ecsv_cell source references must point to .ecsv files")
            return
        validate_ecsv_cell_ref(ref, path, location, ctx)
        return
    if suffix == ".ecsv":
        ctx.error(f"{location}.kind", "ECSV paths must use kind 'ecsv_cell'")
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
    component_raw_value = ref.get("component_raw_value")

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
    if "component_raw_value" in ref:
        if not isinstance(component_raw_value, str) or not component_raw_value.strip():
            ctx.error(f"{location}.component_raw_value", "expected non-empty component text when present")
        elif isinstance(raw_value, str) and component_raw_value not in raw_value:
            ctx.error(
                f"{location}.component_raw_value",
                f"component value {component_raw_value!r} is not present in ECSV cell {raw_value!r}",
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


def validate_paper_text_evidence(value: Any, location: str, ctx: ValidationContext, message: str) -> None:
    if not has_paper_text_source_ref(value):
        ctx.error(location, message)
    if not is_list(value):
        return
    for index, ref in enumerate(value):
        if not is_dict(ref):
            continue
        suffix = ref_path_suffix(ref)
        if suffix in {".json", ".bib", ".bbl", ".ecsv"}:
            ctx.error(
                f"{location}[{index}].path",
                "scientific evidence source_refs must cite paper text, not metadata, bibliography, or ECSV-only sources",
            )


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


def all_refs_have_suffix(value: Any, suffixes: set[str]) -> bool:
    return is_list(value) and all(is_dict(ref) and ref_path_suffix(ref) in suffixes for ref in value)


def bibliography_text_for_refs(refs: Any, ctx: ValidationContext) -> str:
    if not is_list(refs):
        return ""
    return "\n".join(text_for_source_ref(ref, ctx) for ref in refs if is_dict(ref) and ref_path_suffix(ref) in {".bib", ".bbl"})


def compact_bibliography_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def bibkey_supported_by_bibliography(bibkey: str, bibliography_text: str) -> bool:
    escaped = re.escape(bibkey)
    return bool(
        re.search(rf"@\w+\s*\{{\s*{escaped}\s*,", bibliography_text)
        or re.search(rf"\\bibitem(?:\[[^\]]*\])?\s*\{{\s*{escaped}\s*\}}", bibliography_text)
    )


def bibliography_field_supported(value: str, bibliography_text: str) -> bool:
    terms = weak_match_terms(value)
    if terms:
        bibliography_terms = weak_match_terms(bibliography_text)
        return terms.issubset(bibliography_terms)
    compact_value = compact_bibliography_text(value)
    if not compact_value:
        return True
    return compact_value in compact_bibliography_text(bibliography_text)


def citation_has_structured_fields(citation_obj: dict[str, Any]) -> bool:
    for field in ("bibkey", "year", "title", "doi", "bibcode", "arxiv_id"):
        value = citation_obj.get(field)
        if isinstance(value, str) and value.strip():
            return True
    authors = citation_obj.get("authors")
    return is_list(authors) and any(isinstance(author, str) and author.strip() for author in authors)


def validate_citation_bibliography_fields(citation_obj: dict[str, Any], location: str, ctx: ValidationContext) -> None:
    bibliography_refs = citation_obj.get("bibliography_refs")
    bibliography_text = bibliography_text_for_refs(bibliography_refs, ctx)
    if citation_has_structured_fields(citation_obj) and not bibliography_text.strip():
        ctx.error(
            f"{location}.bibliography_refs",
            "structured citation fields require readable .bib or .bbl bibliography source refs",
        )
        return

    bibkey = citation_obj.get("bibkey")
    if isinstance(bibkey, str) and bibkey.strip() and bibliography_text:
        if not bibkey_supported_by_bibliography(bibkey.strip(), bibliography_text):
            ctx.error(f"{location}.bibkey", "bibkey must match a .bib or .bbl bibliography entry key")

    authors = citation_obj.get("authors")
    if is_list(authors) and bibliography_text:
        for author_index, author in enumerate(authors):
            if not isinstance(author, str) or not author.strip():
                ctx.error(f"{location}.authors[{author_index}]", "expected non-empty author string")
                continue
            if not bibliography_field_supported(author, bibliography_text):
                ctx.error(
                    f"{location}.authors[{author_index}]",
                    "citation author must be supported by bibliography source refs",
                )

    for field in ("year", "title", "doi", "bibcode", "arxiv_id"):
        value = citation_obj.get(field)
        if value in (None, ""):
            continue
        if not isinstance(value, str):
            ctx.error(f"{location}.{field}", "expected string")
            continue
        if bibliography_text and not bibliography_field_supported(value, bibliography_text):
            ctx.error(f"{location}.{field}", "citation field must be supported by bibliography source refs")


def validate_citation_refs_and_fields(
    citation_obj: dict[str, Any],
    location: str,
    ctx: ValidationContext,
    *,
    require_context_refs: bool,
    require_bibliography_refs: bool,
) -> None:
    if "source_refs" in citation_obj:
        ctx.error(f"{location}.source_refs", "legacy citation.source_refs is removed in v7")

    context_refs = citation_obj.get("citation_context_refs")
    bibliography_refs = citation_obj.get("bibliography_refs")

    if context_refs is not None or require_context_refs:
        validate_source_refs(context_refs, f"{location}.citation_context_refs", ctx)
        if not has_paper_text_source_ref(context_refs):
            ctx.error(
                f"{location}.citation_context_refs",
                "expected at least one paper text citation reference",
            )

    if bibliography_refs is not None or require_bibliography_refs or citation_has_structured_fields(citation_obj):
        validate_source_refs(bibliography_refs, f"{location}.bibliography_refs", ctx)
        if not has_bibliography_source_ref(bibliography_refs):
            ctx.error(
                f"{location}.bibliography_refs",
                "expected at least one .bib or .bbl bibliography entry reference",
            )
        elif not all_refs_have_suffix(bibliography_refs, {".bib", ".bbl"}):
            ctx.error(
                f"{location}.bibliography_refs",
                "bibliography_refs may only contain .bib or .bbl entries",
            )
        validate_citation_bibliography_fields(citation_obj, location, ctx)


def validate_clean_machine_string(value: Any, location: str, ctx: ValidationContext) -> None:
    if not isinstance(value, str):
        ctx.error(location, "expected machine-readable string")
        return
    if LATEX_RESIDUE_RE.search(value):
        ctx.error(location, "contains LaTeX residue; keep it in raw_value and store a cleaned machine value here")


def field_name_from_location(location: str) -> str:
    normalized = re.sub(r"\[\d+\]", "", location)
    return normalized.rsplit(".", 1)[-1]


def quantity_requires_numeric_machine_fields(record: dict[str, Any], location: str) -> bool:
    field_name = field_name_from_location(location)
    if ".core.derived_kinematics." in location or ".core.bound_assessment." in location:
        return True
    if ".core.observed_phase_space." in location:
        return field_name in CORE_OBSERVED_NUMERIC_FIELDS
    if ".photometry[" in location or ".abundances[" in location or ".orbit." in location:
        return True
    if ".stellar_parameters." in location:
        return field_name != "spectral_type"
    if ".astrophysical_origin.hypothesis_metrics[" in location:
        return record.get("metric_type") != "classification"
    if ".astrophysical_origin." in location:
        return field_name not in {"origin_site", "origin_classification"}
    if ".extra[" not in location:
        return False

    unit = record.get("unit")
    if isinstance(unit, str) and unit.strip():
        return True
    searchable = " ".join(
        value
        for key in ("name", "kind", "description")
        if isinstance((value := record.get(key)), str)
    )
    return bool(QUANTITATIVE_EXTRA_RE.search(searchable))


def warn_if_non_numeric_machine_fields(record: dict[str, Any], location: str, ctx: ValidationContext) -> None:
    if not quantity_requires_numeric_machine_fields(record, location):
        return
    for key in MACHINE_NUMERIC_FIELDS:
        value = record.get(key)
        if value in (None, ""):
            continue
        if not isinstance(value, str):
            continue
        if MACHINE_NUMBER_RE.fullmatch(value.strip()):
            continue
        ctx.error(
            f"{location}.{key}",
            "expected a single plain numeric machine value; keep ranges, limits, units, notes, and "
            "LaTeX residue in raw_value/description or a future structured range field",
        )


def validate_core_probability_record(record: dict[str, Any], location: str, ctx: ValidationContext) -> None:
    if not (
        ".core.bound_assessment.bound_probability" in location
        or ".core.bound_assessment.unbound_probability" in location
    ):
        return

    value = record.get("value")
    if not isinstance(value, str) or not MACHINE_NUMBER_RE.fullmatch(value.strip()):
        ctx.error(f"{location}.value", "bound/unbound probability value must be a plain 0-1 fraction")
        return

    numeric = float(value)
    if not (0.0 <= numeric <= 1.0):
        ctx.error(
            f"{location}.value",
            "bound/unbound probability value must be a 0-1 fraction; keep percent text in raw_value",
        )

    unit = record.get("unit", "")
    if isinstance(unit, str):
        if unit.strip():
            ctx.error(
                f"{location}.unit",
                "bound/unbound probability unit must be empty because value is a 0-1 fraction; keep '%' only in raw_value/source_refs",
            )
    else:
        ctx.error(f"{location}.unit", "bound/unbound probability unit must be an empty string")


def is_substantive_text_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith(("%", "#")):
        return False
    if stripped in {"{", "}"}:
        return False
    if PAGE_MARKER_RE.fullmatch(stripped):
        return False
    if LATEX_STRUCTURE_ONLY_RE.fullmatch(stripped):
        return False
    if LATEX_PREAMBLE_ASSIGNMENT_RE.fullmatch(stripped):
        return False
    return True


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
            if key == "source_refs" or key in COORDINATE_CONTEXT_KEYS:
                continue
            yield from iter_quantity_records(value, f"{location}.{key}")
    elif is_list(node):
        for index, item in enumerate(node):
            yield from iter_quantity_records(item, f"{location}[{index}]")


def validate_method_refs(
    record: dict[str, Any],
    location: str,
    method_ids: set[str],
    method_step_types: dict[str, str],
    method_dependencies: dict[str, list[str]],
    direct_step_categories: dict[str, set[str]],
    ctx: ValidationContext,
    *,
    require_complete: bool,
) -> None:
    if "method_refs" not in record:
        ctx.error(f"{location}.method_refs", "quantity record with value must include method_refs")
        return

    method_refs = record.get("method_refs")
    if not is_list(method_refs):
        ctx.error(f"{location}.method_refs", "expected a list")
        return
    if require_complete and len(method_refs) != 1:
        ctx.error(f"{location}.method_refs", "must reference exactly one direct method_chain step when complete")
    for ref_index, ref in enumerate(method_refs):
        if not isinstance(ref, str) or not ref:
            ctx.error(f"{location}.method_refs[{ref_index}]", "expected non-empty method_chain id")
            continue
        if ref not in method_ids:
            ctx.error(f"{location}.method_refs[{ref_index}]", f"unknown method_chain id {ref!r}")
            continue
        validate_direct_method_ref(
            record,
            location,
            ref,
            method_step_types,
            method_dependencies,
            direct_step_categories,
            ctx,
        )


def validate_direct_method_ref(
    record: dict[str, Any],
    location: str,
    method_ref: str,
    method_step_types: dict[str, str],
    method_dependencies: dict[str, list[str]],
    direct_step_categories: dict[str, set[str]],
    ctx: ValidationContext,
) -> None:
    category = classify_quantity_record(location, record)
    if category is None:
        return
    direct_step_categories[method_ref].add(category)

    step_type = method_step_types.get(method_ref)
    allowed_step_types = allowed_direct_step_types(category)
    if step_type not in allowed_step_types:
        ctx.error(
            f"{location}.method_refs",
            f"direct producer {method_ref!r} has step_type {step_type!r}; expected one of {sorted(allowed_step_types)}",
        )
        return
    if step_type == REPORTED_VALUE_STEP_TYPE:
        return

    lineage = lineage_for_step(method_ref, method_dependencies)
    lineage_types = {method_step_types.get(step_id) for step_id in lineage}
    for required_group in required_lineage_step_type_groups(category):
        if not lineage_types.intersection(required_group):
            ctx.error(
                f"{location}.method_refs",
                f"lineage for {method_ref!r} must include a step_type in {sorted(required_group)}",
            )


def validate_coordinate_context(
    value: Any,
    location: str,
    ctx: ValidationContext,
    *,
    context_kind: str,
) -> None:
    obj = validate_required_mapping(value, location, ctx)
    if obj is None:
        return

    context_value = obj.get("value")
    if not isinstance(context_value, str) or not context_value.strip():
        ctx.error(f"{location}.value", "expected non-empty coordinate context value or 'unknown'")
    normalized_value = context_value.strip().lower() if isinstance(context_value, str) else ""

    if context_kind == "epoch":
        epoch_kind = obj.get("epoch_kind")
        if epoch_kind not in EPOCH_KIND_VALUES:
            ctx.error(f"{location}.epoch_kind", f"expected one of {sorted(EPOCH_KIND_VALUES)}")

    for key in (
        "raw_value",
        "source_catalog",
        "data_release",
        "inference_basis",
        "reference_entry_id",
        "confidence",
        "description",
    ):
        if key in obj and not isinstance(obj.get(key), str):
            ctx.error(f"{location}.{key}", "expected string")

    refs = obj.get("source_refs")
    has_refs = is_list(refs) and bool(refs)
    if refs in (None, []):
        ctx.warn(f"{location}.source_refs", "coordinate context has no source reference; review provenance")
    else:
        validate_source_refs(refs, f"{location}.source_refs", ctx)

    inference_basis = str(obj.get("inference_basis") or "").strip().lower()
    is_documented_unknown = (
        normalized_value in UNKNOWN_CONTEXT_VALUES
        and inference_basis in {"not_in_reference", "not_reported"}
        and has_refs
    )
    if (
        (normalized_value in UNKNOWN_CONTEXT_VALUES or inference_basis in {"not_in_reference", "not_reported"})
        and not is_documented_unknown
    ):
        ctx.warn(
            location,
            "coordinate context is unknown or not covered by coordinate_frames.md; keep value unknown until reviewed",
        )


def _sexagesimal_parts(value: str) -> tuple[float, float, float] | None:
    match = re.fullmatch(r"([+-]?\d{1,3})[:hd°](\d{1,2})[:m'](\d{1,2}(?:\.\d+)?)(?:s|\")?", value)
    if not match:
        return None
    return float(match.group(1)), float(match.group(2)), float(match.group(3))


def validate_coordinate_range(value: str, location: str, ctx: ValidationContext, *, field_name: str) -> None:
    try:
        numeric = float(value)
    except ValueError:
        ctx.error(location, "decimal coordinate value must be a plain number")
        return
    if field_name == "ra" and not (0.0 <= numeric < 360.0):
        ctx.error(location, "RA in decimal degrees must be in [0, 360)")
    if field_name == "dec" and not (-90.0 <= numeric <= 90.0):
        ctx.error(location, "Dec in decimal degrees must be in [-90, 90]")


def validate_coordinate_sexagesimal_range(
    value: str,
    location: str,
    ctx: ValidationContext,
    *,
    field_name: str,
) -> None:
    parts = _sexagesimal_parts(value)
    if parts is None:
        return
    major, minutes, seconds = parts
    if not (0 <= minutes < 60) or not (0 <= seconds < 60):
        ctx.error(location, "sexagesimal coordinate minutes and seconds must be in [0, 60)")
        return
    if field_name == "ra" and not (0 <= major < 24):
        ctx.error(location, "RA sexagesimal hour component must be in [0, 24)")
    if field_name == "dec" and not (-90 <= major <= 90):
        ctx.error(location, "Dec sexagesimal degree component must be in [-90, 90]")


def validate_coordinate_record(record: Any, location: str, field_name: str, ctx: ValidationContext) -> None:
    obj = validate_required_mapping(record, location, ctx)
    if obj is None:
        return

    for key in ("coordinate_format", "reference_frame", "epoch"):
        if key not in obj:
            ctx.error(f"{location}.{key}", "missing required coordinate field")

    coordinate_format = obj.get("coordinate_format")
    if coordinate_format not in COORDINATE_FORMATS:
        ctx.error(f"{location}.coordinate_format", f"expected one of {sorted(COORDINATE_FORMATS)}")

    unit = obj.get("unit")
    if not isinstance(unit, str) or not unit.strip():
        ctx.error(f"{location}.unit", "coordinate unit is required")
    else:
        unit_text = unit.strip().lower()
        if coordinate_format == "decimal_degrees" and unit_text not in COORDINATE_DECIMAL_UNITS:
            ctx.error(f"{location}.unit", "decimal coordinate unit must be deg/degree/degrees")
        elif coordinate_format == "sexagesimal_hms" and (field_name != "ra" or unit_text not in COORDINATE_HOURANGLE_UNITS):
            ctx.error(f"{location}.unit", "sexagesimal_hms is only valid for RA with unit hourangle")
        elif coordinate_format == "sexagesimal_dms" and (field_name != "dec" or unit_text not in COORDINATE_DECIMAL_UNITS):
            ctx.error(f"{location}.unit", "sexagesimal_dms is only valid for Dec with angular degree units")
        elif coordinate_format == "sexagesimal_colon":
            expected_units = COORDINATE_HOURANGLE_UNITS if field_name == "ra" else COORDINATE_DECIMAL_UNITS
            if unit_text not in expected_units:
                ctx.error(f"{location}.unit", f"sexagesimal_colon {field_name.upper()} unit must be one of {sorted(expected_units)}")

    for key in ("value", "raw_value"):
        field_value = obj.get(key)
        if not isinstance(field_value, str):
            continue
        if "," in field_value or "(" in field_value or ")" in field_value:
            ctx.error(f"{location}.{key}", "RA/Dec must contain only this coordinate component, not a tuple or prose")

    for key in ("value", "raw_value", "unit", "description"):
        field_value = obj.get(key)
        if isinstance(field_value, str) and COORDINATE_CONTEXT_RE.search(field_value):
            ctx.error(f"{location}.{key}", "coordinate frame or epoch belongs in reference_frame/epoch, not in RA/Dec fields")

    coordinate_value = obj.get("value")
    if isinstance(coordinate_value, str) and isinstance(coordinate_format, str):
        stripped_value = coordinate_value.strip()
        if coordinate_format == "decimal_degrees":
            if MACHINE_NUMBER_RE.fullmatch(stripped_value):
                validate_coordinate_range(stripped_value, f"{location}.value", ctx, field_name=field_name)
            else:
                ctx.error(f"{location}.value", "decimal_degrees coordinate value must be a plain number")
        elif coordinate_format == "sexagesimal_hms":
            if not SEXAGESIMAL_HMS_RE.fullmatch(stripped_value):
                ctx.error(f"{location}.value", "sexagesimal_hms coordinate value must look like 17h39m53.68s")
            validate_coordinate_sexagesimal_range(stripped_value, f"{location}.value", ctx, field_name=field_name)
        elif coordinate_format == "sexagesimal_dms":
            if not SEXAGESIMAL_DMS_RE.fullmatch(stripped_value):
                ctx.error(f"{location}.value", "sexagesimal_dms coordinate value must look like -27d42m35.30s")
            validate_coordinate_sexagesimal_range(stripped_value, f"{location}.value", ctx, field_name=field_name)
        elif coordinate_format == "sexagesimal_colon":
            if not SEXAGESIMAL_COLON_RE.fullmatch(stripped_value):
                ctx.error(f"{location}.value", "sexagesimal_colon coordinate value must look like 16:37:12.214")
            validate_coordinate_sexagesimal_range(stripped_value, f"{location}.value", ctx, field_name=field_name)

    validate_coordinate_context(
        obj.get("reference_frame"),
        f"{location}.reference_frame",
        ctx,
        context_kind="reference_frame",
    )
    validate_coordinate_context(
        obj.get("epoch"),
        f"{location}.epoch",
        ctx,
        context_kind="epoch",
    )


def validate_coordinate_records(core: dict[str, Any], location: str, ctx: ValidationContext) -> None:
    observed = core.get("observed_phase_space")
    if not is_dict(observed):
        return
    for field_name in sorted(COORDINATE_FIELDS):
        record = observed.get(field_name)
        if record is None:
            continue
        validate_coordinate_record(record, f"{location}.observed_phase_space.{field_name}", field_name, ctx)


def validate_quantity_records(
    node: Any,
    location: str,
    ctx: ValidationContext,
    method_ids: set[str],
    method_step_types: dict[str, str],
    method_dependencies: dict[str, list[str]],
    direct_step_categories: dict[str, set[str]],
    *,
    require_complete: bool,
) -> None:
    for record, record_location in iter_quantity_records(node, location):
        if not is_dict(record):
            continue
        validate_clean_machine_string(record.get("value"), f"{record_location}.value", ctx)
        validate_method_refs(
            record,
            record_location,
            method_ids,
            method_step_types,
            method_dependencies,
            direct_step_categories,
            ctx,
            require_complete=require_complete,
        )
        raw_value = record.get("raw_value")
        if not isinstance(raw_value, str):
            ctx.error(f"{record_location}.raw_value", "quantity record with value must include raw_value")
        else:
            validate_uncertainty_fields(record, raw_value, record_location, ctx)
        for key in ("error", "lower_error", "upper_error"):
            if key in record and record.get(key) not in (None, ""):
                validate_clean_machine_string(record.get(key), f"{record_location}.{key}", ctx)
        warn_if_non_numeric_machine_fields(record, record_location, ctx)
        validate_core_probability_record(record, record_location, ctx)
        if "source_refs" not in record:
            ctx.error(record_location, "quantity record with value must include source_refs")
            continue
        validate_source_refs(record["source_refs"], f"{record_location}.source_refs", ctx)
        refs = record.get("source_refs")
        if isinstance(raw_value, str) and isinstance(refs, list):
            for ref_index, ref in enumerate(refs):
                if is_ecsv_source_ref(ref):
                    if not is_dict(ref):
                        ref_raw_value = None
                    else:
                        component_raw_value = ref.get("component_raw_value")
                        ref_raw_value = component_raw_value if isinstance(component_raw_value, str) and component_raw_value else ref.get("raw_value")
                    if ref_raw_value != raw_value:
                        ctx.error(
                            f"{record_location}.source_refs[{ref_index}]",
                            "ECSV source raw_value or component_raw_value must match the quantity record raw_value",
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
    validate_paper_text_evidence(
        source_refs,
        f"{location}.source_refs",
        ctx,
        "expected at least one paper text reference for origin evidence",
    )

    citation = origin_obj.get("citation")
    if origin_type == "cited_from_literature":
        citation_obj = validate_required_mapping(citation, f"{location}.citation", ctx)
        if citation_obj is not None:
            if not isinstance(citation_obj.get("bibkey"), str) or not citation_obj.get("bibkey"):
                ctx.error(f"{location}.citation.bibkey", "expected non-empty bibkey for cited candidates")
            validate_citation_refs_and_fields(
                citation_obj,
                f"{location}.citation",
                ctx,
                require_context_refs=True,
                require_bibliography_refs=True,
            )
    elif citation is not None:
        citation_obj = validate_required_mapping(citation, f"{location}.citation", ctx)
        if citation_obj is not None:
            validate_citation_refs_and_fields(
                citation_obj,
                f"{location}.citation",
                ctx,
                require_context_refs=False,
                require_bibliography_refs=False,
            )

    return origin_type if isinstance(origin_type, str) else None


def validate_identifier_record(
    record: Any,
    location: str,
    ctx: ValidationContext,
    *,
    require_complete: bool,
) -> str | None:
    record_obj = validate_required_mapping(record, location, ctx)
    if record_obj is None:
        return None

    value = record_obj.get("value")
    if not isinstance(value, str) or not value.strip():
        ctx.error(f"{location}.value", "expected non-empty identifier value")
        normalized_value = None
    else:
        normalized_value = value.strip()

    source_refs = record_obj.get("source_refs")
    if source_refs in (None, []):
        if require_complete:
            ctx.error(f"{location}.source_refs", "expected at least one source reference when complete")
    else:
        validate_source_refs(source_refs, f"{location}.source_refs", ctx)

    return normalized_value


def validate_candidate_identifiers(
    identifiers: Any,
    location: str,
    paper_arxiv_id: str,
    seen_record_ids: set[str],
    seen_paper_candidate_ids: set[str],
    seen_gaia_source_ids: set[str],
    ctx: ValidationContext,
    *,
    require_complete: bool,
) -> None:
    ids_obj = validate_required_mapping(identifiers, location, ctx)
    if ids_obj is None:
        return

    for key in LEGACY_IDENTIFIER_FIELDS:
        if key in ids_obj:
            ctx.error(f"{location}.{key}", "legacy identifier field is removed in v7; convert the file to v7 identifiers")

    for key in ("record_id", "paper_candidate_id", "gaia_source_id", "all"):
        if key not in ids_obj:
            ctx.error(f"{location}.{key}", "missing required field")

    record_id = ids_obj.get("record_id")
    expected_record_re = re.compile(rf"^{re.escape(paper_arxiv_id)}:cand-[0-9]{{3}}$")
    if not isinstance(record_id, str) or not record_id.strip():
        ctx.error(f"{location}.record_id", "expected non-empty record id")
        record_id_text = ""
    else:
        record_id_text = record_id.strip()
        if not expected_record_re.fullmatch(record_id_text):
            ctx.error(f"{location}.record_id", f"expected {paper_arxiv_id}:cand-XXX format")
        if record_id_text in seen_record_ids:
            ctx.error(f"{location}.record_id", f"duplicate record_id {record_id_text!r}")
        seen_record_ids.add(record_id_text)

    paper_candidate_id = ids_obj.get("paper_candidate_id")
    if not isinstance(paper_candidate_id, str) or not paper_candidate_id.strip():
        ctx.error(f"{location}.paper_candidate_id", "expected non-empty paper candidate identifier")
        paper_candidate_id_text = ""
    else:
        paper_candidate_id_text = paper_candidate_id.strip()
        if paper_candidate_id_text in seen_paper_candidate_ids:
            ctx.error(f"{location}.paper_candidate_id", f"duplicate paper_candidate_id {paper_candidate_id_text!r}")
        seen_paper_candidate_ids.add(paper_candidate_id_text)

    gaia_source_id = ids_obj.get("gaia_source_id")
    if not isinstance(gaia_source_id, str):
        ctx.error(f"{location}.gaia_source_id", "expected string")
        gaia_source_id_text = ""
    else:
        gaia_source_id_text = gaia_source_id.strip()
        if gaia_source_id_text and not GAIA_SOURCE_ID_RE.fullmatch(gaia_source_id_text):
            ctx.error(
                f"{location}.gaia_source_id",
                "expected empty string or strict Gaia source id like 'Gaia DR3 123456789'",
            )
        if gaia_source_id_text:
            if gaia_source_id_text in seen_gaia_source_ids:
                ctx.error(f"{location}.gaia_source_id", f"duplicate gaia_source_id {gaia_source_id_text!r}")
            seen_gaia_source_ids.add(gaia_source_id_text)

    all_value = ids_obj.get("all")
    all_list = validate_required_list(all_value, f"{location}.all", ctx)
    if all_list is None:
        return
    if not all_list:
        ctx.error(f"{location}.all", "must be non-empty")
        return

    all_identifiers: set[str] = set()
    for index, record in enumerate(all_list):
        value = validate_identifier_record(
            record,
            f"{location}.all[{index}]",
            ctx,
            require_complete=require_complete,
        )
        if value is None:
            continue
        if value in all_identifiers:
            ctx.error(f"{location}.all[{index}].value", f"duplicate identifier value {value!r}")
        all_identifiers.add(value)
        if record_id_text and value == record_id_text:
            ctx.error(f"{location}.all[{index}].value", "record_id is internal and must not appear in identifiers.all")

    if paper_candidate_id_text and paper_candidate_id_text not in all_identifiers:
        ctx.error(f"{location}.paper_candidate_id", "must also appear in identifiers.all[].value")
    if gaia_source_id_text and gaia_source_id_text not in all_identifiers:
        ctx.error(f"{location}.gaia_source_id", "must also appear in identifiers.all[].value")
    if not gaia_source_id_text and any(GAIA_SOURCE_ID_RE.fullmatch(value) for value in all_identifiers):
        ctx.error(f"{location}.gaia_source_id", "must be set when identifiers.all contains a strict Gaia source id")


def validate_inclusion_assessment(assessment: Any, location: str, ctx: ValidationContext) -> None:
    assessment_obj = validate_required_mapping(assessment, location, ctx)
    if assessment_obj is None:
        return

    if not assessment_obj.get("summary"):
        ctx.error(f"{location}.summary", "expected non-empty candidate rationale")

    paper_labels = assessment_obj.get("paper_labels")
    label_list = validate_required_list(paper_labels, f"{location}.paper_labels", ctx)
    if label_list is not None:
        if not label_list:
            ctx.error(f"{location}.paper_labels", "expected at least one paper label")
        seen_labels: set[str] = set()
        for label_index, label in enumerate(label_list):
            if label not in LITERATURE_HVS_PAPER_LABELS:
                ctx.error(
                    f"{location}.paper_labels[{label_index}]",
                    f"expected one of {sorted(LITERATURE_HVS_PAPER_LABELS)}",
                )
            elif label in seen_labels:
                ctx.error(f"{location}.paper_labels[{label_index}]", f"duplicate paper label {label!r}")
            seen_labels.add(str(label))

    galactic_bound_claim = assessment_obj.get("galactic_bound_claim")
    if galactic_bound_claim not in LITERATURE_HVS_GALACTIC_BOUND_CLAIMS:
        ctx.error(
            f"{location}.galactic_bound_claim",
            f"expected one of {sorted(LITERATURE_HVS_GALACTIC_BOUND_CLAIMS)}",
        )

    inclusion_basis = assessment_obj.get("inclusion_basis")
    if inclusion_basis not in LITERATURE_HVS_INCLUSION_BASES:
        ctx.error(f"{location}.inclusion_basis", f"expected one of {sorted(LITERATURE_HVS_INCLUSION_BASES)}")

    extraction_confidence = assessment_obj.get("extraction_confidence")
    if extraction_confidence not in LITERATURE_HVS_EXTRACTION_CONFIDENCE:
        ctx.error(
            f"{location}.extraction_confidence",
            f"expected one of {sorted(LITERATURE_HVS_EXTRACTION_CONFIDENCE)}",
        )
    if not str(assessment_obj.get("confidence_reason") or "").strip():
        ctx.error(f"{location}.confidence_reason", "expected non-empty extraction confidence rationale")

    assessment_refs = assessment_obj.get("source_refs")
    validate_source_refs(assessment_refs, f"{location}.source_refs", ctx)
    validate_paper_text_evidence(
        assessment_refs,
        f"{location}.source_refs",
        ctx,
        "expected at least one paper text reference for Galactic-unbound candidate evidence",
    )


def validate_extra_records(extra_list: list[Any], location: str, ctx: ValidationContext) -> None:
    for index, record in enumerate(extra_list):
        if not is_dict(record):
            continue
        searchable = " ".join(
            str(record.get(key) or "")
            for key in ("name", "kind", "description", "unit", "raw_value")
        )
        if STANDARD_EXTRA_RE.search(searchable):
            ctx.error(
                f"{location}[{index}]",
                "standard HVS candidate quantity belongs in a typed v7 group, not extra[]",
            )


def validate_candidate(
    candidate: Any,
    index: int,
    paper_arxiv_id: str,
    seen_record_ids: set[str],
    seen_paper_candidate_ids: set[str],
    seen_gaia_source_ids: set[str],
    method_ids: set[str],
    method_step_types: dict[str, str],
    method_dependencies: dict[str, list[str]],
    direct_step_categories: dict[str, set[str]],
    ctx: ValidationContext,
    *,
    require_complete: bool,
) -> None:
    location = f"candidates[{index}]"
    candidate_obj = validate_required_mapping(candidate, location, ctx)
    if candidate_obj is None:
        return

    for key in (
        "identifiers",
        "inclusion_assessment",
        "candidate_origin",
        "core",
        "photometry",
        "spectroscopy",
        "stellar_parameters",
        "abundances",
        "quality_flags",
        "orbit",
        "astrophysical_origin",
        "extra",
    ):
        if key not in candidate_obj:
            ctx.error(f"{location}.{key}", "missing required field")
    if "candidate_assessment" in candidate_obj:
        ctx.error(f"{location}.candidate_assessment", "candidate_assessment is removed in v7; use inclusion_assessment")
    if "method_chain_refs" in candidate_obj:
        ctx.error(f"{location}.method_chain_refs", "candidate-level method_chain_refs is removed; use quantity method_refs")
    for key in LEGACY_CANDIDATE_FIELDS:
        if key in candidate_obj:
            ctx.error(f"{location}.{key}", "legacy candidate field is removed in v7; convert the file to v7 identifiers")

    identifiers = candidate_obj.get("identifiers")
    validate_candidate_identifiers(
        identifiers,
        f"{location}.identifiers",
        paper_arxiv_id,
        seen_record_ids,
        seen_paper_candidate_ids,
        seen_gaia_source_ids,
        ctx,
        require_complete=require_complete,
    )

    validate_inclusion_assessment(candidate_obj.get("inclusion_assessment"), f"{location}.inclusion_assessment", ctx)

    validate_candidate_origin(
        candidate_obj.get("candidate_origin"),
        f"{location}.candidate_origin",
        ctx,
    )
    warn_if_candidate_bound_conflict(candidate_obj, location, ctx)

    core = candidate_obj.get("core")
    if is_dict(core):
        validate_core(
            core,
            f"{location}.core",
            ctx,
            method_ids,
            method_step_types,
            method_dependencies,
            direct_step_categories,
            require_complete=require_complete,
        )
    else:
        ctx.error(f"{location}.core", "expected an object")

    for key in ("photometry", "spectroscopy", "abundances", "quality_flags", "extra"):
        value = candidate_obj.get(key)
        value_list = validate_required_list(value, f"{location}.{key}", ctx)
        if value_list is None:
            continue
        if key == "extra":
            validate_extra_records(value_list, f"{location}.extra", ctx)
        validate_quantity_records(
            value_list,
            f"{location}.{key}",
            ctx,
            method_ids,
            method_step_types,
            method_dependencies,
            direct_step_categories,
            require_complete=require_complete,
        )

    for key in ("stellar_parameters", "orbit", "astrophysical_origin"):
        value = candidate_obj.get(key)
        if is_dict(value):
            validate_quantity_records(
                value,
                f"{location}.{key}",
                ctx,
                method_ids,
                method_step_types,
                method_dependencies,
                direct_step_categories,
                require_complete=require_complete,
            )
        else:
            ctx.error(f"{location}.{key}", "expected an object")


def validate_core(
    core: dict[str, Any],
    location: str,
    ctx: ValidationContext,
    method_ids: set[str],
    method_step_types: dict[str, str],
    method_dependencies: dict[str, list[str]],
    direct_step_categories: dict[str, set[str]],
    *,
    require_complete: bool,
) -> None:
    allowed = set(CORE_GROUPS)
    unexpected = sorted(set(core) - allowed)
    for key in unexpected:
        ctx.error(f"{location}.{key}", f"unexpected core group; expected only {list(CORE_GROUPS)}")
    for group in CORE_GROUPS:
        value = core.get(group)
        if not is_dict(value):
            ctx.error(f"{location}.{group}", "expected core schema group object")
    validate_coordinate_records(core, location, ctx)
    validate_quantity_records(
        core,
        location,
        ctx,
        method_ids,
        method_step_types,
        method_dependencies,
        direct_step_categories,
        require_complete=require_complete,
    )


def warn_if_candidate_bound_conflict(candidate_obj: dict[str, Any], location: str, ctx: ValidationContext) -> None:
    texts: list[str] = []
    assessment = candidate_obj.get("inclusion_assessment")
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
            ctx.error(
                location,
                f"candidate evidence contains bound-status phrase {match.group(0)!r}; move Galaxy-bound objects to candidate_groups_considered",
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
            validate_paper_text_evidence(
                group["source_refs"],
                f"{location}.source_refs",
                ctx,
                "expected at least one paper text reference for candidate group evidence",
            )
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
        if match and not NO_CANDIDATE_NEGATION_RE.search(text):
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


def validate_method_chain(
    method_chain: Any,
    ctx: ValidationContext,
) -> tuple[set[str], dict[str, str], dict[str, list[str]]]:
    method_ids: set[str] = set()
    method_step_types: dict[str, str] = {}
    method_dependencies: dict[str, list[str]] = {}
    previous_method_number = 0

    if not is_list(method_chain):
        ctx.error("$.method_chain", "expected a list")
        return method_ids, method_step_types, method_dependencies

    for index, step in enumerate(method_chain):
        if not is_dict(step):
            ctx.error(f"$.method_chain[{index}]", "expected an object")
            continue
        step_id = step.get("id")
        if not isinstance(step_id, str) or not step_id:
            ctx.error(f"$.method_chain[{index}].id", "expected non-empty string")
            continue
        if not METHOD_STEP_ID_RE.match(step_id):
            ctx.error(f"$.method_chain[{index}].id", "expected step-XX format")
        else:
            step_number = int(step_id.split("-")[1])
            if step_number <= previous_method_number:
                ctx.error(f"$.method_chain[{index}].id", "method_chain ids must be in ascending numeric order")
            previous_method_number = step_number
        if step_id in method_ids:
            ctx.error(f"$.method_chain[{index}].id", f"duplicate method_chain id {step_id!r}")
        method_ids.add(step_id)

        step_type = step.get("step_type")
        if step_type not in LITERATURE_HVS_METHOD_STEP_TYPES:
            ctx.error(
                f"$.method_chain[{index}].step_type",
                f"expected one of {sorted(LITERATURE_HVS_METHOD_STEP_TYPES)}",
            )
        elif isinstance(step_type, str):
            method_step_types[step_id] = step_type

        if "depends_on" not in step:
            ctx.error(f"$.method_chain[{index}].depends_on", "missing required field")
            depends_on: Any = []
        else:
            depends_on = step.get("depends_on")
        method_dependencies[step_id] = validate_method_step_dependencies(
            depends_on,
            f"$.method_chain[{index}].depends_on",
            step_id,
            method_ids,
            ctx,
        )

        if "source_refs" in step:
            validate_source_refs(step["source_refs"], f"$.method_chain[{index}].source_refs", ctx)
        for warning in coarse_step_warnings(step):
            ctx.warn(f"$.method_chain[{index}]", warning)

    validate_method_dependency_cycles(method_dependencies, ctx)
    return method_ids, method_step_types, method_dependencies


def validate_method_step_dependencies(
    depends_on: Any,
    location: str,
    step_id: str,
    prior_method_ids: set[str],
    ctx: ValidationContext,
) -> list[str]:
    if not is_list(depends_on):
        ctx.error(location, "expected a list")
        return []
    valid_dependencies: list[str] = []
    seen: set[str] = set()
    for index, dependency in enumerate(depends_on):
        dependency_location = f"{location}[{index}]"
        if not isinstance(dependency, str) or not dependency:
            ctx.error(dependency_location, "expected non-empty method_chain id")
            continue
        if dependency == step_id:
            ctx.error(dependency_location, "method step cannot depend on itself")
            continue
        if dependency in seen:
            ctx.error(dependency_location, f"duplicate dependency {dependency!r}")
            continue
        seen.add(dependency)
        if dependency not in prior_method_ids:
            ctx.error(dependency_location, f"dependency {dependency!r} must reference an earlier method_chain step")
            continue
        valid_dependencies.append(dependency)
    return valid_dependencies


def validate_method_dependency_cycles(method_dependencies: dict[str, list[str]], ctx: ValidationContext) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(step_id: str, chain: list[str]) -> None:
        if step_id in visited:
            return
        if step_id in visiting:
            ctx.error("$.method_chain", f"method dependency cycle detected: {' -> '.join(chain + [step_id])}")
            return
        visiting.add(step_id)
        for dependency in method_dependencies.get(step_id, []):
            visit(dependency, chain + [step_id])
        visiting.remove(step_id)
        visited.add(step_id)

    for step_id in method_dependencies:
        visit(step_id, [])


def validate_direct_step_category_compatibility(
    direct_step_categories: dict[str, set[str]],
    ctx: ValidationContext,
) -> None:
    for step_id, categories in sorted(direct_step_categories.items()):
        if categories_have_compatible_direct_types(categories):
            continue
        ctx.error(
            "$.candidates",
            f"method step {step_id!r} is used as direct producer for incompatible quantity categories "
            f"{sorted(categories)}; split this method step",
        )


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
    paper_arxiv_id = ""
    if not is_dict(paper):
        ctx.error("$.paper", "expected an object")
    elif not paper.get("arxiv_id"):
        ctx.error("$.paper.arxiv_id", "expected non-empty arXiv ID")
    else:
        paper_arxiv_id = str(paper.get("arxiv_id") or "").strip()
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
        if status not in LITERATURE_HVS_EXTRACTION_STATUSES:
            ctx.error("$.extraction.status", f"expected one of {sorted(LITERATURE_HVS_EXTRACTION_STATUSES)}")

    method_ids, method_step_types, method_dependencies = validate_method_chain(root.get("method_chain"), ctx)
    direct_step_categories: dict[str, set[str]] = defaultdict(set)
    seen_record_ids: set[str] = set()
    seen_paper_candidate_ids: set[str] = set()
    seen_gaia_source_ids: set[str] = set()

    candidates = root.get("candidates")
    if not is_list(candidates):
        ctx.error("$.candidates", "expected a list")
    else:
        if status == "no_candidates" and candidates:
            ctx.error("$.candidates", "must be empty when extraction.status is no_candidates")
        if status == "candidates_found" and not candidates:
            ctx.error("$.candidates", "must contain at least one candidate when extraction.status is candidates_found")
        for index, candidate in enumerate(candidates):
            validate_candidate(
                candidate,
                index,
                paper_arxiv_id,
                seen_record_ids,
                seen_paper_candidate_ids,
                seen_gaia_source_ids,
                method_ids,
                method_step_types,
                method_dependencies,
                direct_step_categories,
                ctx,
                require_complete=require_complete,
            )
        validate_direct_step_category_compatibility(direct_step_categories, ctx)

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
    selection.add_argument("--all", action="store_true", help="Validate every literature_hvs_candidates.json file.")
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
    parser.add_argument(
        "--verbose-warnings",
        action="store_true",
        help="Print every warning instead of grouping repeated candidate warnings.",
    )
    return parser


def _validate_one_path(
    path: Path,
    *,
    workspace: Path,
    require_complete: bool,
    verbose_warnings: bool,
) -> ValidationReport | None:
    if not path.exists():
        print(f"missing candidate extraction JSON: {path}", file=sys.stderr)
        return None

    try:
        payload = load_json(path)
    except json.JSONDecodeError as exc:
        print(f"{path}: invalid JSON: {exc}", file=sys.stderr)
        return None

    report = validate_hvs_candidates_report(
        payload,
        workspace=workspace,
        require_complete=require_complete,
    )
    warning_lines = report.warnings if verbose_warnings else grouped_warning_lines(report.warnings)
    for warning in warning_lines:
        print(f"WARNING: {path}: {warning}", file=sys.stderr)
    for error in report.errors:
        print(f"{path}: {error}", file=sys.stderr)
    return report


def main() -> int:
    args = build_parser().parse_args()
    workspace = args.workspace.expanduser()

    literature_dir = args.literature_dir.expanduser()
    if args.all:
        paths = list(iter_hvs_candidates_paths(literature_dir))
    elif args.path:
        paths = [args.path.expanduser()]
    else:
        paths = [literature_dir / str(args.arxiv_id) / "literature_hvs_candidates.json"]

    if not paths:
        print(f"no literature_hvs_candidates.json files found under {literature_dir}", file=sys.stderr)
        return 1

    reports: list[ValidationReport] = []
    missing_or_invalid = 0
    for path in paths:
        report = _validate_one_path(
            path,
            workspace=workspace,
            require_complete=args.require_complete,
            verbose_warnings=args.verbose_warnings,
        )
        if report is None:
            missing_or_invalid += 1
            continue
        reports.append(report)

    error_count = missing_or_invalid + sum(len(report.errors) for report in reports)
    warning_count = sum(len(report.warnings) for report in reports)
    if error_count:
        print(f"FAILED: {len(paths)} files checked, {error_count} errors, {warning_count} warnings.", file=sys.stderr)
        return 1

    if args.all:
        print(f"OK: {len(paths)} files checked, 0 errors, {warning_count} warnings.")
    else:
        print(f"OK: {paths[0]}")

    if args.rebuild_index:
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
