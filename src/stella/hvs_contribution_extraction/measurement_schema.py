"""Strict grouped-measurement submission schema.

One forced function and one strict schema are the sole output contract. The
contract is a field-grouped multiset: each measurement entry is one field and
its non-empty values list. There is no measurement ID, no sequence number, no
scenarios array, and no scenario reference anywhere in this contract.
"""

from __future__ import annotations

from stella.lit.schema_specs import HVS_CONTRIBUTION_MEASUREMENT_FIELDS

SUBMIT_OBJECT_MEASUREMENTS = "submit_object_measurements"

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
COORDINATE_FIELD_PATHS = ("observed_phase_space.ra", "observed_phase_space.dec")
SOURCE_KINDS = ("this_paper", "prior_work", "unclear")


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


def _ecsv_cell_schema(ecsv_paths: list[str]) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "path", "line", "column"],
        "properties": {
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
            "component_raw_value": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "Only for a compound cell: the smallest exact substring of the "
                    "addressed cell preserving the component's printed representation."
                ),
            },
        },
    }


def _direct_evidence_schema(tex_paths: list[str], ecsv_paths: list[str]) -> dict:
    branches = [_text_locator_schema(tex_paths, with_raw_value=True)]
    if ecsv_paths:
        branches.append(_ecsv_cell_schema(ecsv_paths))
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


def _source_schema(tex_paths: list[str]) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "paper_visible_citation", "bibkey", "citation_evidence"],
        "properties": {
            "kind": {
                "enum": list(SOURCE_KINDS),
                "description": (
                    "Provenance of the value, orthogonal to preference: a "
                    "prior-work value may be this paper's preferred adopted input."
                ),
            },
            "paper_visible_citation": {
                "oneOf": [{"type": "string", "minLength": 1}, {"type": "null"}],
                "description": (
                    "The paper-visible rendered citation exactly as printed; null "
                    "only when the paper supplies no rendered citation."
                ),
            },
            "bibkey": {
                "oneOf": [{"type": "string", "minLength": 1}, {"type": "null"}],
                "description": (
                    "A TeX bibkey only when reliably recoverable from the supplied "
                    "source; never guess one."
                ),
            },
            "citation_evidence": {
                "type": "array",
                "items": _text_locator_schema(tex_paths, with_raw_value=False),
            },
        },
    }


def _value_schema(tex_paths: list[str], ecsv_paths: list[str]) -> dict:
    required = [
        "value",
        "error",
        "lower_error",
        "upper_error",
        "unit",
        "limit_kind",
        "range_lower",
        "range_upper",
        "condition_note",
        "paper_preferred",
        "source",
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
        "coordinate_format": {
            "enum": list(COORDINATE_FORMATS),
            "_applies_to": list(COORDINATE_FIELD_PATHS),
            "description": (
                "Required only for ra and dec values; deterministic validation "
                "rejects a coordinate value without its format."
            ),
        },
        "condition_note": {
            "type": "string",
            "description": (
                "The potential, prior, method, epoch, data release, or other "
                "condition this value belongs to; empty only when the paper states "
                "no condition or distinction."
            ),
        },
        "paper_preferred": {
            "oneOf": [{"type": "boolean"}, {"type": "null"}],
            "description": (
                "true only when the paper explicitly calls the value adopted, "
                "preferred, fiducial, final, recommended, current, or a replacement "
                "used for its analysis; false only when explicitly superseded, "
                "replaced, rejected, non-adopted, or an alternative; null when the "
                "paper gives no explicit preference."
            ),
        },
        "source": _source_schema(tex_paths),
        "direct_evidence": _direct_evidence_schema(tex_paths, ecsv_paths),
        "context_evidence": {
            "type": "array",
            "items": _text_locator_schema(tex_paths, with_raw_value=False),
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def build_measurement_submission_schema(
    tex_paths: list[str], ecsv_paths: list[str]
) -> dict:
    """Compile the submit_object_measurements parameter schema."""

    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["measurements"],
        "properties": {
            "measurements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["field", "values"],
                    "properties": {
                        "field": {
                            "enum": list(HVS_CONTRIBUTION_MEASUREMENT_FIELDS),
                            "description": (
                                "One of the nineteen structured fields; each field "
                                "occurs at most once per object."
                            ),
                        },
                        "values": {
                            "type": "array",
                            "minItems": 1,
                            "items": _value_schema(tex_paths, ecsv_paths),
                            "description": (
                                "Every explicitly object-attributed value of this "
                                "field as an unordered multiset; array order is never "
                                "scored."
                            ),
                        },
                    },
                },
                "description": (
                    "All grouped measurements for the assigned contribution."
                ),
            }
        },
    }
