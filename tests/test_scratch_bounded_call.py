"""Bounded call machinery tests: transport, format, and evidence correction (D017-D020)."""

from __future__ import annotations

import json
import unittest

from stella.benchmark.scratch.bounded_call import (
    CORRECTION_DRIFT,
    EVIDENCE_VALIDATION_FAILURE,
    OK,
    REQUEST_REJECTED,
    SUBMISSION_FORMAT_FAILURE,
    TRANSPORT_FAILURE,
    build_evidence_correction_message,
    drift_violations,
    execute_with_evidence_correction,
    execute_with_format_correction,
)
from stella.benchmark.scratch.roster_validate import EvidenceIssue
from stella.lit.llm_batch import LLMTransportError


TOOL = "submit_candidate_roster"
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["candidates"],
    "properties": {"candidates": {"type": "array"}},
}
MESSAGES = [{"role": "user", "content": "submit"}]


def fake_response(payload: dict | None, *, tool_name: str = TOOL, calls: int = 1) -> dict:
    tool_calls = []
    for index in range(calls):
        arguments = payload if isinstance(payload, str) else json.dumps(payload or {})
        tool_calls.append(
            {
                "id": f"call_{index}",
                "type": "function",
                "function": {"name": tool_name, "arguments": arguments},
            }
        )
    return {"choices": [{"index": 0, "message": {"role": "assistant", "tool_calls": tool_calls}}]}


def no_call_response() -> dict:
    return {"choices": [{"index": 0, "message": {"role": "assistant", "content": "thinking out loud"}}]}


def with_usage(response: dict, tokens: int) -> dict:
    response["usage"] = {"total_tokens": tokens}
    return response


