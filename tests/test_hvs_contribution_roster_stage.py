"""Contribution roster stage orchestration tests (fake transports only)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.hvs_contribution_fixtures import (
    ARXIV_ID,
    BOTH_TYPES_SUBMISSION,
    EMPTY_SUBMISSION,
    EXTERNAL_KNOWLEDGE_SUBMISSION,
    FULL_SUBMISSION,
    RANGE_GROUP,
    RUN_ID,
    RecordingTransport,
    fake_content_response,
    fake_response,
    frozen_contribution_config,
    make_workspace,
    manuscript_text,
    tool_name_of,
)
from stella.hvs_contribution_extraction.roster_stage import (
    ROSTER_COMPLETE,
    ROSTER_FAILED,
    finalize_contribution_roster,
    run_contribution_roster_stage,
)

ROOT = Path(__file__).resolve().parents[1]


def run_dir_for(workspace: Path) -> Path:
    return workspace / "runs" / "hvs-contribution-extraction" / RUN_ID


class ContributionRosterStageTest(unittest.TestCase):
    def test_happy_path_mixes_contribution_types_and_range(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            run_dir = run_dir_for(workspace)
            transport = RecordingTransport(
                lambda kwargs: fake_response(FULL_SUBMISSION, tool_name=tool_name_of(kwargs))
            )
            artifact = run_contribution_roster_stage(
                workspace,
                RUN_ID,
                ARXIV_ID,
                config=frozen_contribution_config(),
                transport=transport,
                sleep=lambda _: None,
                run_dir=run_dir,
            )
            self.assertEqual(artifact["status"], ROSTER_COMPLETE)
            self.assertEqual(artifact["roster_status"], "contributions_found")
            contributions = artifact["object_contributions"]
            # Six direct contributions plus four expanded range members.
            self.assertEqual(len(contributions), 10)
            by_identifier = {
                item["identifiers"][0]["value"]: item for item in contributions
            }
            self.assertEqual(
                {item["record_id"] for item in contributions},
                {f"obj-{index:03d}" for index in range(1, 11)},
            )
            # Per-object classification (case 10): same paper, two types.
            self.assertEqual(by_identifier["J1234"]["contribution_type"], "candidates_found")
            self.assertEqual(by_identifier["HVS-7"]["contribution_type"], "follow_up")
            self.assertEqual(by_identifier["HVS-7"]["paper_boundness"]["status"], "not_assessed")
            # Case 3: bound reassessment stays included as follow_up.
            self.assertEqual(by_identifier["HVS-9"]["contribution_type"], "follow_up")
            self.assertEqual(by_identifier["HVS-9"]["paper_boundness"]["status"], "bound")
            # Case 6/7/8 status semantics.
            self.assertEqual(by_identifier["J2001"]["paper_boundness"]["status"], "unbound")
            self.assertEqual(by_identifier["J2002"]["paper_boundness"]["status"], "no_overall_conclusion")
            self.assertEqual(by_identifier["J2003"]["paper_boundness"]["status"], "no_overall_conclusion")
            # Range members carry the group's contribution shape.
            range_member = by_identifier["J12"]
            self.assertEqual(range_member["contribution_type"], "candidates_found")
            self.assertTrue(range_member["identifiers"][0].get("range_expanded"))
            self.assertEqual(
                range_member["identifiers"][0].get("range_notation"), "J10-13"
            )
            # Reviewed exclusions preserved (cases 4 and 5).
            self.assertEqual(len(artifact["reviewed_exclusions"]), 2)
            # Exactly one roster-model call with the contribution tool.
            self.assertEqual(len(transport.calls), 1)
            self.assertEqual(
                {tool_name_of(call) for call in transport.calls},
                {"submit_contribution_roster"},
            )
            # Program-hidden context: paper identity never enters the prompts.
            for call in transport.calls:
                for message in call["messages"]:
                    self.assertNotIn(ARXIV_ID, message["content"])
            # Contribution rules present, V6 roster rules absent.
            system = transport.calls[0]["messages"][0]["content"]
            self.assertIn("[hvs.contrib.follow_up]", system)
            self.assertNotIn("hvs.roster.final_treatment", system)
            # Artifacts persisted inside the contribution run root only.
            paper_dir = run_dir / "papers" / ARXIV_ID
            proposal = json.loads(
                (paper_dir / "contribution_roster_proposal-slot-0.json").read_text(encoding="utf-8")
            )
            self.assertEqual(proposal["status"], "valid")
            final = json.loads(
                (paper_dir / "contribution_roster_final.json").read_text(encoding="utf-8")
            )
            self.assertEqual(final["status"], ROSTER_COMPLETE)
            self.assertFalse((workspace / "benchmark").exists())

    def test_json_object_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            config = frozen_contribution_config().model_copy(
                update={
                    "roster_model": frozen_contribution_config().roster_model.model_copy(
                        update={"structured_output_mode": "json_object"}
                    )
                }
            )
            transport = RecordingTransport(
                lambda kwargs: fake_content_response(BOTH_TYPES_SUBMISSION)
            )
            artifact = run_contribution_roster_stage(
                workspace,
                RUN_ID,
                ARXIV_ID,
                config=config,
                transport=transport,
                sleep=lambda _: None,
                run_dir=run_dir_for(workspace),
            )
            self.assertEqual(artifact["status"], ROSTER_COMPLETE)
            self.assertEqual(len(artifact["object_contributions"]), 3)

    def test_evidence_correction_recovers_from_invalid_identifier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            # The flagged subtree is identifiers[0]; the correction may only
            # fix that element, so the second submission keeps everything else.
            typo_submission = {
                "object_contributions": [
                    {
                        "identifiers": [
                            {
                                "value": "J1234X",
                                "source_refs": [
                                    {"path": "main.tex", "start_line": 3, "end_line": 3}
                                ],
                            }
                        ],
                        "contribution_type": "candidates_found",
                        "contribution_note": "note",
                        "contribution_evidence": [
                            {"path": "main.tex", "start_line": 3, "end_line": 3}
                        ],
                        "paper_boundness": {
                            "status": "unbound",
                            "evidence": [
                                {"path": "main.tex", "start_line": 3, "end_line": 3}
                            ],
                        },
                    }
                ],
                "reviewed_exclusions": [],
                "range_groups": [],
            }
            corrected = {
                "object_contributions": [
                    {
                        "identifiers": [
                            {
                                "value": "J1234",
                                "source_refs": [
                                    {"path": "main.tex", "start_line": 3, "end_line": 3}
                                ],
                            }
                        ],
                        "contribution_type": "candidates_found",
                        "contribution_note": "note",
                        "contribution_evidence": [
                            {"path": "main.tex", "start_line": 3, "end_line": 3}
                        ],
                        "paper_boundness": {
                            "status": "unbound",
                            "evidence": [
                                {"path": "main.tex", "start_line": 3, "end_line": 3}
                            ],
                        },
                    }
                ],
                "reviewed_exclusions": [],
                "range_groups": [],
            }
            responses = [typo_submission, corrected]
            transport = RecordingTransport(
                lambda kwargs: fake_response(
                    responses[len(transport.calls) - 1], tool_name=tool_name_of(kwargs)
                )
            )
            artifact = run_contribution_roster_stage(
                workspace,
                RUN_ID,
                ARXIV_ID,
                config=frozen_contribution_config(),
                transport=transport,
                sleep=lambda _: None,
                run_dir=run_dir_for(workspace),
            )
            self.assertEqual(artifact["status"], ROSTER_COMPLETE)
            self.assertEqual(len(transport.calls), 2)
            self.assertEqual(len(artifact["object_contributions"]), 1)

    def test_terminal_failure_produces_no_trusted_contributions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            transport = RecordingTransport(
                lambda kwargs: fake_response(
                    EXTERNAL_KNOWLEDGE_SUBMISSION, tool_name=tool_name_of(kwargs)
                )
            )
            artifact = run_contribution_roster_stage(
                workspace,
                RUN_ID,
                ARXIV_ID,
                config=frozen_contribution_config(),
                transport=transport,
                sleep=lambda _: None,
                run_dir=run_dir_for(workspace),
            )
            self.assertEqual(artifact["status"], ROSTER_FAILED)
            self.assertIsNone(artifact["roster_status"])
            self.assertEqual(artifact["object_contributions"], [])
            self.assertIsNotNone(artifact["failure"])

    def test_no_contributions_roster_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            transport = RecordingTransport(
                lambda kwargs: fake_response(EMPTY_SUBMISSION, tool_name=tool_name_of(kwargs))
            )
            artifact = run_contribution_roster_stage(
                workspace,
                RUN_ID,
                ARXIV_ID,
                config=frozen_contribution_config(),
                transport=transport,
                sleep=lambda _: None,
                run_dir=run_dir_for(workspace),
            )
            self.assertEqual(artifact["status"], ROSTER_COMPLETE)
            self.assertEqual(artifact["roster_status"], "no_contributions")

    def test_missing_run_dir_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            with self.assertRaisesRegex(ValueError, "run_dir is required"):
                run_contribution_roster_stage(
                    workspace,
                    RUN_ID,
                    ARXIV_ID,
                    config=frozen_contribution_config(),
                    transport=RecordingTransport(lambda kwargs: {}),
                    sleep=lambda _: None,
                )

    def test_finalize_expands_range_and_assigns_program_ids(self) -> None:
        payload = {
            "object_contributions": [],
            "reviewed_exclusions": [],
            "range_groups": [RANGE_GROUP],
        }
        contributions, exclusions, roster_status = finalize_contribution_roster(
            payload,
            original_texts={"main.tex": manuscript_text()},
            file_sha256={"main.tex": "0" * 64},
        )
        self.assertEqual(roster_status, "contributions_found")
        self.assertEqual(
            [item["display_name"] for item in contributions],
            ["J10", "J11", "J12", "J13"],
        )
        self.assertEqual(exclusions, [])


if __name__ == "__main__":
    unittest.main()
