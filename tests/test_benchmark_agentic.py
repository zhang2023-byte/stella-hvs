from __future__ import annotations

import json
import unittest
from pathlib import Path

from stella.benchmark.agentic_run import (
    ContextFS,
    ReactUnit,
    challenges_by_candidate,
    plan_task_prompt,
    review_structure_errors,
    reconcile_roster_records,
    agentic_delivery_status,
)
from stella.benchmark.context_pack import PackedContext, PackedFile
from stella.lit.extraction_rules import render_rule_profile


ROOT = Path(__file__).resolve().parents[1]


def packed_context() -> PackedContext:
    tex_body = "1|\\title{Fast star}\n2|We report HVS1.\n3|v = 743 km/s."
    ecsv_body = "1|# %ECSV 1.0\n2|col_001 col_002\n3|HVS1 743"
    text = (
        "===== BEGIN paper/arxiv_source/main.tex =====\n"
        f"{tex_body}\n"
        "===== END paper/arxiv_source/main.tex =====\n"
        "\n"
        "===== BEGIN paper/catalog_tables/t1.ecsv =====\n"
        f"{ecsv_body}\n"
        "===== END paper/catalog_tables/t1.ecsv =====\n"
    )
    files = [
        PackedFile(
            path="paper/arxiv_source/main.tex",
            kind="paper_text",
            chars=len(tex_body),
            lines=3,
            sha256="x",
        ),
        PackedFile(
            path="paper/catalog_tables/t1.ecsv",
            kind="ecsv_table",
            chars=len(ecsv_body),
            lines=3,
            sha256="y",
        ),
    ]
    return PackedContext(text=text, files=files, sha256="z", total_chars=len(text))


class ContextFSTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fs = ContextFS(packed_context())

    def test_list_files(self) -> None:
        listing = self.fs.list_files()
        paths = {item["path"] for item in listing}
        self.assertEqual(
            paths,
            {"paper/arxiv_source/main.tex", "paper/catalog_tables/t1.ecsv"},
        )

    def test_read_lines_respects_physical_numbers(self) -> None:
        body = self.fs.read_lines("paper/arxiv_source/main.tex", 2, 3)
        self.assertIn("2|We report HVS1.", body)
        self.assertIn("3|v = 743 km/s.", body)
        self.assertNotIn("1|", body.split("\n")[0])

    def test_read_lines_unknown_path_reports_known_files(self) -> None:
        body = self.fs.read_lines("nope.tex", 1, 2)
        self.assertIn("ERROR: unknown path", body)
        self.assertIn("main.tex", body)

    def test_search_returns_numbered_hits(self) -> None:
        hits = self.fs.search("743", "paper/arxiv_source/main.tex")
        self.assertIn("paper/arxiv_source/main.tex:3|v = 743 km/s.", hits)

    def test_search_bad_regex_is_reported(self) -> None:
        self.assertIn("ERROR: bad regex", self.fs.search("("))

    def test_plan_prompt_matches_identifiable_subset_policy(self) -> None:
        prompt = plan_task_prompt(
            {"schema": {}},
            self.fs,
            render_rule_profile(ROOT, "hvs_roster", "prompt"),
        )
        self.assertIn("identifiable subset", prompt)
        self.assertIn("inaccessible remainder", prompt)
        self.assertIn("never permits truncating a large but accessible table", prompt)


