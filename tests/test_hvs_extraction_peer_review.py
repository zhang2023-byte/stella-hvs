"""Peer-consistency review tests: trigger detection and bounded review.

The review uses the narrow ``submit_reviewed_fields`` contract: the response
may only carry the flagged field quantities, code merges them into the
previous delivery, and any failure keeps the original delivery.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from stella.hvs_extraction.field_stage import (
    FIELDS_COMPLETE,
    detect_peer_consistency_flags,
    run_field_stage,
)
from stella.hvs_extraction.method_config import (
    HvsFieldRequestPolicy,
    HvsPeerConsistencyReviewPolicy,
)
from tests import hvs_extraction_synthetic_fixtures as fixtures
from tests.test_hvs_extraction_synthetic_fixtures import (
    candidate_artifact,
    fake_response,
    make_group_workspace,
    RecordingTransport,
    RUN_ID,
    ARXIV_ID,
)
from tests.test_hvs_extraction_field_stage import frozen_config
from stella.lit.llm_batch import LLMTransportError

ROOT = Path(__file__).resolve().parents[1]


def review_enabled_config():
    return frozen_config().model_copy(
        update={
            "field_request_policy": HvsFieldRequestPolicy(
                peer_consistency_review=HvsPeerConsistencyReviewPolicy(
                    enabled=True
                )
            )
        }
    )


def review_response(core_fields: dict) -> dict:
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
                                "name": "submit_reviewed_fields",
                                "arguments": json.dumps(
                                    {"core_fields": core_fields},
                                    ensure_ascii=False,
                                ),
                            },
                        }
                    ],
                },
            }
        ]
    }


def group_note_quantity(**overrides) -> dict:
    submission = fixtures.group_bound_probability_submission(member_line=8)
    quantity = submission["core"]["bound_assessment"]["bound_probability"]
    quantity.update(overrides)
    return quantity


def artifact(record_id: str, submission: dict) -> dict:
    return {
        "record_id": record_id,
        "status": FIELDS_COMPLETE,
        "fields": submission,
    }


class DetectPeerConsistencyFlagsTest(unittest.TestCase):
    NAMES = ["HVS-A", "HVS-B", "HVS-C"]

    def submissions(self, *, third_null: bool, peer_value: str = "0.5"):
        filled = [
            fixtures.group_bound_probability_submission(member_line=line)
            for line in (6, 7)
        ]
        if peer_value != "0.5":
            for submission in filled:
                quantity = submission["core"]["bound_assessment"][
                    "bound_probability"
                ]
                quantity["value"] = peer_value
                quantity["direct_evidence"][0]["source"]["raw_value"] = (
                    peer_value
                )
        third = (
            fixtures.group_null_probability_submission()
            if third_null
            else fixtures.group_bound_probability_submission(member_line=8)
        )
        return filled + [third]

    def flags_for(self, submissions):
        artifacts = {
            f"candidate-{index:03d}": artifact(
                f"candidate-{index:03d}", submission
            )
            for index, submission in enumerate(submissions, start=1)
        }
        return detect_peer_consistency_flags(artifacts, min_shared_peers=2)

    def test_shared_peer_evidence_flags_the_null_candidate(self) -> None:
        flags = self.flags_for(self.submissions(third_null=True))
        self.assertEqual(list(flags), ["candidate-003"])
        (flag,) = flags["candidate-003"]
        self.assertEqual(
            flag["path"], "$.core.bound_assessment.bound_probability"
        )
        self.assertEqual(flag["peers"], 2)
        self.assertIn("main.tex lines", flag["locator"])

    def test_no_flag_when_all_peers_filled(self) -> None:
        self.assertEqual(
            self.flags_for(self.submissions(third_null=False)), {}
        )

    def test_no_flag_when_peers_disagree_on_value(self) -> None:
        filled = self.submissions(third_null=True)
        quantity = filled[1]["core"]["bound_assessment"]["bound_probability"]
        quantity["value"] = "0.9"
        quantity["direct_evidence"][0]["source"]["raw_value"] = "0.9"
        self.assertEqual(self.flags_for(filled), {})

    def test_no_flag_with_single_peer(self) -> None:
        submissions = self.submissions(third_null=True)[:2]
        submissions[1] = fixtures.group_null_probability_submission()
        self.assertEqual(self.flags_for(submissions), {})

    def test_failed_candidates_never_participate(self) -> None:
        artifacts = {
            "candidate-001": artifact(
                "candidate-001", self.submissions(third_null=True)[0]
            ),
            "candidate-002": {
                "record_id": "candidate-002",
                "status": "field_extraction_failed",
                "fields": None,
            },
            "candidate-003": artifact(
                "candidate-003",
                fixtures.group_null_probability_submission(),
            ),
        }
        self.assertEqual(
            detect_peer_consistency_flags(artifacts, min_shared_peers=2), {}
        )


class PeerReviewFieldStageTest(unittest.TestCase):
    def dispatch_handler(self, names, *, review_response_factory):
        state = {"review_messages": []}

        def handler(kwargs: dict) -> dict:
            review = next(
                (
                    message
                    for message in kwargs["messages"]
                    if "PEER CONSISTENCY REVIEW" in message.get("content", "")
                ),
                None,
            )
            if review is not None:
                state["review_messages"].append(review["content"])
                return review_response_factory()
            block = (
                kwargs["messages"][1]["content"]
                .split("===== BEGIN ASSIGNED CANDIDATE =====", 1)[1]
                .split("===== END ASSIGNED CANDIDATE =====", 1)[0]
            )
            name = json.loads(block)["identifiers"][0]["value"]
            if name == names[-1]:
                return fake_response(
                    fixtures.group_null_probability_submission()
                )
            member_line = fixtures.GROUP_NOTE_LINE + names.index(name) + 1
            return fake_response(
                fixtures.group_bound_probability_submission(
                    member_line=member_line
                )
            )

        return state, handler

    def run_stage(self, names, handler, config, verify) -> None:
        transport = RecordingTransport(handler)
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_group_workspace(tmp, names)
            summary = run_field_stage(
                workspace,
                RUN_ID,
                ARXIV_ID,
                config=config,
                transport=transport,
                sleep=lambda _: None,
            )
            self.assertTrue(
                all(
                    status == FIELDS_COMPLETE
                    for status in summary["candidates"].values()
                ),
                summary["candidates"],
            )
            verify(workspace, transport)

    def test_review_populates_shared_group_field(self) -> None:
        names = ["HVS-A", "HVS-B", "HVS-C"]
        state, handler = self.dispatch_handler(
            names,
            review_response_factory=lambda: review_response(
                {
                    "bound_assessment.bound_probability": (
                        group_note_quantity()
                    )
                }
            ),
        )

        def verify(workspace: Path, transport: RecordingTransport) -> None:
            self.assertEqual(len(state["review_messages"]), 1)
            self.assertIn(
                "submit_reviewed_fields", state["review_messages"][0]
            )
            artifact = candidate_artifact(workspace, "candidate-003")
            probability = artifact["fields"]["core"]["bound_assessment"][
                "bound_probability"
            ]
            self.assertEqual(probability["value"], "0.5")
            self.assertEqual(probability["limit_kind"], "upper_limit")
            self.assertIn(
                "resolved_text", probability["direct_evidence"][0]["source"]
            )
            (repair,) = artifact["repair_history"]
            self.assertEqual(repair["type"], "peer_consistency_review")
            self.assertEqual(repair["final_result"], "accepted")
            self.assertEqual(
                repair["applied_fields"],
                ["bound_assessment.bound_probability"],
            )
            self.assertEqual(
                [attempt["kind"] for attempt in artifact["attempts"]],
                ["initial", "peer_consistency_review"],
            )

        self.run_stage(names, handler, review_enabled_config(), verify)

    def test_review_survives_transient_transport_failure(self) -> None:
        # One transient transport failure inside the review draws on the
        # per-call retry pool; the review still delivers instead of failing.
        names = ["HVS-A", "HVS-B", "HVS-C"]
        state = {"review_calls": 0}

        def handler(kwargs: dict) -> dict:
            review = next(
                (
                    message
                    for message in kwargs["messages"]
                    if "PEER CONSISTENCY REVIEW" in message.get("content", "")
                ),
                None,
            )
            if review is not None:
                state["review_calls"] += 1
                if state["review_calls"] == 1:
                    raise LLMTransportError(
                        "boom timeout",
                        category="timeout",
                        http_status=None,
                        automatic_retryable=True,
                    )
                return review_response(
                    {
                        "bound_assessment.bound_probability": (
                            group_note_quantity()
                        )
                    }
                )
            block = (
                kwargs["messages"][1]["content"]
                .split("===== BEGIN ASSIGNED CANDIDATE =====", 1)[1]
                .split("===== END ASSIGNED CANDIDATE =====", 1)[0]
            )
            name = json.loads(block)["identifiers"][0]["value"]
            if name == names[-1]:
                return fake_response(
                    fixtures.group_null_probability_submission()
                )
            member_line = fixtures.GROUP_NOTE_LINE + names.index(name) + 1
            return fake_response(
                fixtures.group_bound_probability_submission(
                    member_line=member_line
                )
            )

        def verify(workspace: Path, transport: RecordingTransport) -> None:
            self.assertEqual(state["review_calls"], 2)
            artifact = candidate_artifact(workspace, "candidate-003")
            probability = artifact["fields"]["core"]["bound_assessment"][
                "bound_probability"
            ]
            self.assertEqual(probability["value"], "0.5")
            (repair,) = artifact["repair_history"]
            self.assertEqual(repair["final_result"], "accepted")
            review_attempts = [
                attempt
                for attempt in artifact["attempts"]
                if attempt["kind"] == "peer_consistency_review"
            ]
            self.assertEqual(
                [attempt["transport_attempt_kind"] for attempt in review_attempts],
                ["initial", "transport_retry"],
            )

        self.run_stage(names, handler, review_enabled_config(), verify)

    def test_review_confirms_null_when_statement_does_not_apply(self) -> None:
        names = ["HVS-A", "HVS-B", "HVS-C"]
        state, handler = self.dispatch_handler(
            names,
            review_response_factory=lambda: review_response(
                {"bound_assessment.bound_probability": None}
            ),
        )

        def verify(workspace: Path, transport: RecordingTransport) -> None:
            self.assertEqual(len(state["review_messages"]), 1)
            artifact = candidate_artifact(workspace, "candidate-003")
            self.assertIsNone(
                artifact["fields"]["core"]["bound_assessment"][
                    "bound_probability"
                ]
            )
            (repair,) = artifact["repair_history"]
            self.assertEqual(repair["final_result"], "accepted")
            self.assertEqual(repair["applied_fields"], [])
            self.assertEqual(
                repair["confirmed_null"],
                ["bound_assessment.bound_probability"],
            )

        self.run_stage(names, handler, review_enabled_config(), verify)

    def test_failed_review_keeps_original_delivery(self) -> None:
        names = ["HVS-A", "HVS-B", "HVS-C"]

        def handler(kwargs: dict) -> dict:
            if any(
                "PEER CONSISTENCY REVIEW" in message.get("content", "")
                for message in kwargs["messages"]
            ):
                return {
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "no",
                            },
                        }
                    ]
                }
            block = (
                kwargs["messages"][1]["content"]
                .split("===== BEGIN ASSIGNED CANDIDATE =====", 1)[1]
                .split("===== END ASSIGNED CANDIDATE =====", 1)[0]
            )
            name = json.loads(block)["identifiers"][0]["value"]
            if name == "HVS-C":
                return fake_response(
                    fixtures.group_null_probability_submission()
                )
            member_line = fixtures.GROUP_NOTE_LINE + names.index(name) + 1
            return fake_response(
                fixtures.group_bound_probability_submission(
                    member_line=member_line
                )
            )

        def verify(workspace: Path, transport: RecordingTransport) -> None:
            artifact = candidate_artifact(workspace, "candidate-003")
            self.assertIsNone(
                artifact["fields"]["core"]["bound_assessment"][
                    "bound_probability"
                ]
            )
            (repair,) = artifact["repair_history"]
            self.assertEqual(repair["final_result"], "failed")
            self.assertEqual(
                [attempt["kind"] for attempt in artifact["attempts"]],
                ["initial", "peer_consistency_review"],
            )

        self.run_stage(names, handler, review_enabled_config(), verify)

    def test_invalid_review_quantity_is_rejected(self) -> None:
        names = ["HVS-A", "HVS-B", "HVS-C"]
        invalid = group_note_quantity()
        invalid["direct_evidence"][0]["source"]["raw_value"] = "9.99"
        _, handler = self.dispatch_handler(
            names, review_response_factory=lambda: review_response(
                {"bound_assessment.bound_probability": invalid}
            )
        )

        def verify(workspace: Path, transport: RecordingTransport) -> None:
            artifact = candidate_artifact(workspace, "candidate-003")
            self.assertIsNone(
                artifact["fields"]["core"]["bound_assessment"][
                    "bound_probability"
                ]
            )
            (repair,) = artifact["repair_history"]
            self.assertEqual(
                repair["final_status"], "evidence_validation_failure"
            )
            self.assertTrue(repair["result_errors"])

        self.run_stage(names, handler, review_enabled_config(), verify)

    def test_review_issues_no_request_when_disabled(self) -> None:
        names = ["HVS-A", "HVS-B", "HVS-C"]
        state, handler = self.dispatch_handler(
            names,
            review_response_factory=lambda: review_response(
                {
                    "bound_assessment.bound_probability": (
                        group_note_quantity()
                    )
                }
            ),
        )

        def verify(workspace: Path, transport: RecordingTransport) -> None:
            self.assertEqual(state["review_messages"], [])
            self.assertEqual(len(transport.calls), 3)
            artifact = candidate_artifact(workspace, "candidate-003")
            self.assertIsNone(
                artifact["fields"]["core"]["bound_assessment"][
                    "bound_probability"
                ]
            )
            self.assertEqual(artifact["repair_history"], [])

        self.run_stage(names, handler, frozen_config(), verify)

    def test_renamed_members_trigger_identically(self) -> None:
        names = ["K9-STAR", "S-12", "S-1"]
        state, handler = self.dispatch_handler(
            names,
            review_response_factory=lambda: review_response(
                {
                    "bound_assessment.bound_probability": (
                        group_note_quantity()
                    )
                }
            ),
        )

        def verify(workspace: Path, transport: RecordingTransport) -> None:
            self.assertEqual(len(state["review_messages"]), 1)
            artifact = candidate_artifact(workspace, "candidate-003")
            (repair,) = artifact["repair_history"]
            self.assertEqual(repair["final_result"], "accepted")

        self.run_stage(names, handler, review_enabled_config(), verify)


if __name__ == "__main__":
    unittest.main()
