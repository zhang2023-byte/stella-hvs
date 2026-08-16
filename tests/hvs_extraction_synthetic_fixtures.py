"""Value-free synthetic fixtures for the observed extraction failure shapes.

Builders encode abstract failure structures only: a group-level statement
that assigns one limit to every named table member, letter-marked sexagesimal
coordinates, empty-quantity submissions, and mixed uncertainty forms. They
never contain real paper identifiers, object names, or table-specific
exceptions; name parameters exist so deformation tests can prove the
structures are identity-independent.
"""

from __future__ import annotations

from stella.hvs_extraction.field_schema import CORE_GROUPS
from stella.hvs_extraction.field_validate import FieldValidationContext

GROUP_NOTE = "Every star listed in this table has a bound probability below 0.5."
GROUP_NOTE_LINE = 5
COORDINATE_LETTER_RA = "9h05m35.55s"
COORDINATE_COLON_RA = "09:05:35.55"
UNCERTAINTY_LINE = (
    "The Galactic rest-frame speed is 805 +49 -32 km/s "
    "(systematic 12 km/s) for this star."
)


def group_statement_manuscript(names: list[str]) -> str:
    """Abstract manuscript whose table note assigns one limit to all members."""

    lines = [
        "\\documentclass{article}",
        "\\begin{document}",
        "\\section{Results}",
        "\\begin{table}",
        "\\caption{" + GROUP_NOTE + "}\\label{tab:cands}",
    ]
    lines.extend(f"{name} & unbound \\\\" for name in names)
    lines.extend(["\\end{table}", "\\end{document}"])
    return "\n".join(lines) + "\n"


def coordinate_manuscript() -> str:
    """Abstract manuscript printing one coordinate in two representations."""

    return (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        f"The star HVS-K lies at {COORDINATE_LETTER_RA} "
        f"({COORDINATE_COLON_RA}) in the survey field.\n"
        "\\end{document}\n"
    )


def uncertainty_manuscript() -> str:
    """Abstract manuscript printing one asymmetric speed measurement."""

    return (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        f"{UNCERTAINTY_LINE}\n"
        "\\end{document}\n"
    )


def tex_context(manuscript: str) -> FieldValidationContext:
    return FieldValidationContext(
        tex_line_counts={"main.tex": manuscript.count("\n")},
        tex_texts={"main.tex": manuscript},
        ecsv_structures={},
        ecsv_texts={},
    )


def roster_candidate_for_group_note(index: int, name: str) -> dict:
    """Roster record whose qualification anchors to the shared group note."""

    member_line = GROUP_NOTE_LINE + index
    member_text = f"{name} & unbound \\\\"
    note_ref = {
        "path": "main.tex",
        "start_line": GROUP_NOTE_LINE,
        "end_line": GROUP_NOTE_LINE,
        "resolved_text": GROUP_NOTE,
        "source_sha256": "0" * 64,
    }
    return {
        "record_id": f"candidate-{index:03d}",
        "display_name": name,
        "identifiers": [
            {
                "value": name,
                "source_refs": [
                    {
                        "path": "main.tex",
                        "start_line": member_line,
                        "end_line": member_line,
                        "resolved_text": member_text,
                        "source_sha256": "0" * 64,
                    }
                ],
                "recognition": {"kind": "other"},
            }
        ],
        "qualification": {
            "reason": (
                "The table note states every listed star has a bound "
                "probability below 0.5, and the paper retains this star."
            ),
            "source_refs": [note_ref],
        },
    }


def quantity(**overrides) -> dict:
    base = {
        "value": None,
        "error": None,
        "lower_error": None,
        "upper_error": None,
        "unit": None,
        "limit_kind": "none",
        "range_lower": None,
        "range_upper": None,
        "direct_evidence": [],
        "context_evidence": [],
    }
    base.update(overrides)
    return base


def _text_source(start_line: int, end_line: int, raw_value: str) -> dict:
    return {
        "kind": "text",
        "path": "main.tex",
        "start_line": start_line,
        "end_line": end_line,
        "raw_value": raw_value,
    }


def _empty_core() -> dict:
    return {
        group: {field: None for field in fields}
        for group, fields in CORE_GROUPS.items()
    }


def _submission(core: dict) -> dict:
    return {
        "candidate_origin": {
            "origin_type": "introduced_by_this_paper",
            "bibkey": None,
            "evidence": [
                {"kind": "text", "path": "main.tex", "start_line": 3, "end_line": 3}
            ],
        },
        "core": core,
        "provenance_conflicts": [],
    }


def group_bound_probability_submission(*, member_line: int) -> dict:
    """Submission applying the shared group note as an upper limit."""

    core = _empty_core()
    core["bound_assessment"]["bound_probability"] = quantity(
        value="0.5",
        limit_kind="upper_limit",
        direct_evidence=[
            {
                "part": "value",
                "source": _text_source(GROUP_NOTE_LINE, GROUP_NOTE_LINE, "0.5"),
            }
        ],
        context_evidence=[
            {
                "kind": "text",
                "path": "main.tex",
                "start_line": member_line,
                "end_line": member_line,
            }
        ],
    )
    return _submission(core)


def group_null_probability_submission() -> dict:
    """Submission that leaves the group-covered field null."""

    return _submission(_empty_core())


def empty_quantity_submission() -> dict:
    """Submission whose radial velocity object has no numeric component."""

    core = _empty_core()
    core["observed_phase_space"]["radial_velocity"] = quantity()
    return _submission(core)


def coordinate_submission(value: str, coordinate_format: str, unit: str | None) -> dict:
    """Submission printing RA in the requested representation."""

    core = _empty_core()
    core["observed_phase_space"]["ra"] = quantity(
        value=value,
        unit=unit,
        limit_kind="none",
        coordinate_format=coordinate_format,
        direct_evidence=[
            {"part": "value", "source": _text_source(3, 3, value)}
        ],
    )
    return _submission(core)


def mixed_uncertainty_submission() -> dict:
    """Submission mixing symmetric and asymmetric uncertainty forms."""

    core = _empty_core()
    core["derived_kinematics"]["galactic_rest_frame_velocity"] = quantity(
        value="805",
        unit="km/s",
        error="40",
        lower_error="32",
        upper_error="49",
        direct_evidence=[
            {"part": "value", "source": _text_source(3, 3, "805")},
            {"part": "error", "source": _text_source(3, 3, "12")},
            {"part": "lower_error", "source": _text_source(3, 3, "-32")},
            {"part": "upper_error", "source": _text_source(3, 3, "+49")},
        ],
    )
    return _submission(core)
