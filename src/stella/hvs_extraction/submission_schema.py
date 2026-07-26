"""Strict roster submission schemas.

One forced function and one strict schema are the sole output contract. The
schema carries only structural guidance — property names, JSON types, required
fields, cardinality, additional-properties restrictions, and concise semantic
descriptions (no full output example in the initial context). The
source-ref path enum is a runtime value containing exactly the TeX file block
names visible in that request.
"""

from __future__ import annotations

SUBMIT_CANDIDATE_ROSTER = "submit_candidate_roster"
SUBMIT_FINAL_CANDIDATE_ROSTER = "submit_final_candidate_roster"
SUBMIT_ROSTER_FUNCTIONS = (SUBMIT_CANDIDATE_ROSTER, SUBMIT_FINAL_CANDIDATE_ROSTER)


def _source_ref_schema(allowed_paths: list[str]) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["path", "start_line", "end_line"],
        "properties": {
            "path": {
                "type": "string",
                "enum": list(allowed_paths),
                "description": "One TeX file block name visible in this request.",
            },
            "start_line": {
                "type": "integer",
                "minimum": 1,
                "description": "One-based physical start line in the named file.",
            },
            "end_line": {
                "type": "integer",
                "minimum": 1,
                "description": "One-based physical end line, inclusive.",
            },
        },
    }


def _source_refs_schema(allowed_paths: list[str]) -> dict:
    return {
        "type": "array",
        "minItems": 1,
        "items": _source_ref_schema(allowed_paths),
        "description": (
            "Manuscript source references with exact file path and inclusive "
            "physical line range; use separate references for discontinuous passages."
        ),
    }


def build_roster_submission_schema(allowed_paths: list[str]) -> dict:
    """Compile the submit_candidate_roster parameter schema."""

    refs = lambda: _source_refs_schema(allowed_paths)  # noqa: E731
    qualification = {
        "type": "object",
        "additionalProperties": False,
        "required": ["reason", "source_refs"],
        "properties": {
            "reason": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "One-to-three-sentence statement of the "
                    "paper's qualifying final treatment."
                ),
            },
            "source_refs": refs(),
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["candidates", "reviewed_exclusions", "range_groups"],
        "properties": {
            "candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["identifiers", "qualification"],
                    "properties": {
                        "identifiers": {
                            "type": "array",
                            "minItems": 1,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["value", "source_refs"],
                                "properties": {
                                    "value": {
                                        "type": "string",
                                        "minLength": 1,
                                        "description": (
                                            "One paper-visible identifier copied "
                                            "verbatim from the manuscript."
                                        ),
                                    },
                                    "source_refs": refs(),
                                },
                            },
                        },
                        "qualification": qualification,
                    },
                },
            },
            "reviewed_exclusions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["subject", "reason", "source_refs"],
                    "properties": {
                        "subject": {
                            "type": "string",
                            "minLength": 1,
                            "description": "One object or paper-defined group reviewed and excluded.",
                        },
                        "reason": {
                            "type": "string",
                            "minLength": 1,
                            "description": "One-to-three-sentence exclusion reason.",
                        },
                        "source_refs": refs(),
                    },
                },
            },
            "range_groups": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["range_notation", "source_refs", "qualification"],
                    "properties": {
                        "range_notation": {
                            "type": "string",
                            "minLength": 1,
                            "description": (
                                "One compressed range notation copied verbatim from "
                                "the manuscript (e.g. HVS1,4-10,12-24). The program "
                                "expands it into individual identifiers; never expand "
                                "it yourself."
                            ),
                        },
                        "source_refs": refs(),
                        "qualification": qualification,
                    },
                },
                "description": (
                    "Qualifying groups whose members are individually identifiable "
                    "only through a compressed range notation in the manuscript."
                ),
            },
        },
    }
