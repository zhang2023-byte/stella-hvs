"""Deterministic grouped-measurement validation and hydration.

Reuses the neutral V6 quantity, coordinate, locator, and hydration
primitives without modification: their semantics are identical per value.
New checks cover the grouped-multiset contract (vocabulary, one group per
field, non-empty values, exact-duplicate rejection) and per-value
condition/preference/provenance presence. Code never guesses or corrects a
bibkey and never rewrites a submitted citation string.
"""

from __future__ import annotations

import json
from typing import Any

from stella.hvs_extraction.field_validate import (
    DIRECT_EVIDENCE_MISSING,
    FieldIssue,
    FieldValidationContext,
    _hydrate_source,
    _hydrate_text,
    _issues_for_coordinate,
    _issues_for_quantity,
    _validate_ecsv_locator,
    _validate_text_locator,
)

__all__ = [
    "DIRECT_EVIDENCE_MISSING",
    "FIELD_NOT_IN_VOCABULARY",
    "FIELD_DUPLICATE_GROUP",
    "VALUES_EMPTY",
    "VALUE_DUPLICATE",
    "CONDITION_NOTE_REQUIRED",
    "PAPER_PREFERRED_REQUIRED",
    "SOURCE_REQUIRED",
    "SOURCE_KIND_INVALID",
    "CITATION_NOT_VERBATIM",
    "BIBKEY_NOT_VERBATIM",
    "COORDINATE_FORMAT_REQUIRED",
    "validate_measurement_submission",
    "hydrate_measurement_submission",
    "measurement_allowed_roots",
]
from stella.hvs_contribution_extraction.measurement_schema import (
    COORDINATE_FIELD_PATHS,
    SOURCE_KINDS,
)
from stella.lit.schema_specs import HVS_CONTRIBUTION_MEASUREMENT_FIELDS

# Grouped-multiset invariant codes.
FIELD_NOT_IN_VOCABULARY = "field_not_in_vocabulary"
FIELD_DUPLICATE_GROUP = "field_duplicate_group"
VALUES_EMPTY = "values_empty"
VALUE_DUPLICATE = "value_duplicate"
CONDITION_NOTE_REQUIRED = "condition_note_required"
PAPER_PREFERRED_REQUIRED = "paper_preferred_required"
SOURCE_REQUIRED = "source_required"
SOURCE_KIND_INVALID = "source_kind_invalid"
CITATION_NOT_VERBATIM = "citation_not_verbatim"
BIBKEY_NOT_VERBATIM = "bibkey_not_verbatim"
COORDINATE_FORMAT_REQUIRED = "coordinate_format_required"

_COORDINATE_SIMPLE_NAMES = {path.rsplit(".", 1)[1] for path in COORDINATE_FIELD_PATHS}


