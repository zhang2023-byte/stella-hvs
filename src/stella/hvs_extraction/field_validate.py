"""Deterministic field-extraction validation, hydration, and bibliography resolution.

Structural validation proves that every submitted quantity component has one
real source locator; whether that source
actually belongs to the assigned candidate remains the field extractor's
scientific responsibility. Code hydrates exact source text, ECSV
cells and column headers, and bibliography provenance; it never moves a
locator, rewrites a fragment, or substitutes a nearby citation key.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stella.hvs_extraction.ecsv import EcsvStructure
from stella.hvs_extraction.ecsv_cells import EcsvRowParseError, cell_at
from stella.hvs_extraction.field_schema import (
    CORE_GROUPS,
    COORDINATE_FIELDS,
    QUANTITY_PARTS,
)


@dataclass(frozen=True)
class FieldIssue:
    path: str
    code: str
    message: str

    def render(self) -> str:
        return f"{self.path}: {self.code}: {self.message}"


# Locator error codes.
TEXT_PATH_NOT_ALLOWED = "text_path_not_allowed"
TEXT_LINE_OUT_OF_BOUNDS = "text_line_out_of_bounds"
TEXT_LINE_RANGE_REVERSED = "text_line_range_reversed"
TEXT_RAW_VALUE_EMPTY = "text_raw_value_empty"
TEXT_RAW_VALUE_NOT_FOUND = "text_raw_value_not_found"
ECSV_PATH_NOT_ALLOWED = "ecsv_path_not_allowed"
ECSV_LINE_OUT_OF_BOUNDS = "ecsv_line_out_of_bounds"
ECSV_LINE_NOT_DATA_ROW = "ecsv_line_not_data_row"
ECSV_COLUMN_NOT_FOUND = "ecsv_column_not_found"
ECSV_ROW_PARSE_FAILURE = "ecsv_row_parse_failure"
ECSV_CELL_MISSING = "ecsv_cell_missing"
ECSV_COMPONENT_EMPTY = "ecsv_component_empty"
ECSV_COMPONENT_NOT_FOUND = "ecsv_component_not_found"

# Structural invariant codes.
QUANTITY_EMPTY = "quantity_empty"
UNCERTAINTY_MIXED = "uncertainty_mixed"
UNCERTAINTY_INCOMPLETE_ASYMMETRIC = "uncertainty_incomplete_asymmetric"
RANGE_INCONSISTENT = "range_inconsistent"
VALUE_MISSING = "value_missing"
DIRECT_EVIDENCE_MISSING = "direct_evidence_missing"
DIRECT_EVIDENCE_UNEXPECTED = "direct_evidence_unexpected"
DIRECT_EVIDENCE_DUPLICATE_PART = "direct_evidence_duplicate_part"
CONTEXT_EVIDENCE_DUPLICATE = "context_evidence_duplicate"
COORDINATE_FORMAT_INCONSISTENT = "coordinate_format_inconsistent"
ORIGIN_BIBKEY_REQUIRED = "origin_bibkey_required"
ORIGIN_BIBKEY_FORBIDDEN = "origin_bibkey_forbidden"
ORIGIN_EVIDENCE_DUPLICATE = "origin_evidence_duplicate"
CONFLICT_FIELD_DUPLICATE = "conflict_field_duplicate"
CONFLICT_RESOLUTION_INCONSISTENT = "conflict_resolution_inconsistent"

DEGREE_UNITS = {"deg", "degree", "degrees", "°", "^\\circ", "\\circ"}
HOUR_UNITS = {"h", "hr", "hour", "hours", "^h", "\\rm{h}", "\\mathrm{h}"}


def _issues_for_quantity(path: str, quantity: dict[str, Any]) -> list[FieldIssue]:
    issues: list[FieldIssue] = []
    components = {part: quantity.get(part) for part in QUANTITY_PARTS}
    populated = {part for part, value in components.items() if value is not None}
    if not populated:
        issues.append(
            FieldIssue(path, QUANTITY_EMPTY, "quantity has no numeric component; submit null for the field instead")
        )
        return issues
    error = components.get("error") is not None
    lower = components.get("lower_error") is not None
    upper = components.get("upper_error") is not None
    if error and (lower or upper):
        issues.append(
            FieldIssue(path, UNCERTAINTY_MIXED, "symmetric and asymmetric uncertainty representations are mixed")
        )
    if lower != upper:
        issues.append(
            FieldIssue(path, UNCERTAINTY_INCOMPLETE_ASYMMETRIC, "asymmetric uncertainty requires both lower_error and upper_error")
        )
    limit_kind = quantity.get("limit_kind")
    range_lower = components.get("range_lower") is not None
    range_upper = components.get("range_upper") is not None
    if limit_kind == "range":
        if components.get("value") is not None or not (range_lower and range_upper):
            issues.append(
                FieldIssue(path, RANGE_INCONSISTENT, "a closed range uses range_lower and range_upper and leaves value null")
            )
    else:
        if range_lower or range_upper:
            issues.append(
                FieldIssue(path, RANGE_INCONSISTENT, "range bounds require limit_kind 'range'")
            )
        if components.get("value") is None:
            issues.append(
                FieldIssue(path, VALUE_MISSING, "a non-range quantity requires a value")
            )
    parts_seen: dict[str, int] = {}
    for index, item in enumerate(quantity.get("direct_evidence") or []):
        part = item.get("part")
        item_path = f"{path}.direct_evidence[{index}]"
        if part in parts_seen:
            issues.append(
                FieldIssue(item_path, DIRECT_EVIDENCE_DUPLICATE_PART, f"part {part!r} already has a direct evidence item at index {parts_seen[part]}")
            )
        parts_seen.setdefault(part, index)
        if part in QUANTITY_PARTS and part not in populated:
            issues.append(
                FieldIssue(item_path, DIRECT_EVIDENCE_UNEXPECTED, f"part {part!r} has no populated component")
            )
    for part in populated:
        if part not in parts_seen:
            issues.append(
                FieldIssue(path, DIRECT_EVIDENCE_MISSING, f"component {part!r} lacks its one direct evidence item")
            )
    context_seen: set[tuple] = set()
    for index, item in enumerate(quantity.get("context_evidence") or []):
        key = (item.get("path"), item.get("start_line"), item.get("end_line"))
        if key in context_seen:
            issues.append(
                FieldIssue(f"{path}.context_evidence[{index}]", CONTEXT_EVIDENCE_DUPLICATE, "duplicate identical context locator")
            )
        context_seen.add(key)
    return issues


_SEXAGESIMAL_COLON_RE = re.compile(r"^[+-]?\d{1,3}:\d{1,2}(?::\d{1,2}(?:\.\d+)?)?$")
_SEXAGESIMAL_LETTER_RE = re.compile(
    r"^[+-]?\d{1,3}\s*[hd]\s*\d{1,2}\s*[m'](?:\s*\d{1,2}(?:\.\d+)?\s*[s\"]?)?$",
    re.IGNORECASE,
)
_PLAIN_NUMBER_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")


def _sexagesimal_bounds_ok(value: str) -> bool:
    numbers = [float(part) for part in re.split(r"[:hmd'\"s\s]+", value) if part]
    if not numbers:
        return False
    return all(0 <= part < 60 for part in numbers[1:])


def _issues_for_coordinate(path: str, field: str, quantity: dict[str, Any]) -> list[FieldIssue]:
    issues: list[FieldIssue] = []
    coordinate_format = quantity.get("coordinate_format")
    value = quantity.get("value")
    unit = (quantity.get("unit") or "").strip()
    if coordinate_format == "decimal_degrees":
        if value is not None and not _PLAIN_NUMBER_RE.match(str(value).strip()):
            issues.append(
                FieldIssue(path, COORDINATE_FORMAT_INCONSISTENT, "decimal_degrees requires a plain numeric value")
            )
        if unit and unit.lower() not in DEGREE_UNITS:
            issues.append(
                FieldIssue(path, COORDINATE_FORMAT_INCONSISTENT, f"decimal_degrees requires a degree unit, got {unit!r}")
            )
        return issues
    if value is not None:
        colon_form = bool(_SEXAGESIMAL_COLON_RE.match(str(value).strip()))
        letter_form = bool(_SEXAGESIMAL_LETTER_RE.match(str(value).strip()))
        if coordinate_format == "sexagesimal_colon" and not colon_form:
            issues.append(
                FieldIssue(path, COORDINATE_FORMAT_INCONSISTENT, "sexagesimal_colon requires a colon-separated value")
            )
        if coordinate_format in ("sexagesimal_hms", "sexagesimal_dms") and not letter_form:
            issues.append(
                FieldIssue(path, COORDINATE_FORMAT_INCONSISTENT, f"{coordinate_format} requires a letter-marked sexagesimal value")
            )
        if (colon_form or letter_form) and not _sexagesimal_bounds_ok(str(value).strip()):
            issues.append(
                FieldIssue(path, COORDINATE_FORMAT_INCONSISTENT, "sexagesimal minutes/seconds are out of bounds")
            )
    if coordinate_format == "sexagesimal_hms" and field != "ra":
        issues.append(
            FieldIssue(path, COORDINATE_FORMAT_INCONSISTENT, "sexagesimal_hms is valid only for ra")
        )
    if coordinate_format == "sexagesimal_dms" and field != "dec":
        issues.append(
            FieldIssue(path, COORDINATE_FORMAT_INCONSISTENT, "sexagesimal_dms is valid only for dec")
        )
    hour_like = coordinate_format == "sexagesimal_hms" or (
        coordinate_format == "sexagesimal_colon" and field == "ra"
    )
    if unit:
        if hour_like and unit.lower() not in HOUR_UNITS:
            issues.append(
                FieldIssue(path, COORDINATE_FORMAT_INCONSISTENT, f"sexagesimal ra requires an hour-angle unit, got {unit!r}")
            )
        if not hour_like and unit.lower() not in DEGREE_UNITS:
            issues.append(
                FieldIssue(path, COORDINATE_FORMAT_INCONSISTENT, f"this coordinate form requires a degree unit, got {unit!r}")
            )
    return issues


@dataclass
class FieldValidationContext:
    tex_line_counts: dict[str, int]
    tex_texts: dict[str, str]
    ecsv_structures: dict[str, EcsvStructure]
    ecsv_texts: dict[str, str]

    def tex_lines(self, path: str) -> list[str]:
        lines = self.tex_texts[path].split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        return lines

    def ecsv_lines(self, path: str) -> list[str]:
        lines = self.ecsv_texts[path].split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        return lines


def _validate_text_locator(
    path: str,
    ref: dict[str, Any],
    ctx: FieldValidationContext,
    *,
    require_raw_value: bool,
) -> list[FieldIssue]:
    issues: list[FieldIssue] = []
    tex_path = ref.get("path")
    if tex_path not in ctx.tex_line_counts:
        return [FieldIssue(path, TEXT_PATH_NOT_ALLOWED, f"path {tex_path!r} is not a TeX file in the approved manuscript graph")]
    start, end = ref.get("start_line"), ref.get("end_line")
    if not isinstance(start, int) or not isinstance(end, int) or isinstance(start, bool) or isinstance(end, bool):
        return [FieldIssue(path, TEXT_LINE_OUT_OF_BOUNDS, "line values must be integers")]
    if start > end:
        return [FieldIssue(path, TEXT_LINE_RANGE_REVERSED, f"start_line {start} exceeds end_line {end}")]
    line_count = ctx.tex_line_counts[tex_path]
    if start < 1 or end > line_count:
        return [FieldIssue(path, TEXT_LINE_OUT_OF_BOUNDS, f"range {start}-{end} is outside {tex_path} (1-{line_count})")]
    if require_raw_value:
        raw_value = ref.get("raw_value")
        if not isinstance(raw_value, str) or not raw_value:
            issues.append(FieldIssue(path, TEXT_RAW_VALUE_EMPTY, "raw_value must be a non-empty string"))
        else:
            resolved = "\n".join(ctx.tex_lines(tex_path)[start - 1 : end])
            if raw_value not in resolved:
                issues.append(
                    FieldIssue(path, TEXT_RAW_VALUE_NOT_FOUND, "raw_value does not occur verbatim in the resolved TeX range")
                )
    return issues


def _validate_ecsv_locator(
    path: str,
    ref: dict[str, Any],
    ctx: FieldValidationContext,
    *,
    allow_component: bool,
) -> list[FieldIssue]:
    issues: list[FieldIssue] = []
    ecsv_path = ref.get("path")
    if ecsv_path not in ctx.ecsv_structures:
        return [FieldIssue(path, ECSV_PATH_NOT_ALLOWED, f"path {ecsv_path!r} is not one of the ECSV files attached to this request")]
    structure = ctx.ecsv_structures[ecsv_path]
    line = ref.get("line")
    if not isinstance(line, int) or isinstance(line, bool) or line < 1 or line > structure.line_count:
        return [FieldIssue(path, ECSV_LINE_OUT_OF_BOUNDS, f"line {line!r} is outside {ecsv_path} (1-{structure.line_count})")]
    if line not in structure.data_row_lines:
        return [FieldIssue(path, ECSV_LINE_NOT_DATA_ROW, f"line {line} in {ecsv_path} is metadata or the column-name row, not a data row")]
    column = ref.get("column")
    if column not in structure.columns:
        return [FieldIssue(path, ECSV_COLUMN_NOT_FOUND, f"column {column!r} does not exist in {ecsv_path}")]
    row_text = ctx.ecsv_lines(ecsv_path)[line - 1]
    column_index = structure.columns.index(column)
    try:
        cell = cell_at(row_text, column_index)
    except EcsvRowParseError as exc:
        return [FieldIssue(path, ECSV_ROW_PARSE_FAILURE, f"row {line} in {ecsv_path} cannot be parsed: {exc}")]
    if cell == "":
        issues.append(FieldIssue(path, ECSV_CELL_MISSING, f"cell at line {line} column {column!r} is empty"))
    component = ref.get("component_raw_value")
    if component is not None:
        if not allow_component:
            issues.append(
                FieldIssue(path, ECSV_COMPONENT_NOT_FOUND, "component_raw_value is not accepted for this source")
            )
        elif not isinstance(component, str) or not component:
            issues.append(FieldIssue(path, ECSV_COMPONENT_EMPTY, "component_raw_value must be a non-empty string"))
        elif component not in cell:
            issues.append(
                FieldIssue(path, ECSV_COMPONENT_NOT_FOUND, "component_raw_value does not occur in the addressed cell")
            )
    return issues


def validate_field_submission(
    payload: dict[str, Any], ctx: FieldValidationContext
) -> list[FieldIssue]:
    """Run every deterministic structural and locator check (no science)."""

    issues: list[FieldIssue] = []
    core = payload.get("core") or {}
    quantities: dict[str, dict[str, Any] | None] = {}
    for group, fields in CORE_GROUPS.items():
        group_payload = core.get(group) or {}
        for field_name in fields:
            quantity = group_payload.get(field_name)
            field_path = f"{group}.{field_name}"
            quantities[field_path] = quantity if isinstance(quantity, dict) else None
            if isinstance(quantity, dict):
                base = f"$.core.{group}.{field_name}"
                issues.extend(_issues_for_quantity(base, quantity))
                if field_name in COORDINATE_FIELDS:
                    issues.extend(_issues_for_coordinate(base, field_name, quantity))

    origin = payload.get("candidate_origin") or {}
    origin_type = origin.get("origin_type")
    bibkey = origin.get("bibkey")
    if origin_type == "cited_from_literature" and not bibkey:
        issues.append(
            FieldIssue("$.candidate_origin.bibkey", ORIGIN_BIBKEY_REQUIRED, "cited_from_literature requires a non-empty bibkey")
        )
    if origin_type == "introduced_by_this_paper" and bibkey is not None:
        issues.append(
            FieldIssue("$.candidate_origin.bibkey", ORIGIN_BIBKEY_FORBIDDEN, "introduced_by_this_paper requires bibkey null")
        )
    origin_seen: set[tuple] = set()
    for index, ref in enumerate(origin.get("evidence") or []):
        key = (ref.get("path"), ref.get("start_line"), ref.get("end_line"))
        if key in origin_seen:
            issues.append(
                FieldIssue(f"$.candidate_origin.evidence[{index}]", ORIGIN_EVIDENCE_DUPLICATE, "duplicate identical evidence locator")
            )
        origin_seen.add(key)
        issues.extend(
            _validate_text_locator(f"$.candidate_origin.evidence[{index}]", ref, ctx, require_raw_value=False)
        )

    for group, fields in CORE_GROUPS.items():
        for field_name in fields:
            quantity = (core.get(group) or {}).get(field_name)
            if not isinstance(quantity, dict):
                continue
            base = f"$.core.{group}.{field_name}"
            for index, item in enumerate(quantity.get("direct_evidence") or []):
                source = item.get("source") or {}
                source_path = f"{base}.direct_evidence[{index}].source"
                kind = source.get("kind")
                if kind == "text":
                    issues.extend(_validate_text_locator(source_path, source, ctx, require_raw_value=True))
                elif kind == "ecsv_cell":
                    issues.extend(_validate_ecsv_locator(source_path, source, ctx, allow_component=True))
            for index, item in enumerate(quantity.get("context_evidence") or []):
                issues.extend(
                    _validate_text_locator(f"{base}.context_evidence[{index}]", item, ctx, require_raw_value=False)
                )

    conflicts = payload.get("provenance_conflicts") or []
    conflict_fields: dict[str, int] = {}
    for index, conflict in enumerate(conflicts):
        base = f"$.provenance_conflicts[{index}]"
        field_path = conflict.get("field")
        if field_path in conflict_fields:
            issues.append(
                FieldIssue(base, CONFLICT_FIELD_DUPLICATE, f"field {field_path!r} already has a conflict at index {conflict_fields[field_path]}")
            )
        conflict_fields.setdefault(field_path, index)
        tex_source = conflict.get("tex_source") or {}
        issues.extend(
            _validate_text_locator(f"{base}.tex_source", tex_source, ctx, require_raw_value=False)
        )
        ecsv_source = conflict.get("ecsv_source") or {}
        issues.extend(
            _validate_ecsv_locator(f"{base}.ecsv_source", ecsv_source, ctx, allow_component=False)
        )
        resolution = conflict.get("resolution")
        quantity = quantities.get(field_path)
        if resolution == "use_tex":
            if quantity is None:
                issues.append(
                    FieldIssue(base, CONFLICT_RESOLUTION_INCONSISTENT, "use_tex requires the affected quantity to be non-null")
                )
            else:
                for eindex, item in enumerate(quantity.get("direct_evidence") or []):
                    if (item.get("source") or {}).get("kind") == "ecsv_cell":
                        issues.append(
                            FieldIssue(
                                f"$.core.{field_path}.direct_evidence[{eindex}]",
                                CONFLICT_RESOLUTION_INCONSISTENT,
                                "use_tex forbids the conflicting ECSV cell as direct evidence",
                            )
                        )
        elif resolution == "unresolved":
            if quantity is not None:
                issues.append(
                    FieldIssue(base, CONFLICT_RESOLUTION_INCONSISTENT, "unresolved requires the affected quantity to be null")
                )
    return issues


def _hydrate_text(
    ref: dict[str, Any], ctx: FieldValidationContext, tex_sha256: dict[str, str]
) -> dict[str, Any]:
    resolved = "\n".join(
        ctx.tex_lines(ref["path"])[ref["start_line"] - 1 : ref["end_line"]]
    )
    return {
        **ref,
        "resolved_text": resolved,
        "source_sha256": tex_sha256[ref["path"]],
    }


def _hydrate_source(
    source: dict[str, Any], ctx: FieldValidationContext
) -> dict[str, Any]:
    if source.get("kind") == "text":
        hydrated = dict(source)
        hydrated["quantity_raw_value"] = source["raw_value"]
        return hydrated
    structure = ctx.ecsv_structures[source["path"]]
    row_text = ctx.ecsv_lines(source["path"])[source["line"] - 1]
    cell = cell_at(row_text, structure.columns.index(source["column"]))
    return {
        **source,
        "column_header": structure.column_headers.get(
            source["column"], source["column"]
        ),
        "cell_raw_value": cell,
        "quantity_raw_value": source.get("component_raw_value") or cell,
        "source_sha256": structure.sha256,
    }


def hydrate_quantity(
    quantity: dict[str, Any],
    ctx: FieldValidationContext,
    *,
    tex_sha256: dict[str, str],
) -> dict[str, Any]:
    """Hydrate one standalone quantity (narrow review submissions)."""

    return {
        **quantity,
        "direct_evidence": [
            {
                "part": item["part"],
                "source": (
                    _hydrate_text(item["source"], ctx, tex_sha256)
                    | {"quantity_raw_value": item["source"]["raw_value"]}
                    if item["source"].get("kind") == "text"
                    else _hydrate_source(item["source"], ctx)
                ),
            }
            for item in quantity["direct_evidence"]
        ],
        "context_evidence": [
            _hydrate_text(ref, ctx, tex_sha256)
            for ref in quantity["context_evidence"]
        ],
    }


def hydrate_field_submission(
    payload: dict[str, Any],
    ctx: FieldValidationContext,
    *,
    tex_sha256: dict[str, str],
) -> dict[str, Any]:
    """Hydrate source representations; model-submitted fields stay untouched."""

    def hydrate_text(ref: dict[str, Any]) -> dict[str, Any]:
        return _hydrate_text(ref, ctx, tex_sha256)

    def hydrate_source(source: dict[str, Any]) -> dict[str, Any]:
        if source.get("kind") == "text":
            hydrated = hydrate_text(source)
            hydrated["quantity_raw_value"] = source["raw_value"]
            return hydrated
        return _hydrate_source(source, ctx)

    hydrated: dict[str, Any] = {
        "candidate_origin": {
            **payload["candidate_origin"],
            "evidence": [hydrate_text(ref) for ref in payload["candidate_origin"]["evidence"]],
        },
        "core": {},
        "provenance_conflicts": [
            {
                **conflict,
                "tex_source": hydrate_text(conflict["tex_source"]),
                "ecsv_source": hydrate_source({**conflict["ecsv_source"], "kind": "ecsv_cell"}),
            }
            for conflict in payload.get("provenance_conflicts") or []
        ],
    }
    for group, fields in CORE_GROUPS.items():
        group_out: dict[str, Any] = {}
        for field_name in fields:
            quantity = payload["core"][group][field_name]
            if quantity is None:
                group_out[field_name] = None
                continue
            group_out[field_name] = {
                **quantity,
                "direct_evidence": [
                    {"part": item["part"], "source": hydrate_source(item["source"])}
                    for item in quantity["direct_evidence"]
                ],
                "context_evidence": [
                    hydrate_text(ref) for ref in quantity["context_evidence"]
                ],
            }
        hydrated["core"][group] = group_out
    return hydrated


BIBENTRY_BBL_RE = re.compile(r"\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}")
BIBENTRY_BIB_RE = re.compile(r"@(\w+)\s*[{(]\s*([^,\s{}()]+)\s*,")
BIB_FIELD_NAME_RE = re.compile(r"([A-Za-z][A-Za-z0-9_]*)\s*=")


def _parse_bib_fields(entry_text: str) -> dict[str, str]:
    """Parse ``name = {value}`` or ``name = "value"`` fields with balanced braces."""

    fields: dict[str, str] = {}
    for match in BIB_FIELD_NAME_RE.finditer(entry_text):
        name = match.group(1).lower()
        position = match.end()
        while position < len(entry_text) and entry_text[position] in " \t\n":
            position += 1
        if position >= len(entry_text):
            break
        if entry_text[position] == "{":
            depth = 0
            start = position + 1
            while position < len(entry_text):
                char = entry_text[position]
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        break
                position += 1
            fields[name] = entry_text[start:position].strip()
        elif entry_text[position] == '"':
            end = entry_text.find('"', position + 1)
            if end == -1:
                break
            fields[name] = entry_text[position + 1 : end].strip()
    return fields

RESOLVED = "resolved"
BIBLIOGRAPHY_UNRESOLVED = "bibliography_unresolved"
REASON_SOURCE_MISSING = "bibliography_source_missing"
REASON_KEY_NOT_FOUND = "bibliography_key_not_found"
REASON_KEY_AMBIGUOUS = "bibliography_key_ambiguous"
REASON_ENTRY_UNREADABLE = "bibliography_entry_unreadable"


@dataclass
class BibliographyResolution:
    status: str
    bibkey: str
    reason: str = ""
    reference: dict[str, Any] | None = None
    diagnostics: list[str] = field(default_factory=list)


def resolve_bibliography_key(
    bibkey: str,
    bibliography_sources: list[dict[str, Any]],
    source_dir: Path,
) -> BibliographyResolution:
    """Exact key lookup against the associated bibliography sources.

    No fuzzy author/year/title matching, no nearest-key substitution, no
    external lookup. Unavailable or unresolved metadata is a program-owned
    diagnostic, never a candidate field-extraction failure.
    """

    if not bibliography_sources:
        return BibliographyResolution(
            status=BIBLIOGRAPHY_UNRESOLVED,
            bibkey=bibkey,
            reason=REASON_SOURCE_MISSING,
            diagnostics=["no bibliography sources discovered for the manuscript"],
        )
    matches: list[dict[str, Any]] = []
    diagnostics: list[str] = []
    for source in bibliography_sources:
        path = source_dir / source["path"]
        if source["kind"] == "embedded_thebibliography":
            text = "\n".join(
                path.read_text(encoding="utf-8", errors="replace").split("\n")[
                    source["start_line"] - 1 : source["end_line"]
                ]
            )
        else:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                diagnostics.append(f"{source['path']}: unreadable: {exc}")
                continue
        if source["kind"] == "bib":
            for match in BIBENTRY_BIB_RE.finditer(text):
                if match.group(2) == bibkey:
                    start_line = text.count("\n", 0, match.start()) + 1
                    end_line = text.count("\n", 0, match.end()) + 1
                    brace_start = text.find("{", match.start())
                    depth = 0
                    position = brace_start
                    while position < len(text):
                        char = text[position]
                        if char == "{":
                            depth += 1
                        elif char == "}":
                            depth -= 1
                            if depth == 0:
                                break
                        position += 1
                    entry_text = text[brace_start : position + 1]
                    fields_found = _parse_bib_fields(entry_text)
                    matches.append(
                        {
                            "kind": "bib",
                            "path": source["path"],
                            "start_line": start_line,
                            "end_line": text.count("\n", 0, position) + 1,
                            "entry_type": match.group(1).lower(),
                            "metadata": {
                                key: fields_found[key]
                                for key in ("author", "year", "title", "doi", "bibcode", "eprint")
                                if key in fields_found
                            },
                        }
                    )
        else:
            for match in BIBENTRY_BBL_RE.finditer(text):
                if match.group(1) == bibkey:
                    if source["kind"] == "embedded_thebibliography":
                        offset = source["start_line"]
                    else:
                        offset = 1
                    entry_start = match.start()
                    following = BIBENTRY_BBL_RE.search(text, match.end())
                    entry_end = following.start() if following else len(text)
                    start_line = offset + text.count("\n", 0, entry_start)
                    end_line = offset + text.count("\n", 0, entry_end)
                    matches.append(
                        {
                            "kind": source["kind"],
                            "path": source["path"],
                            "start_line": start_line,
                            "end_line": end_line,
                            "metadata": {},
                        }
                    )
    if not matches:
        return BibliographyResolution(
            status=BIBLIOGRAPHY_UNRESOLVED,
            bibkey=bibkey,
            reason=REASON_KEY_NOT_FOUND,
            diagnostics=diagnostics,
        )
    if len(matches) > 1:
        return BibliographyResolution(
            status=BIBLIOGRAPHY_UNRESOLVED,
            bibkey=bibkey,
            reason=REASON_KEY_AMBIGUOUS,
            diagnostics=diagnostics + [f"key occurs {len(matches)} times"],
        )
    return BibliographyResolution(
        status=RESOLVED,
        bibkey=bibkey,
        reference=matches[0],
        diagnostics=diagnostics,
    )
