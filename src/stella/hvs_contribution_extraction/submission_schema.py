"""Strict contribution-roster submission schema.

One forced function and one strict schema are the sole output contract. The
schema carries only structural guidance; the source-ref path enum is a
runtime value containing exactly the TeX file block names visible in that
request. Range groups carry the full contribution shape because every
expanded member must hold identifiers, contribution_type, note, evidence,
and paper_boundness.
"""

from __future__ import annotations

SUBMIT_CONTRIBUTION_ROSTER = "submit_contribution_roster"

CONTRIBUTION_TYPES = ("candidates_found", "follow_up")
PAPER_BOUNDNESS_STATUSES = (
    "unbound",
    "possibly_unbound",
    "bound",
    "no_overall_conclusion",
    "not_assessed",
)


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


def _source_refs_schema(allowed_paths: list[str], *, min_items: int = 0) -> dict:
    return {
        "type": "array",
        "minItems": min_items,
        "items": _source_ref_schema(allowed_paths),
        "description": (
            "Manuscript source references with exact file path and inclusive "
            "physical line range; use separate references for discontinuous passages."
        ),
    }


def _boundness_schema(allowed_paths: list[str]) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["status", "evidence"],
        "properties": {
            "status": {
                "type": "string",
                "enum": list(PAPER_BOUNDNESS_STATUSES),
                "description": (
                    "The paper's own object-level boundness summary. Every status "
                    "except not_assessed requires at least one evidence locator; "
                    "not_assessed may use an empty evidence list."
                ),
            },
            "evidence": _source_refs_schema(allowed_paths),
        },
    }


def _contribution_core_properties(allowed_paths: list[str]) -> dict:
    return {
        "contribution_type": {
            "type": "string",
            "enum": list(CONTRIBUTION_TYPES),
            "description": (
                "candidates_found when the object enters through this paper's own "
                "systematic search or independent data processing and is retained "
                "as an HVS or unbound candidate; follow_up when it enters because "
                "prior work already treats it as one and this paper performs "
                "substantive object-level research."
            ),
        },
        "contribution_note": {
            "type": "string",
            "minLength": 1,
            "description": (
                "What the current paper actually did to this object, including "
                "important unstructured results beyond the structured vocabulary. "
                "For not_assessed, state that no new boundness conclusion was reported."
            ),
        },
        "contribution_evidence": _source_refs_schema(allowed_paths, min_items=1),
        "paper_boundness": _boundness_schema(allowed_paths),
    }


def build_contribution_roster_submission_schema(allowed_paths: list[str]) -> dict:
    """Compile the submit_contribution_roster parameter schema."""

    core = _contribution_core_properties(allowed_paths)
    refs = lambda: _source_refs_schema(allowed_paths)  # noqa: E731
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["object_contributions", "reviewed_exclusions", "range_groups"],
        "properties": {
            "object_contributions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "identifiers",
                        "contribution_type",
                        "contribution_note",
                        "contribution_evidence",
                        "paper_boundness",
                    ],
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
                        **{key: dict(value) for key, value in core.items()},
                    },
                },
            },
            "reviewed_exclusions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["note", "source_refs"],
                    "properties": {
                        "note": {
                            "type": "string",
                            "minLength": 1,
                            "description": (
                                "Why the excluded object or group was reviewed and "
                                "why it is scientifically relevant."
                            ),
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
                    "required": [
                        "range_notation",
                        "source_refs",
                        *core.keys(),
                    ],
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
                        **{key: dict(value) for key, value in core.items()},
                    },
                },
                "description": (
                    "Contribution groups whose members are individually identifiable "
                    "only through a compressed range notation in the manuscript; every "
                    "expanded member carries this contribution shape."
                ),
            },
        },
    }
