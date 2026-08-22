"""Synthetic contribution-roster fixtures (fictional objects only).

The manuscript and submissions encode the contribution-first decision cases
from the approved plan with invented identifiers; no real paper, private
gold, or campaign data appears here.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from stella.hvs_extraction.method_config import (
    HvsComponentHashes,
    HvsContextBudget,
    HvsModelRoute,
)
from stella.hvs_extraction.prepare import build_prepared_input, write_prepared_input
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
    note: str,
    boundness_status: str,
    *,
    boundness_lines: list[int] | None = None,
) -> dict:
    boundness_lines = [line] if boundness_lines is None else boundness_lines
    return {
        "identifiers": [{"value": identifier, "source_refs": [_ref(line)]}],
        "contribution_type": contribution_type,
        "contribution_note": note,
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
    "note": "B-2 appears only in background comparison prose with an old cited distance and no current-paper analysis.",
    "source_refs": [_ref(LINE_BACKGROUND)],
}
REJECTED_EXCLUSION = {
    "note": "J9999 is a current-paper search target finally rejected by quality cuts and was never a prior HVS candidate.",
    "source_refs": [_ref(LINE_REJECTED)],
}

RANGE_GROUP = {
    "range_notation": "J10-13",
    "source_refs": [_ref(LINE_RANGE)],
    "contribution_type": "candidates_found",
    "contribution_note": "Each member of the compressed range is retained as an unbound candidate by the paper's search.",
    "contribution_evidence": [_ref(LINE_RANGE)],
    "paper_boundness": {
        "status": "unbound",
        "evidence": [_ref(LINE_RANGE)],
    },
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
    "reviewed_exclusions": [BACKGROUND_EXCLUSION, REJECTED_EXCLUSION],
    "range_groups": [RANGE_GROUP],
}

BOTH_TYPES_SUBMISSION = {
    "object_contributions": [
        SEARCH_CONTRIBUTION,
        SPECTROSCOPY_CONTRIBUTION,
        BOUND_CONTRIBUTION,
    ],
    "reviewed_exclusions": [BACKGROUND_EXCLUSION, REJECTED_EXCLUSION],
    "range_groups": [],
}

EMPTY_SUBMISSION = {
    "object_contributions": [],
    "reviewed_exclusions": [],
    "range_groups": [],
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
    "range_groups": [],
}


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
    from stella.hvs_contribution_extraction.method_config import (
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
        measurement_model=route,
        roster_context_budget=budget(),
        measurement_context_budget=budget(),
        components=HvsComponentHashes(
            rule_profile_sha256={"hvs_contribution_v1": "a" * 64},
            prompt_template_sha256={"contribution_roster_model": "b" * 64},
            submission_schema_sha256={"submit_contribution_roster": "c" * 64},
        ),
    )


def make_workspace(tmp: str, tex: str | None = None, run_dir: Path | None = None) -> Path:
    """Create a workspace with one synthetic paper and a prepared input.

    The prepared input reuses the neutral TeX preparation machinery and is
    stamped with the contribution pipeline's own transient schema name.
    """

    workspace = Path(tmp)
    shutil.copytree(
        Path(__file__).resolve().parents[1] / "skills/hvs-candidates-extraction/rules",
        workspace / "skills/hvs-candidates-extraction/rules",
    )
    paper_dir = workspace / "literature" / ARXIV_ID
    (paper_dir / "arxiv_source").mkdir(parents=True)
    (paper_dir / "arxiv_source" / "main.tex").write_text(
        tex if tex is not None else manuscript_text(), encoding="utf-8"
    )
    artifact = build_prepared_input(
        workspace,
        ARXIV_ID,
        roster_budget=budget(),
        field_budget=budget(),
    )
    assert artifact["status"] == "prepared", artifact.get("failure")
    artifact["schema"] = schema_ref("hvs_contribution_extraction.prepared_input")
    resolved_run_dir = run_dir or (workspace / "local_runs" / "contributions" / RUN_ID)
    write_prepared_input(workspace, RUN_ID, artifact, run_dir=resolved_run_dir)
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
