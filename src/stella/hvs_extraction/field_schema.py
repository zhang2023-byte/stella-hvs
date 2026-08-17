"""Canonical submit_candidate_fields schema compiler.

The fixed nullable core skeleton makes the model consider the entire scored
vocabulary: all 19 field keys are required, each value is one valid quantity
object or null, and missing or extra keys are submission-format errors rather
than values silently added or discarded by code. Runtime enums carry
exactly the TeX block names and selected ECSV paths visible in one request;
in the TeX-only context mode the ECSV source branch is absent, matching the
TeX-only rule profile.
"""

from __future__ import annotations

SUBMIT_CANDIDATE_FIELDS = "submit_candidate_fields"

OBSERVED_PHASE_SPACE = (
    "ra",
    "dec",
    "distance",
    "parallax",
    "proper_motion_ra",
    "proper_motion_dec",
    "radial_velocity",
)
DERIVED_KINEMATICS = (
    "galactocentric_x",
    "galactocentric_y",
    "galactocentric_z",
    "galactocentric_radius",
    "galactocentric_vx",
    "galactocentric_vy",
    "galactocentric_vz",
    "tangential_velocity",
    "galactocentric_tangential_velocity",
    "galactic_rest_frame_velocity",
)
BOUND_ASSESSMENT = ("bound_probability", "unbound_probability")
CORE_GROUPS = {
    "observed_phase_space": OBSERVED_PHASE_SPACE,
    "derived_kinematics": DERIVED_KINEMATICS,
    "bound_assessment": BOUND_ASSESSMENT,
}
CORE_FIELD_PATHS = tuple(
    f"{group}.{field}"
    for group, fields in CORE_GROUPS.items()
    for field in fields
)
COORDINATE_FIELDS = ("ra", "dec")
QUANTITY_PARTS = (
    "value",
    "error",
    "lower_error",
    "upper_error",
    "range_lower",
    "range_upper",
)
COORDINATE_FORMATS = (
    "decimal_degrees",
    "sexagesimal_hms",
    "sexagesimal_dms",
    "sexagesimal_colon",
)


def _string_or_null() -> dict:
    return {"oneOf": [{"type": "string"}, {"type": "null"}]}


def _text_locator_schema(tex_paths: list[str], *, with_raw_value: bool) -> dict:
    required = ["kind", "path", "start_line", "end_line"]
    properties: dict = {
        "kind": {"const": "text"},
        "path": {
            "type": "string",
            "enum": list(tex_paths),
            "description": "One TeX file block name visible in this request.",
        },
        "start_line": {"type": "integer", "minimum": 1},
        "end_line": {"type": "integer", "minimum": 1},
    }
    if with_raw_value:
        required.append("raw_value")
        properties["raw_value"] = {
            "type": "string",
            "minLength": 1,
            "description": (
                "The smallest exact source substring preserving the printed "
                "representation of the numeric component."
            ),
        }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def _ecsv_cell_schema(ecsv_paths: list[str], *, with_component: bool) -> dict:
    required = ["kind", "path", "line", "column"]
    properties: dict = {
        "kind": {"const": "ecsv_cell"},
        "path": {
            "type": "string",
            "enum": list(ecsv_paths),
            "description": "One ECSV file block name visible in this request.",
        },
        "line": {
            "type": "integer",
            "minimum": 1,
            "description": "One-based physical ECSV data-row line.",
        },
        "column": {
            "type": "string",
            "minLength": 1,
            "description": "Exact machine column name.",
        },
    }
    if with_component:
        properties["component_raw_value"] = {
            "type": "string",
            "minLength": 1,
            "description": (
                "Only for a compound cell: the smallest exact substring of the "
                "addressed cell preserving the component's printed representation."
            ),
        }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def _direct_evidence_schema(tex_paths: list[str], ecsv_paths: list[str]) -> dict:
    branches = [_text_locator_schema(tex_paths, with_raw_value=True)]
    if ecsv_paths:
        branches.append(_ecsv_cell_schema(ecsv_paths, with_component=True))
    return {
        "type": "array",
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["part", "source"],
            "properties": {
                "part": {"enum": list(QUANTITY_PARTS)},
                "source": {"oneOf": branches},
            },
        },
    }


