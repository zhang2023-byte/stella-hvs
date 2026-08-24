"""Regression tests over the synthetic extraction failure fixtures.

Each observed failure shape (group-level probability propagation,
letter-marked sexagesimal coordinates, empty-quantity submissions, mixed
uncertainty forms, corrected submissions that drop required properties) is
pinned here with abstract identities only, plus a deformation test proving
the structures are name- and order-independent.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from stella.lit.extraction.bounded_call import build_evidence_correction_message
from stella.hvs_extraction.field_stage import (
    FIELDS_COMPLETE,
    run_field_stage,
)
from stella.lit.extraction.field_validate import (
    COORDINATE_FORMAT_INCONSISTENT,
    QUANTITY_EMPTY,
    UNCERTAINTY_MIXED,
    validate_field_submission,
)
from stella.lit.extraction.prepare import (
    build_prepared_input,
    write_prepared_input,
)
from stella.lit.extraction_rules import render_rule_profile
from tests import hvs_extraction_synthetic_fixtures as fixtures
from tests.test_hvs_extraction_field_stage import budget, frozen_config

ROOT = Path(__file__).resolve().parents[1]
ARXIV_ID = "2406.99996"
RUN_ID = "run-synthetic-group-test"


def fake_response(payload: dict) -> dict:
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
                                "name": "submit_candidate_fields",
                                "arguments": json.dumps(payload, ensure_ascii=False),
                            },
                        }
                    ],
                },
            }
        ]
    }


class RecordingTransport:
    def __init__(self, handler) -> None:
        self.handler = handler
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.handler(kwargs)


def make_group_workspace(tmp: str, names: list[str]) -> Path:
    workspace = Path(tmp)
    shutil.copytree(
        ROOT / "skills/hvs-candidates-extraction/rules",
        workspace / "skills/hvs-candidates-extraction/rules",
    )
    paper_dir = workspace / "literature" / ARXIV_ID
    (paper_dir / "arxiv_source").mkdir(parents=True)
    (paper_dir / "arxiv_source" / "main.tex").write_text(
        fixtures.group_statement_manuscript(names), encoding="utf-8"
    )
    artifact = build_prepared_input(
        workspace,
        ARXIV_ID,
        roster_budget=budget(),
        field_budget=budget(),
    )
    assert artifact["status"] == "prepared", artifact.get("failure")
    write_prepared_input(workspace, RUN_ID, artifact)
    candidates = [
        fixtures.roster_candidate_for_group_note(index, name)
        for index, name in enumerate(names, start=1)
    ]
    roster_final = {
        "schema": {"name": "hvs_extraction.roster_final", "version": 1},
        "paper": {"arxiv_id": ARXIV_ID},
        "run_id": RUN_ID,
        "status": "roster_complete",
        "roster_status": "candidates_found",
        "candidates": candidates,
        "reviewed_exclusions": [],
    }
    paper_out = (
        workspace
        / "benchmark/campaigns/hvs-extraction-v6/runs"
        / RUN_ID
        / "papers"
        / ARXIV_ID
    )
    paper_out.mkdir(parents=True)
    (paper_out / "roster_final.json").write_text(
        json.dumps(roster_final), encoding="utf-8"
    )
    return workspace


def candidate_artifact(workspace: Path, record_id: str) -> dict:
    path = (
        workspace
        / "benchmark/campaigns/hvs-extraction-v6/runs"
        / RUN_ID
        / "papers"
        / ARXIV_ID
        / "candidates"
        / f"{record_id}.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


class GroupStatementNoteTest(unittest.TestCase):
    NAMES = ["HVS-A", "HVS-B", "HVS-C"]

    def test_shared_group_note_evidence_is_valid_for_every_member(self) -> None:
        manuscript = fixtures.group_statement_manuscript(self.NAMES)
        ctx = fixtures.tex_context(manuscript)
        for index in range(1, len(self.NAMES) + 1):
            submission = fixtures.group_bound_probability_submission(
                member_line=fixtures.GROUP_NOTE_LINE + index
            )
            self.assertEqual(validate_field_submission(submission, ctx), [])

    def test_renamed_and_reordered_members_stay_valid(self) -> None:
        names = ["K9-STAR", "S-1", "S-12"]
        manuscript = fixtures.group_statement_manuscript(names)
        ctx = fixtures.tex_context(manuscript)
        for index in range(1, len(names) + 1):
            submission = fixtures.group_bound_probability_submission(
                member_line=fixtures.GROUP_NOTE_LINE + index
            )
            self.assertEqual(validate_field_submission(submission, ctx), [])


class QuantityNullRemedyTest(unittest.TestCase):
    def test_empty_quantity_is_flagged_with_null_remedy(self) -> None:
        ctx = fixtures.tex_context(fixtures.uncertainty_manuscript())
        issues = validate_field_submission(
            fixtures.empty_quantity_submission(), ctx
        )
        rendered = [issue.render() for issue in issues]
        self.assertTrue(
            any(
                QUANTITY_EMPTY in line
                and "submit null for the field instead" in line
                for line in rendered
            ),
            rendered,
        )

    def test_evidence_correction_carries_remedy_and_completeness(self) -> None:
        ctx = fixtures.tex_context(fixtures.uncertainty_manuscript())
        payload = fixtures.empty_quantity_submission()
        issues = validate_field_submission(payload, ctx)
        message = build_evidence_correction_message(
            issues, payload, "submit_candidate_fields"
        )
        self.assertIn("submit null for the field instead", message)
        self.assertIn("must remain one complete submission", message)
        self.assertIn("no previously present property may be dropped", message)


class CoordinateLetterMarkTest(unittest.TestCase):
    def test_letter_marked_sexagesimal_is_valid(self) -> None:
        ctx = fixtures.tex_context(fixtures.coordinate_manuscript())
        submission = fixtures.coordinate_submission(
            fixtures.COORDINATE_LETTER_RA, "sexagesimal_hms", "h"
        )
        self.assertEqual(validate_field_submission(submission, ctx), [])

    def test_colon_form_under_hms_is_inconsistent(self) -> None:
        ctx = fixtures.tex_context(fixtures.coordinate_manuscript())
        submission = fixtures.coordinate_submission(
            fixtures.COORDINATE_COLON_RA, "sexagesimal_hms", None
        )
        issues = validate_field_submission(submission, ctx)
        self.assertTrue(
            any(
                issue.code == COORDINATE_FORMAT_INCONSISTENT
                and "letter-marked" in issue.message
                for issue in issues
            ),
            [issue.render() for issue in issues],
        )


class UncertaintyFormTest(unittest.TestCase):
    def test_mixed_uncertainty_forms_are_rejected(self) -> None:
        ctx = fixtures.tex_context(fixtures.uncertainty_manuscript())
        issues = validate_field_submission(
            fixtures.mixed_uncertainty_submission(), ctx
        )
        self.assertTrue(
            any(issue.code == UNCERTAINTY_MIXED for issue in issues),
            [issue.render() for issue in issues],
        )


class NullReconciliationRuleRenderingTest(unittest.TestCase):
    EXPECTED = "[hvs.field.null_reconciliation] Reconcile every null against the reporting surface"

    def test_rule_renders_in_both_field_profiles_only(self) -> None:
        for profile in (
            "hvs_candidate_core_fields_tex",
            "hvs_candidate_core_fields_tex_ecsv",
        ):
            self.assertIn(self.EXPECTED, render_rule_profile(ROOT, profile, "prompt"))
        self.assertNotIn(
            self.EXPECTED,
            render_rule_profile(ROOT, "hvs_candidate_roster", "prompt"),
        )


class GroupStatementFieldStageTest(unittest.TestCase):
    def test_all_members_share_group_note_evidence(self) -> None:
        names = ["HVS-A", "HVS-B"]
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_group_workspace(tmp, names)

            def handler(kwargs: dict) -> dict:
                user = kwargs["messages"][1]["content"]
                block = user.split("===== BEGIN ASSIGNED CANDIDATE =====", 1)[1]
                block = block.split("===== END ASSIGNED CANDIDATE =====", 1)[0]
                assigned = json.loads(block)
                name = assigned["identifiers"][0]["value"]
                member_line = fixtures.GROUP_NOTE_LINE + names.index(name) + 1
                return fake_response(
                    fixtures.group_bound_probability_submission(
                        member_line=member_line
                    )
                )

            transport = RecordingTransport(handler)
            summary = run_field_stage(
                workspace,
                RUN_ID,
                ARXIV_ID,
                config=frozen_config(),
                transport=transport,
                sleep=lambda _: None,
            )
            self.assertEqual(
                summary["candidates"],
                {"candidate-001": FIELDS_COMPLETE, "candidate-002": FIELDS_COMPLETE},
            )
            for record_id in ("candidate-001", "candidate-002"):
                artifact = candidate_artifact(workspace, record_id)
                probability = artifact["fields"]["core"]["bound_assessment"][
                    "bound_probability"
                ]
                self.assertEqual(probability["value"], "0.5")
                self.assertEqual(probability["limit_kind"], "upper_limit")
                source = probability["direct_evidence"][0]["source"]
                self.assertEqual(source["start_line"], fixtures.GROUP_NOTE_LINE)
                self.assertEqual(source["end_line"], fixtures.GROUP_NOTE_LINE)


if __name__ == "__main__":
    unittest.main()