def _value_key(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def validate_measurement_submission(
    payload: dict[str, Any], ctx: FieldValidationContext
) -> list[FieldIssue]:
    """Run every deterministic structural, locator, and multiset check."""

    issues: list[FieldIssue] = []
    seen_fields: dict[str, int] = {}
    for gi, group in enumerate(payload.get("measurements") or []):
        base = f"$.measurements[{gi}]"
        field_path = group.get("field")
        if field_path not in HVS_CONTRIBUTION_MEASUREMENT_FIELDS:
            issues.append(
                FieldIssue(
                    f"{base}.field",
                    FIELD_NOT_IN_VOCABULARY,
                    f"field {field_path!r} is not in the nineteen-field vocabulary",
                )
            )
        elif field_path in seen_fields:
            issues.append(
                FieldIssue(
                    f"{base}.field",
                    FIELD_DUPLICATE_GROUP,
                    f"field {field_path!r} already has a group at index {seen_fields[field_path]}",
                )
            )
        else:
            seen_fields[field_path] = gi

        values = group.get("values") or []
        if not values:
            issues.append(
                FieldIssue(f"{base}.values", VALUES_EMPTY, "each field group needs at least one value")
            )
        seen_value_keys: set[str] = set()
        for vi, value in enumerate(values):
            value_path = f"{base}.values[{vi}]"
            key = _value_key(value)
            if key in seen_value_keys:
                issues.append(
                    FieldIssue(
                        value_path,
                        VALUE_DUPLICATE,
                        "an exactly identical value record was already submitted in this field group",
                    )
                )
            seen_value_keys.add(key)

            if "condition_note" not in value:
                issues.append(
                    FieldIssue(f"{value_path}.condition_note", CONDITION_NOTE_REQUIRED, "condition_note is required on every value")
                )
            if "paper_preferred" not in value:
                issues.append(
                    FieldIssue(f"{value_path}.paper_preferred", PAPER_PREFERRED_REQUIRED, "paper_preferred is required on every value (true, false, or null)")
                )
            source = value.get("source")
            if not isinstance(source, dict):
                issues.append(
                    FieldIssue(f"{value_path}.source", SOURCE_REQUIRED, "source is required on every value")
                )
            else:
                if source.get("kind") not in SOURCE_KINDS:
                    issues.append(
                        FieldIssue(
                            f"{value_path}.source.kind",
                            SOURCE_KIND_INVALID,
                            f"source.kind must be one of {SOURCE_KINDS}",
                        )
                    )
                citation = source.get("paper_visible_citation")
                bibkey = source.get("bibkey")
                citation_refs = source.get("citation_evidence") or []
                if (citation or bibkey) and citation_refs:
                    resolved_any = False
                    citation_found = not citation
                    bibkey_found = not bibkey
                    for ri, ref in enumerate(citation_refs):
                        ref_issues = _validate_text_locator(
                            f"{value_path}.source.citation_evidence[{ri}]", ref, ctx, require_raw_value=False
                        )
                        issues.extend(ref_issues)
                        if ref_issues:
                            continue
                        resolved = "\n".join(
                            ctx.tex_lines(ref["path"])[ref["start_line"] - 1 : ref["end_line"]]
                        )
                        resolved_any = True
                        if citation and citation in resolved:
                            citation_found = True
                        if bibkey and bibkey in resolved:
                            bibkey_found = True
                    if resolved_any:
                        if not citation_found:
                            issues.append(
                                FieldIssue(
                                    f"{value_path}.source.paper_visible_citation",
                                    CITATION_NOT_VERBATIM,
                                    "the rendered citation does not occur verbatim in its citation evidence",
                                )
                            )
                        if not bibkey_found:
                            issues.append(
                                FieldIssue(
                                    f"{value_path}.source.bibkey",
                                    BIBKEY_NOT_VERBATIM,
                                    "the bibkey does not occur verbatim in its citation evidence",
                                )
                            )

            issues.extend(_issues_for_quantity(value_path, value))
            if field_path in COORDINATE_FIELD_PATHS:
                coordinate_name = field_path.rsplit(".", 1)[1]
                if value.get("coordinate_format") is None:
                    issues.append(
                        FieldIssue(
                            f"{value_path}.coordinate_format",
                            COORDINATE_FORMAT_REQUIRED,
                            "coordinate values require coordinate_format",
                        )
                    )
                else:
                    issues.extend(_issues_for_coordinate(value_path, coordinate_name, value))

            for di, item in enumerate(value.get("direct_evidence") or []):
                source_ref = item.get("source") or {}
                source_path = f"{value_path}.direct_evidence[{di}].source"
                if source_ref.get("kind") == "text":
                    issues.extend(_validate_text_locator(source_path, source_ref, ctx, require_raw_value=True))
                elif source_ref.get("kind") == "ecsv_cell":
                    issues.extend(_validate_ecsv_locator(source_path, source_ref, ctx, allow_component=True))
            for ci, ref in enumerate(value.get("context_evidence") or []):
                issues.extend(
                    _validate_text_locator(f"{value_path}.context_evidence[{ci}]", ref, ctx, require_raw_value=False)
                )
    return issues


def hydrate_measurement_submission(
    payload: dict[str, Any],
    ctx: FieldValidationContext,
    *,
    tex_sha256: dict[str, str],
) -> dict[str, Any]:
    """Hydrate source representations; model-submitted values stay untouched."""

    def hydrate_text(ref: dict[str, Any]) -> dict[str, Any]:
        return _hydrate_text(ref, ctx, tex_sha256)

    def hydrate_direct(item: dict[str, Any]) -> dict[str, Any]:
        source = item["source"]
        if source.get("kind") == "text":
            hydrated = hydrate_text(source)
            hydrated["quantity_raw_value"] = source["raw_value"]
            return {"part": item["part"], "source": hydrated}
        return {"part": item["part"], "source": _hydrate_source(source, ctx)}

    def hydrate_value(value: dict[str, Any]) -> dict[str, Any]:
        source = value.get("source") or {}
        return {
            **value,
            "source": {
                **source,
                "citation_evidence": [
                    hydrate_text(ref) for ref in source.get("citation_evidence") or []
                ],
            },
            "direct_evidence": [hydrate_direct(item) for item in value.get("direct_evidence") or []],
            "context_evidence": [hydrate_text(ref) for ref in value.get("context_evidence") or []],
        }

    return {
        "measurements": [
            {
                "field": group["field"],
                "values": [hydrate_value(value) for value in group.get("values") or []],
            }
            for group in payload.get("measurements") or []
        ]
    }


def measurement_allowed_roots(issues: list[Any]) -> set[str]:
    """Smallest replaceable subtree per issue: one value, one group, or the list.

    Multiset semantics make the individual value the natural replacement
    unit; a whole field group may also be replaced when its identity itself
    is wrong.
    """

    roots: set[str] = set()
    for issue in issues:
        path = issue.path
        if path.startswith("$.measurements[") and ".values[" in path:
            head = path.split(".values[", 1)[0]
            value_index = path.split(".values[", 1)[1].split("]", 1)[0]
            roots.add(f"{head}.values[{value_index}]")
        elif path.startswith("$.measurements["):
            roots.add(path.split("].", 1)[0] + "]")
        else:
            roots.add(path)
    return roots