def script_transport(responses: list):
    state = {"calls": 0, "messages": []}

    def transport(**kwargs):
        state["calls"] += 1
        state["messages"].append(kwargs["messages"])
        item = responses[min(state["calls"] - 1, len(responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    return state, transport


def transport_error(category: str, status: int | None, retryable: bool) -> LLMTransportError:
    return LLMTransportError(
        f"boom {category}",
        category=category,
        http_status=status,
        automatic_retryable=retryable,
    )


def run(transport, sleep=lambda _: None):
    return execute_with_format_correction(
        transport=transport,
        transport_kwargs={"model": "fake"},
        tool_name=TOOL,
        schema=SCHEMA,
        messages=MESSAGES,
        sleep=sleep,
    )


class TransportBudgetTest(unittest.TestCase):
    def test_retryable_failures_are_retried_identically(self) -> None:
        sleeps: list[float] = []
        state, transport = script_transport(
            [
                transport_error("rate_limit", 429, True),
                transport_error("server", 503, True),
                fake_response({"candidates": []}),
            ]
        )
        result = run(transport, sleep=sleeps.append)
        self.assertEqual(result.status, OK)
        self.assertEqual(state["calls"], 3)
        self.assertEqual(len(sleeps), 2)
        self.assertTrue(all(delay > 0 for delay in sleeps))
        kinds = [record["kind"] for record in result.attempts]
        self.assertEqual(kinds, ["initial", "transport_retry", "transport_retry"])

    def test_request_rejected_is_not_resent(self) -> None:
        state, transport = script_transport(
            [transport_error("invalid_request", 400, False)]
        )
        result = run(transport)
        self.assertEqual(result.status, REQUEST_REJECTED)
        self.assertEqual(state["calls"], 1)
        self.assertEqual(result.transport_error["http_status"], 400)

    def test_transport_failure_exhausts_three_attempts(self) -> None:
        state, transport = script_transport(
            [transport_error("timeout", None, True)]
        )
        result = run(transport, sleep=lambda _: None)
        self.assertEqual(result.status, TRANSPORT_FAILURE)
        self.assertEqual(state["calls"], 3)


class FormatCorrectionTest(unittest.TestCase):
    def test_missing_call_is_corrected_once(self) -> None:
        state, transport = script_transport(
            [no_call_response(), fake_response({"candidates": []})]
        )
        result = run(transport)
        self.assertEqual(result.status, OK)
        correction_messages = state["messages"][1]
        self.assertEqual(len(correction_messages), 2)
        self.assertEqual(correction_messages[0]["content"], "submit")
        correction = correction_messages[-1]["content"]
        self.assertIn("SUBMISSION CORRECTION", correction)
        self.assertIn("missing_submission_call", correction)
        # Assistant prose from the failed response is never replayed.
        self.assertNotIn("thinking out loud", correction)

    def test_terminal_format_failure_records_both_error_sets(self) -> None:
        state, transport = script_transport([no_call_response(), no_call_response()])
        result = run(transport)
        self.assertEqual(result.status, SUBMISSION_FORMAT_FAILURE)
        self.assertEqual(state["calls"], 2)
        self.assertTrue(result.initial_errors)
        self.assertTrue(result.correction_errors)
        kinds = [record["kind"] for record in result.attempts]
        self.assertIn("format_correction", kinds)

    def test_malformed_arguments_replay_raw_text(self) -> None:
        state, transport = script_transport(
            [fake_response("{not json", calls=1), fake_response({"candidates": []})]
        )
        result = run(transport)
        self.assertEqual(result.status, OK)
        correction = state["messages"][1][-1]["content"]
        self.assertIn("malformed_arguments", correction)
        self.assertIn("{not json", correction)

    def test_multiple_calls_report_names_and_counts_only(self) -> None:
        state, transport = script_transport(
            [fake_response({"candidates": []}, calls=2), fake_response({"candidates": []})]
        )
        result = run(transport)
        self.assertEqual(result.status, OK)
        correction = state["messages"][1][-1]["content"]
        self.assertIn("multiple_submission_calls", correction)
        self.assertIn("submit_candidate_roster", correction)
        self.assertNotIn('"candidates"', correction)

    def test_schema_errors_are_format_failures_with_paths(self) -> None:
        state, transport = script_transport(
            [fake_response({"wrong": 1}), fake_response({"candidates": []})]
        )
        result = run(transport)
        self.assertEqual(result.status, OK)
        correction = state["messages"][1][-1]["content"]
        self.assertIn("missing required property 'candidates'", correction)
        self.assertIn("unexpected property 'wrong'", correction)


class EvidenceCorrectionTest(unittest.TestCase):
    ISSUES = [
        EvidenceIssue(
            "$.candidates[0].identifiers[0]",
            "identifier_not_verbatim",
            "identifier 'X' does not occur verbatim",
        )
    ]

    def run_evidence(self, transport, previous, issues=None, validate_fn=lambda payload: []):
        return execute_with_evidence_correction(
            transport=transport,
            transport_kwargs={"model": "fake"},
            tool_name=TOOL,
            schema=SCHEMA,
            messages=MESSAGES,
            previous_payload=previous,
            issues=issues if issues is not None else self.ISSUES,
            validate_fn=validate_fn,
            sleep=lambda _: None,
        )

    def test_correction_message_carries_errors_and_previous_args(self) -> None:
        message = build_evidence_correction_message(
            self.ISSUES, {"candidates": [{"identifiers": []}]}, TOOL
        )
        self.assertIn("EVIDENCE CORRECTION", message)
        self.assertIn("identifier_not_verbatim", message)
        self.assertIn("$.candidates[0].identifiers[0]", message)
        self.assertIn('"candidates"', message)
        self.assertIn("preserve every unaffected value", message)

    def test_accepted_when_repair_stays_in_scope(self) -> None:
        previous = {"candidates": [{"identifiers": [{"value": "X"}], "qualification": {"reason": "r"}}]}
        corrected = {"candidates": [{"identifiers": [{"value": "Y"}], "qualification": {"reason": "r"}}]}
        _, transport = script_transport([fake_response(corrected)])
        result = self.run_evidence(transport, previous)
        self.assertEqual(result.status, OK)
        self.assertEqual(result.payload, corrected)

    def test_drift_guard_rejects_unrelated_change(self) -> None:
        previous = {"candidates": [{"identifiers": [{"value": "X"}], "qualification": {"reason": "r"}}]}
        corrected = {"candidates": [{"identifiers": [{"value": "Y"}], "qualification": {"reason": "rewritten"}}]}
        _, transport = script_transport([fake_response(corrected)])
        result = self.run_evidence(transport, previous)
        self.assertEqual(result.status, CORRECTION_DRIFT)
        self.assertTrue(result.unexpected_changes)

    def test_drift_guard_rejects_membership_change(self) -> None:
        previous = {"candidates": [{"identifiers": [{"value": "X"}]}]}
        corrected = {"candidates": []}
        _, transport = script_transport([fake_response(corrected)])
        result = self.run_evidence(transport, previous)
        self.assertEqual(result.status, CORRECTION_DRIFT)
        self.assertTrue(any("count changed" in item for item in result.unexpected_changes))

    def test_new_evidence_error_is_terminal(self) -> None:
        corrected = {"candidates": []}
        _, transport = script_transport([fake_response(corrected)])
        lingering = [EvidenceIssue("$.candidates", "x", "still broken")]
        result = self.run_evidence(
            transport, {"candidates": []}, validate_fn=lambda payload: lingering
        )
        self.assertEqual(result.status, EVIDENCE_VALIDATION_FAILURE)
        self.assertTrue(result.initial_errors)
        self.assertTrue(result.correction_errors)

    def test_usage_recorded_on_accept(self) -> None:
        previous = {"candidates": [{"identifiers": [{"value": "X"}], "qualification": {"reason": "r"}}]}
        corrected = {"candidates": [{"identifiers": [{"value": "Y"}], "qualification": {"reason": "r"}}]}
        _, transport = script_transport([with_usage(fake_response(corrected), 11)])
        result = self.run_evidence(transport, previous)
        self.assertEqual(result.status, OK)
        self.assertEqual([usage["total_tokens"] for usage in result.usages], [11])
        self.assertEqual(result.usage["total_tokens"], 11)

    def test_usage_recorded_on_drift_and_transport_paths(self) -> None:
        previous = {"candidates": [{"identifiers": [{"value": "X"}]}]}
        corrected = {"candidates": []}
        _, transport = script_transport([with_usage(fake_response(corrected), 13)])
        result = self.run_evidence(transport, previous)
        self.assertEqual(result.status, CORRECTION_DRIFT)
        self.assertEqual([usage["total_tokens"] for usage in result.usages], [13])

        _, failing = script_transport([transport_error("timeout", None, True)])
        result = self.run_evidence(failing, previous)
        self.assertEqual(result.status, TRANSPORT_FAILURE)
        self.assertEqual(result.usages, [])

    def test_drift_violations_unit(self) -> None:
        old = {"candidates": [{"a": 1, "b": {"c": 2}}], "reviewed_exclusions": []}
        same = {"candidates": [{"a": 1, "b": {"c": 2}}], "reviewed_exclusions": []}
        self.assertEqual(drift_violations(old, same, set()), [])
        changed = {"candidates": [{"a": 1, "b": {"c": 3}}], "reviewed_exclusions": []}
        self.assertEqual(
            drift_violations(old, changed, {"$.candidates[0].b"}), []
        )
        self.assertTrue(drift_violations(old, changed, set()))


class UsageAccountingTest(unittest.TestCase):
    """Every received response's usage must reach the cost ledger (D020)."""

    def test_initial_success_records_single_usage(self) -> None:
        _, transport = script_transport(
            [with_usage(fake_response({"candidates": []}), 5)]
        )
        result = run(transport)
        self.assertEqual(result.status, OK)
        self.assertEqual([usage["total_tokens"] for usage in result.usages], [5])
        self.assertEqual(result.usage["total_tokens"], 5)

    def test_format_correction_records_both_usages(self) -> None:
        _, transport = script_transport(
            [
                with_usage(no_call_response(), 3),
                with_usage(fake_response({"candidates": []}), 7),
            ]
        )
        result = run(transport)
        self.assertEqual(result.status, OK)
        self.assertEqual([usage["total_tokens"] for usage in result.usages], [3, 7])
        self.assertEqual(result.usage["total_tokens"], 7)

    def test_terminal_format_failure_keeps_both_usages(self) -> None:
        _, transport = script_transport(
            [with_usage(no_call_response(), 3), with_usage(no_call_response(), 4)]
        )
        result = run(transport)
        self.assertEqual(result.status, SUBMISSION_FORMAT_FAILURE)
        self.assertEqual([usage["total_tokens"] for usage in result.usages], [3, 4])

    def test_transport_only_path_has_no_usage(self) -> None:
        _, transport = script_transport([transport_error("timeout", None, True)])
        result = run(transport, sleep=lambda _: None)
        self.assertEqual(result.status, TRANSPORT_FAILURE)
        self.assertEqual(result.usages, [])


if __name__ == "__main__":
    unittest.main()