def tool_call(name: str, arguments: dict, call_id: str = "call-1") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def response_with(message: dict) -> dict:
    return {
        "model": "fake-model",
        "choices": [{"message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


class ScriptedTransport:
    def __init__(self, replies: list[dict]) -> None:
        self.replies = list(replies)
        self.requests: list[list[dict]] = []

    def __call__(self, *, messages: list[dict], **_: object) -> dict:
        self.requests.append([dict(m) for m in messages])
        if not self.replies:
            raise AssertionError("scripted transport exhausted")
        return self.replies.pop(0)


def make_unit(transport: ScriptedTransport, submit_check) -> ReactUnit:
    return ReactUnit(
        name="unit",
        kind="candidate",
        system_prompt="system",
        task_prompt="task",
        fs=ContextFS(packed_context()),
        submit_name="submit_candidate",
        submit_key="candidate",
        submit_check=submit_check,
        transport=transport,
        transport_kwargs={"extra_body": {}},
        archive=lambda name, response, messages: None,
        usage_totals={},
    )


class ReactUnitTest(unittest.TestCase):
    def test_tool_loop_then_accepted_submission(self) -> None:
        transport = ScriptedTransport(
            [
                response_with(
                    {
                        "content": "",
                        "tool_calls": [
                            tool_call(
                                "read_lines",
                                {
                                    "path": "paper/arxiv_source/main.tex",
                                    "start_line": 1,
                                    "end_line": 3,
                                },
                            )
                        ],
                    }
                ),
                response_with(
                    {
                        "content": "",
                        "tool_calls": [
                            tool_call(
                                "submit_candidate", {"candidate": {"ok": True}}
                            )
                        ],
                    }
                ),
            ]
        )
        unit = make_unit(transport, lambda payload: [])
        payload = unit.run()
        self.assertEqual(payload, {"ok": True})
        self.assertEqual(unit.calls, 2)
        # The tool reply for read_lines went back into the conversation.
        roles = [m["role"] for m in transport.requests[1]]
        self.assertIn("tool", roles)

    def test_rejected_submission_is_retried(self) -> None:
        transport = ScriptedTransport(
            [
                response_with(
                    {
                        "content": "",
                        "tool_calls": [
                            tool_call("submit_candidate", {"candidate": {"bad": 1}})
                        ],
                    }
                ),
                response_with(
                    {
                        "content": "",
                        "tool_calls": [
                            tool_call("submit_candidate", {"candidate": {"bad": 0}})
                        ],
                    }
                ),
            ]
        )
        checks = [["record_id mismatch"], []]
        unit = make_unit(transport, lambda payload: checks.pop(0))
        payload = unit.run()
        self.assertEqual(payload, {"bad": 0})
        rejected_reply = transport.requests[1][-1]
        self.assertEqual(rejected_reply["role"], "tool")
        self.assertIn("REJECTED", rejected_reply["content"])

    def test_plain_text_reply_is_nudged_back_to_tools(self) -> None:
        transport = ScriptedTransport(
            [
                response_with({"content": "I think the answer is HVS1."}),
                response_with(
                    {
                        "content": "",
                        "tool_calls": [
                            tool_call("submit_candidate", {"candidate": {"ok": 1}})
                        ],
                    }
                ),
            ]
        )
        unit = make_unit(transport, lambda payload: [])
        payload = unit.run()
        self.assertEqual(payload, {"ok": 1})
        nudge = transport.requests[1][-1]
        self.assertEqual(nudge["role"], "user")
        self.assertIn("submit_candidate", nudge["content"])

    def test_budget_exhaustion_returns_none(self) -> None:
        transport = ScriptedTransport(
            [
                response_with(
                    {
                        "content": "",
                        "tool_calls": [tool_call("list_files", {})],
                    }
                )
                for _ in range(3)
            ]
        )
        unit = make_unit(transport, lambda payload: [])
        self.assertIsNone(unit.run(budget=3))
        self.assertEqual(unit.calls, 3)


class ReviewContractTest(unittest.TestCase):
    def test_review_structure_errors(self) -> None:
        self.assertTrue(review_structure_errors({"nope": []}))
        self.assertTrue(
            review_structure_errors(
                {"challenges": [{"issue": "", "severity": "high", "candidate_index": 0}]}
            )
        )
        self.assertEqual(
            review_structure_errors(
                {
                    "challenges": [
                        {
                            "issue": "missing HVS2 from Table 1",
                            "severity": "high",
                            "candidate_index": -1,
                            "field": "candidates",
                        }
                    ],
                    "summary": "one miss",
                }
            ),
            [],
        )

    def test_challenges_by_candidate_keeps_high_only(self) -> None:
        grouped = challenges_by_candidate(
            [
                {"candidate_index": 0, "issue": "wrong RV", "severity": "high", "field": "rv"},
                {"candidate_index": 0, "issue": "style", "severity": "low", "field": "notes"},
                {"candidate_index": -1, "issue": "missing star", "severity": "high", "field": "candidates"},
            ]
        )
        self.assertEqual(set(grouped), {0, -1})
        self.assertEqual(len(grouped[0]), 1)

    def test_reviewer_roster_adds_deletes_and_retains_by_record_id(self) -> None:
        def stub(record_id: str) -> dict:
            return {"identifiers": {"record_id": record_id}}

        old = [stub("p:cand-001"), stub("p:cand-002")]
        records = [[{"value": "keep"}], [{"value": "delete"}]]
        new = [stub("p:cand-001"), stub("p:cand-003")]
        aligned, added, deleted = reconcile_roster_records(old, records, new)
        self.assertEqual(aligned, [[{"value": "keep"}], None])
        self.assertEqual(added, ["p:cand-003"])
        self.assertEqual(deleted, ["p:cand-002"])

    def test_reviewer_failure_can_never_be_success(self) -> None:
        self.assertEqual(
            agentic_delivery_status(review_failed=True, errors=[], cjk_paths=[]),
            "review_failed",
        )


if __name__ == "__main__":
    unittest.main()