def _quantity_schema(tex_paths: list[str], ecsv_paths: list[str], *, coordinate: bool) -> dict:
    required = [
        "value",
        "error",
        "lower_error",
        "upper_error",
        "unit",
        "limit_kind",
        "range_lower",
        "range_upper",
        "direct_evidence",
        "context_evidence",
    ]
    properties: dict = {
        "value": _string_or_null(),
        "error": _string_or_null(),
        "lower_error": _string_or_null(),
        "upper_error": _string_or_null(),
        "unit": _string_or_null(),
        "limit_kind": {"enum": ["none", "lower_limit", "upper_limit", "range"]},
        "range_lower": _string_or_null(),
        "range_upper": _string_or_null(),
        "direct_evidence": _direct_evidence_schema(tex_paths, ecsv_paths),
        "context_evidence": {
            "type": "array",
            "items": _text_locator_schema(tex_paths, with_raw_value=False),
        },
    }
    if coordinate:
        required.append("coordinate_format")
        properties["coordinate_format"] = {"enum": list(COORDINATE_FORMATS)}
    return {
        "oneOf": [
            {"type": "null"},
            {
                "type": "object",
                "additionalProperties": False,
                "required": required,
                "properties": properties,
            },
        ]
    }


def _candidate_origin_schema(tex_paths: list[str]) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["origin_type", "bibkey", "evidence"],
        "properties": {
            "origin_type": {
                "enum": ["introduced_by_this_paper", "cited_from_literature"]
            },
            "bibkey": {
                "oneOf": [{"type": "string", "minLength": 1}, {"type": "null"}]
            },
            "evidence": {
                "type": "array",
                "minItems": 1,
                "items": _text_locator_schema(tex_paths, with_raw_value=False),
            },
        },
    }


def _provenance_conflicts_schema(tex_paths: list[str], ecsv_paths: list[str]) -> dict:
    if not ecsv_paths:
        return {"type": "array", "maxItems": 0}
    return {
        "type": "array",
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": ["field", "tex_source", "ecsv_source", "resolution", "reason"],
            "properties": {
                "field": {"enum": list(CORE_FIELD_PATHS)},
                "tex_source": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["path", "start_line", "end_line"],
                    "properties": {
                        "path": {"type": "string", "enum": list(tex_paths)},
                        "start_line": {"type": "integer", "minimum": 1},
                        "end_line": {"type": "integer", "minimum": 1},
                    },
                },
                "ecsv_source": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["path", "line", "column"],
                    "properties": {
                        "path": {"type": "string", "enum": list(ecsv_paths)},
                        "line": {"type": "integer", "minimum": 1},
                        "column": {"type": "string", "minLength": 1},
                    },
                },
                "resolution": {"enum": ["use_tex", "unresolved"]},
                "reason": {"type": "string", "minLength": 1},
            },
        },
    }


def build_field_submission_schema(
    tex_paths: list[str], ecsv_paths: list[str]
) -> dict:
    """Compile the submit_candidate_fields parameter schema."""

    groups: dict[str, dict] = {}
    for group, fields in CORE_GROUPS.items():
        groups[group] = {
            "type": "object",
            "additionalProperties": False,
            "required": list(fields),
            "properties": {
                field: _quantity_schema(
                    tex_paths, ecsv_paths, coordinate=field in COORDINATE_FIELDS
                )
                for field in fields
            },
        }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["candidate_origin", "core", "provenance_conflicts"],
        "properties": {
            "candidate_origin": _candidate_origin_schema(tex_paths),
            "core": {
                "type": "object",
                "additionalProperties": False,
                "required": list(CORE_GROUPS),
                "properties": groups,
            },
            "provenance_conflicts": _provenance_conflicts_schema(tex_paths, ecsv_paths),
        },
    }


SUBMIT_REVIEWED_FIELDS = "submit_reviewed_fields"


def build_field_review_schema(
    flagged_fields: list[tuple[str, str]],
    tex_paths: list[str],
    ecsv_paths: list[str],
) -> dict:
    """Compile the submit_reviewed_fields parameter schema.

    One quantity slot per flagged core field (``group.field`` keys); nothing
    outside the flagged fields is submittable, so a review response cannot
    rewrite candidate origin, empty unaffected fields, or drop properties.
    """

    properties = {
        f"{group}.{field}": _quantity_schema(
            tex_paths, ecsv_paths, coordinate=field in COORDINATE_FIELDS
        )
        for group, field in flagged_fields
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["core_fields"],
        "properties": {
            "core_fields": {
                "type": "object",
                "additionalProperties": False,
                "required": list(properties),
                "properties": properties,
            }
        },
    }
