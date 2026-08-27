"""Synthetic contribution-roster fixtures (fictional objects only).

The manuscript and submissions encode the contribution-first decision cases
from the approved plan with invented identifiers; no real paper, private
gold, or campaign data appears here.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from stella.lit.extraction.method_config import (
    HvsComponentHashes,
    HvsContextBudget,
    HvsModelRoute,
)
from stella.lit.extraction.prepare import build_prepared_input, write_prepared_input
from stella.schema_registry import schema_ref

ARXIV_ID = "2601.09999"
RUN_ID = "run-contribution-roster-test"

MANUSCRIPT_LINES = [
    "\\documentclass{article}",
    "\\begin{document}",
    "Our systematic search of the archival survey selects J1234 and retains it as an unbound candidate, even though the object was previously catalogued.",
    "The prior HVS candidate HVS-7 receives new spectroscopy here; we derive its atmospheric parameters but do not reassess its Galactic boundness.",
    "We remeasure the prior unbound candidate HVS-9 and conclude that it is bound to the Galaxy.",
    "Star B-2 was noted in earlier work as fast; we cite its old distance of 5.1 kpc for background comparison only.",
    "Search target J9999 fails our quality cuts and is rejected; it was never proposed as an HVS candidate.",
    "Under potential A the speed of J2001 exceeds the escape velocity, while under potential B it does not; overall we conclude J2001 is unbound.",
    "For J2002 the survey implies unbound speeds under one model and bound speeds under another, with no synthesis offered.",
    "The analysis reports P_unbound = 0.62 for J2003 with no further verbal conclusion.",
    "The selected sample also contains J10-13, each retained as an unbound candidate by our search.",
    "\\end{document}",
]

LINE_SEARCH = 3
LINE_SPECTROSCOPY = 4
LINE_BOUND = 5
LINE_BACKGROUND = 6
LINE_REJECTED = 7
LINE_SYNTHESIS = 8
LINE_NO_SYNTHESIS = 9
LINE_NUMERIC_ONLY = 10
LINE_RANGE = 11


def manuscript_text() -> str:
    return "\n".join(MANUSCRIPT_LINES) + "\n"


def _ref(line: int) -> dict:
    return {"path": "main.tex", "start_line": line, "end_line": line}


def contribution(
    identifier: str,
    line: int,
    contribution_type: str,
    summary: str,
    boundness_status: str,
    *,
    boundness_lines: list[int] | None = None,
) -> dict:
    boundness_lines = [line] if boundness_lines is None else boundness_lines
    return {
        "identifiers": [{"value": identifier, "source_refs": [_ref(line)]}],
        "contribution_type": contribution_type,
        "contribution_summary": summary,
        "contribution_evidence": [_ref(line)],
        "paper_boundness": {
            "status": boundness_status,
            "evidence": [_ref(item) for item in boundness_lines],
        },
    }


SEARCH_CONTRIBUTION = contribution(
    "J1234",
    LINE_SEARCH,
    "candidates_found",
    "The paper's own systematic archival search selects J1234 and retains it as an unbound candidate.",
    "unbound",
)
SPECTROSCOPY_CONTRIBUTION = contribution(
    "HVS-7",
    LINE_SPECTROSCOPY,
    "follow_up",
    "The paper performs new spectroscopy on the prior HVS candidate HVS-7 and derives atmospheric parameters; no new boundness conclusion was reported.",
    "not_assessed",
)
BOUND_CONTRIBUTION = contribution(
    "HVS-9",
    LINE_BOUND,
    "follow_up",
    "The paper remeasures the prior unbound candidate HVS-9 and concludes it is bound to the Galaxy.",
    "bound",
)
SYNTHESIS_CONTRIBUTION = contribution(
    "J2001",
    LINE_SYNTHESIS,
    "candidates_found",
    "The paper's search retains J2001 and explicitly synthesizes the two potential scenarios into one overall unbound conclusion.",
    "unbound",
)
NO_SYNTHESIS_CONTRIBUTION = contribution(
    "J2002",
    LINE_NO_SYNTHESIS,
    "candidates_found",
    "The paper retains J2002 but reports incompatible conditional speeds without an overall synthesis.",
    "no_overall_conclusion",
)
NUMERIC_ONLY_CONTRIBUTION = contribution(
    "J2003",
    LINE_NUMERIC_ONLY,
    "candidates_found",
    "The paper reports only a numeric unbound probability for J2003 with no verbal conclusion.",
    "no_overall_conclusion",
)

BACKGROUND_EXCLUSION = {
    "reason": "B-2 appears only in background comparison prose with an old cited distance and no current-paper analysis.",
    "source_refs": [_ref(LINE_BACKGROUND)],
}
REJECTED_EXCLUSION = {
    "reason": "J9999 is a current-paper search target finally rejected by quality cuts and was never a prior HVS candidate.",
    "source_refs": [_ref(LINE_REJECTED)],
}

RANGE_NOTATION_EXCLUSION = {
    "reason": "The sample line names J10-13 only through a compressed range notation, so its members are not individually identifiable in the manuscript.",
    "source_refs": [_ref(LINE_RANGE)],
}

FULL_SUBMISSION = {
    "object_contributions": [
        SEARCH_CONTRIBUTION,
        SPECTROSCOPY_CONTRIBUTION,
        BOUND_CONTRIBUTION,
        SYNTHESIS_CONTRIBUTION,
        NO_SYNTHESIS_CONTRIBUTION,
        NUMERIC_ONLY_CONTRIBUTION,
    ],
    "reviewed_exclusions": [
        BACKGROUND_EXCLUSION,
        REJECTED_EXCLUSION,
        RANGE_NOTATION_EXCLUSION,
    ],
}

BOTH_TYPES_SUBMISSION = {
    "object_contributions": [
        SEARCH_CONTRIBUTION,
        SPECTROSCOPY_CONTRIBUTION,
        BOUND_CONTRIBUTION,
    ],
    "reviewed_exclusions": [BACKGROUND_EXCLUSION, REJECTED_EXCLUSION],
}

EMPTY_SUBMISSION = {
    "object_contributions": [],
    "reviewed_exclusions": [],
}

EXTERNAL_KNOWLEDGE_SUBMISSION = {
    "object_contributions": [
        contribution(
            "HVS-77",
            LINE_SEARCH,
            "follow_up",
            "External fixture knowledge says this is a prior candidate, but the current paper never mentions it.",
            "not_assessed",
        )
    ],
    "reviewed_exclusions": [],
}


# ---------------------------------------------------------------------------
# Measurement fixtures (grouped multivalue cases).

MEASUREMENT_ARXIV_ID = "2601.08888"
MEASUREMENT_RUN_ID = "run-contribution-measurement-test"

MEASUREMENT_MANUSCRIPT_LINES = [
    "\\documentclass{article}",
    "\\begin{document}",
    "The distance to J1234 is 8.2 $\\pm$ 0.3 kpc in our fiducial model.",
    "Under the alternative potential the distance is 8.6 $\\pm$ 0.4 kpc.",
    "We adopt the distance 7.9 $\\pm$ 0.4 kpc of Smith et al. (2020) \\citep{smith2020} for comparison.",
    "Our earlier reported distance 7.5 $\\pm$ 0.5 kpc is superseded.",
    "The escape analysis yields P_unbound = 0.92 for J1234.",
    "J1234 lies at RA 09h05m35.55s, Dec +10d20m30s.",
    "\\end{document}",
]

M_LINE_FIDUCIAL = 3
M_LINE_ALTERNATIVE = 4
M_LINE_PRIOR = 5
M_LINE_SUPERSEDED = 6
M_LINE_PROBABILITY = 7
M_LINE_COORDINATES = 8


def measurement_manuscript_text() -> str:
    return "\n".join(MEASUREMENT_MANUSCRIPT_LINES) + "\n"


def _m_ref(line: int) -> dict:
    return {"kind": "text", "path": "main.tex", "start_line": line, "end_line": line}


def _r_ref(line: int) -> dict:
    """Roster source refs carry no kind (the roster schema is path/lines only)."""

    return {"path": "main.tex", "start_line": line, "end_line": line}


def _direct(line: int, part: str, raw: str) -> dict:
    return {
        "part": part,
        "source": {"kind": "text", "path": "main.tex", "start_line": line, "end_line": line, "raw_value": raw},
    }


def measurement_value(**overrides):
    value = {
        "value": "8.2",
        "error": "0.3",
        "lower_error": None,
        "upper_error": None,
        "unit": "kpc",
        "limit_kind": "none",
        "range_lower": None,
        "range_upper": None,
        "condition": "Fiducial model.",
        "paper_preferred": True,
        "source": "this_paper",
        "direct_evidence": [
            _direct(M_LINE_FIDUCIAL, "value", "8.2"),
            _direct(M_LINE_FIDUCIAL, "error", "0.3"),
        ],
        "context_evidence": [_m_ref(M_LINE_FIDUCIAL)],
        "source_note": "",
    }
    value.update(overrides)
    return value


def alternative_value(**overrides):
    value = measurement_value(
        value="8.6",
        error="0.4",
        condition="Alternative potential.",
        paper_preferred=None,
        direct_evidence=[
            _direct(M_LINE_ALTERNATIVE, "value", "8.6"),
            _direct(M_LINE_ALTERNATIVE, "error", "0.4"),
        ],
        context_evidence=[_m_ref(M_LINE_ALTERNATIVE)],
    )
    value.update(overrides)
    return value


def prior_adopted_value(**overrides):
    value = measurement_value(
        value="7.9",
        error="0.4",
        condition="Literature value adopted for comparison.",
        paper_preferred=None,
        source="prior_work",
        direct_evidence=[
            _direct(M_LINE_PRIOR, "value", "7.9"),
            _direct(M_LINE_PRIOR, "error", "0.4"),
        ],
        context_evidence=[_m_ref(M_LINE_PRIOR)],
        source_note="The paper attributes this value to Smith et al. (2020).",
    )
    value.update(overrides)
    return value


def superseded_value(**overrides):
    value = measurement_value(
        value="7.5",
        error="0.5",
        condition="Superseded historical value.",
        paper_preferred=False,
        direct_evidence=[
            _direct(M_LINE_SUPERSEDED, "value", "7.5"),
            _direct(M_LINE_SUPERSEDED, "error", "0.5"),
        ],
        context_evidence=[_m_ref(M_LINE_SUPERSEDED)],
    )
    value.update(overrides)
    return value


def probability_value(**overrides):
    value = measurement_value(
        value="0.92",
        error=None,
        unit=None,
        condition="Escape analysis.",
        paper_preferred=None,
        direct_evidence=[_direct(M_LINE_PROBABILITY, "value", "0.92")],
        context_evidence=[_m_ref(M_LINE_PROBABILITY)],
    )
    value.update(overrides)
    return value


def coordinate_value(**overrides):
    value = measurement_value(
        value="09h05m35.55s",
        error=None,
        unit="h",
        coordinate_format="sexagesimal_hms",
        condition="Printed coordinate.",
        paper_preferred=None,
        direct_evidence=[_direct(M_LINE_COORDINATES, "value", "09h05m35.55s")],
        context_evidence=[_m_ref(M_LINE_COORDINATES)],
    )
    value.update(overrides)
    return value


MEASUREMENT_SUBMISSION = {
    "quantities": [
        {
            "quantity": "observed_phase_space.distance",
            "values": [
                measurement_value(),
                alternative_value(),
                prior_adopted_value(),
                superseded_value(),
            ],
        },
        {
            "quantity": "bound_assessment.unbound_probability",
            "values": [probability_value()],
        },
        {
            "quantity": "observed_phase_space.ra",
            "values": [coordinate_value()],
        },
    ]
}

MEASUREMENT_ROSTER_SUBMISSION = {
    "object_contributions": [
        {
            "identifiers": [
                {"value": "J1234", "source_refs": [_r_ref(M_LINE_FIDUCIAL)]}
            ],
            "contribution_type": "candidates_found",
            "contribution_summary": "The paper's analysis retains J1234 as an unbound candidate.",
            "contribution_evidence": [_r_ref(M_LINE_FIDUCIAL)],
            "paper_boundness": {
                "status": "unbound",
                "evidence": [_r_ref(M_LINE_PROBABILITY)],
            },
        }
    ],
    "reviewed_exclusions": [],
}


def make_measurement_workspace(tmp: str, tex: str | None = None) -> Path:
    """Workspace with the measurement manuscript, prepared input, and roster."""

    workspace = Path(tmp)
    shutil.copytree(
        Path(__file__).resolve().parents[1] / "contracts/hvs-contributions/rules",
        workspace / "contracts/hvs-contributions/rules",
    )
    paper_dir = workspace / "literature" / MEASUREMENT_ARXIV_ID
    (paper_dir / "arxiv_source").mkdir(parents=True)
    (paper_dir / "arxiv_source" / "main.tex").write_text(
        tex if tex is not None else measurement_manuscript_text(), encoding="utf-8"
    )
    artifact = build_prepared_input(
        workspace,
        MEASUREMENT_ARXIV_ID,
        roster_budget=budget(),
        field_budget=budget(),
    )
    assert artifact["status"] == "prepared", artifact.get("failure")
    artifact["schema"] = schema_ref("hvs_contribution_extraction.prepared_input")
    run_dir = workspace / "runs" / "hvs-contribution-extraction" / MEASUREMENT_RUN_ID
    write_prepared_input(workspace, MEASUREMENT_RUN_ID, artifact, run_dir=run_dir)
    roster = {
        "schema": schema_ref("hvs_contribution_extraction.roster_final"),
        "generated_at": "2026-08-22T00:00:00+00:00",
        "paper": {"arxiv_id": MEASUREMENT_ARXIV_ID},
        "run_id": MEASUREMENT_RUN_ID,
        "status": "roster_complete",
        "roster_status": "contributions_found",
        "failure": None,
        "object_contributions": [
            {
                "record_id": "obj-001",
                "identifiers": [
                    {
                        "value": "J1234",
                        "source_refs": [_m_ref(M_LINE_FIDUCIAL)],
                        "recognition": {"kind": "other"},
                    }
                ],
                "contribution_type": "candidates_found",
                "contribution_summary": "The paper's search retains J1234 as an unbound candidate.",
                "contribution_evidence": [
                    {
                        "path": "main.tex",
                        "start_line": M_LINE_FIDUCIAL,
                        "end_line": M_LINE_FIDUCIAL,
                        "resolved_text": "placeholder",
                        "source_sha256": "0" * 64,
                    }
                ],
                "paper_boundness": {
                    "status": "unbound",
                    "evidence": [
                        {
                            "path": "main.tex",
                            "start_line": M_LINE_FIDUCIAL,
                            "end_line": M_LINE_FIDUCIAL,
                            "resolved_text": "placeholder",
                            "source_sha256": "0" * 64,
                        }
                    ],
                },
            }
        ],
        "reviewed_exclusions": [],
    }
    roster_paper_dir = run_dir / "papers" / MEASUREMENT_ARXIV_ID
    roster_paper_dir.mkdir(parents=True, exist_ok=True)
    (roster_paper_dir / "contribution_roster_final.json").write_text(
        json.dumps(roster, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return workspace


def budget() -> HvsContextBudget:
    return HvsContextBudget(
        model_context_limit=900000,
        reserve_system_and_rules=8000,
        reserve_tool_schema=4000,
        reserve_candidate_suffix=0,
        reserve_output=8000,
        reserve_provider_framing=1000,
    )


def frozen_contribution_config() -> "HvsContributionMethodConfig":  # noqa: F821
    from stella.lit.extraction.method_config import (
        HvsContributionMethodConfig,
    )

    # A declared structured-output route; the fake transport makes no call.
    route = HvsModelRoute(
        provider="deepseek",
        model="deepseek-v4-pro",
        structured_output_mode="tool_submission",
        temperature=0.0,
        top_p=1.0,
        seed_honored=True,
    )
    return HvsContributionMethodConfig(
        roster_model=route,
        quantity_model=route,
        roster_context_budget=budget(),
        quantity_context_budget=budget(),
        components=HvsComponentHashes(
            rule_profile_sha256={"hvs_contribution_v1": "a" * 64},
            prompt_template_sha256={"contribution_roster_model": "b" * 64},
            submission_schema_sha256={"submit_contribution_roster": "c" * 64},
        ),
    )


def make_workspace(tmp: str, tex: str | None = None, run_dir: Path | None = None) -> Path:
    """Create a workspace with one synthetic paper, prepared input, and roster.

    The prepared input reuses the neutral TeX preparation machinery and is
    stamped with the contribution pipeline's own transient schema name; the
    staged roster is the finalized FULL_SUBMISSION (six direct contributions
    plus three reviewed exclusions).
    """

    workspace = Path(tmp)
    shutil.copytree(
        Path(__file__).resolve().parents[1] / "contracts/hvs-contributions/rules",
        workspace / "contracts/hvs-contributions/rules",
    )
    paper_dir = workspace / "literature" / ARXIV_ID
    (paper_dir / "arxiv_source").mkdir(parents=True)
    manuscript = tex if tex is not None else manuscript_text()
    (paper_dir / "arxiv_source" / "main.tex").write_text(manuscript, encoding="utf-8")
    artifact = build_prepared_input(
        workspace,
        ARXIV_ID,
        roster_budget=budget(),
        field_budget=budget(),
    )
    assert artifact["status"] == "prepared", artifact.get("failure")
    artifact["schema"] = schema_ref("hvs_contribution_extraction.prepared_input")
    resolved_run_dir = run_dir or (
        workspace / "runs" / "hvs-contribution-extraction" / RUN_ID
    )
    write_prepared_input(workspace, RUN_ID, artifact, run_dir=resolved_run_dir)

    from stella.lit.extraction.roster_stage import (
        finalize_contribution_roster,
    )

    contributions, exclusions, roster_status = finalize_contribution_roster(
        FULL_SUBMISSION,
        original_texts={"main.tex": manuscript},
        file_sha256={"main.tex": hashlib.sha256(manuscript.encode("utf-8")).hexdigest()},
    )
    roster = {
        "schema": schema_ref("hvs_contribution_extraction.roster_final"),
        "generated_at": "2026-08-22T00:00:00+00:00",
        "paper": {"arxiv_id": ARXIV_ID},
        "run_id": RUN_ID,
        "status": "roster_complete",
        "roster_status": roster_status,
        "failure": None,
        "object_contributions": contributions,
        "reviewed_exclusions": exclusions,
        "proposals": {"slots": []},
        "provenance": None,
    }
    roster_paper_dir = resolved_run_dir / "papers" / ARXIV_ID
    roster_paper_dir.mkdir(parents=True, exist_ok=True)
    (roster_paper_dir / "contribution_roster_final.json").write_text(
        json.dumps(roster, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return workspace


def fake_response(payload: dict, *, tool_name: str) -> dict:
    return {
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(payload, ensure_ascii=False),
                            },
                        },
                    ],
                },
            }
        ]
    }


def fake_content_response(payload: dict) -> dict:
    return {
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            }
        ]
    }


def tool_name_of(kwargs: dict) -> str:
    return kwargs["extra_body"]["tools"][0]["function"]["name"]


class RecordingTransport:
    def __init__(self, handler) -> None:
        self.handler = handler
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.handler(kwargs)
