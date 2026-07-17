from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from stella.benchmark.agentic_run import (
    PLAN_PAYLOAD_SCHEMA,
    ContextFS,
    ReactUnit,
    assemble_plan_scaffold,
    build_agentic_plan_system_prompt,
    plan_task_prompt,
    reconcile_roster_records,
    run_paper_agentic,
)
from stella.benchmark.extraction_review import (
    DEFAULT_REVIEWER_MODEL,
    challenges_by_candidate,
    normalize_review_payload,
    review_structure_errors,
    reviewed_delivery_status,
    run_agentic_roster_review,
)
from stella.benchmark.context_pack import PackedContext, PackedFile
from stella.benchmark.tool_loop import accumulate_usage
from stella.lit.extraction_rules import render_rule_profile


ROOT = Path(__file__).resolve().parents[1]
ARXIV = "9901.00001"


def make_skill_files(workspace: Path) -> None:
    skill_dir = workspace / "skills" / "hvs-candidates-extraction"
    (skill_dir / "references").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Skill\nExtract.", encoding="utf-8")
    (skill_dir / "references" / "schema.md").write_text("# Schema", encoding="utf-8")
    (skill_dir / "references" / "coordinate_frames.md").write_text(
        "# Frames", encoding="utf-8"
    )
    shutil.copytree(
        ROOT / "skills" / "hvs-candidates-extraction" / "rules",
        skill_dir / "rules",
    )


def make_paper_dir(workspace: Path, arxiv_id: str = ARXIV) -> Path:
    paper_dir = workspace / "literature" / arxiv_id
    (paper_dir / "arxiv_source").mkdir(parents=True)
    (paper_dir / "catalog_tables").mkdir()
    (paper_dir / "audit.json").write_text(
        json.dumps(
            {
                "arxiv_id": arxiv_id,
                "title": "A synthetic paper",
                "month": "2099-01",
                "source_note_json": "",
            }
        ),
        encoding="utf-8",
    )
    (paper_dir / "catalog_review.json").write_text(
        json.dumps({"schema_version": "x", "tables": []}), encoding="utf-8"
    )
    ecsv_rel = f"literature/{arxiv_id}/catalog_tables/table-a.ecsv"
    (paper_dir / "catalog_extraction.json").write_text(
        json.dumps(
            {
                "schema_version": "x",
                "tables": [{"status": "success", "ecsv_path": ecsv_rel}],
            }
        ),
        encoding="utf-8",
    )
    (paper_dir / "catalog_tables" / "table-a.ecsv").write_text(
        "# %ECSV 1.0\nname,rv\nStarA,612.3\n", encoding="utf-8"
    )
    (paper_dir / "arxiv_source" / "paper.tex").write_text(
        "\\title{Synthetic}\nStarA has rv 612.3 km/s.\n", encoding="utf-8"
    )
    return paper_dir


class FakeValidator:
    def validate_hvs_candidates_report(self, payload, *, workspace, require_complete):
        return type("Report", (), {"errors": [], "warnings": []})()


class UsageAccumulationTest(unittest.TestCase):
    def test_cache_hit_variants_are_normalized(self) -> None:
        totals: dict[str, int] = {}
        accumulate_usage(totals, {"prompt_cache_hit_tokens": 7})
        accumulate_usage(
            totals,
            {"prompt_tokens_details": {"cached_tokens": 11}},
        )
        self.assertEqual(totals["prompt_cache_hit_tokens"], 18)

    def test_direct_cache_field_takes_precedence(self) -> None:
        totals: dict[str, int] = {}
        accumulate_usage(
            totals,
            {
                "prompt_cache_hit_tokens": 7,
                "prompt_tokens_details": {"cached_tokens": 11},
            },
        )
        self.assertEqual(totals["prompt_cache_hit_tokens"], 7)


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

    def test_plan_prompt_and_merge_keep_code_owned_document_small(self) -> None:
        skeleton = {
            "schema": {"name": "literature_hvs_candidates", "version": 2},
            "paper": {"arxiv_id": "9901.00001"},
            "inputs": {"paper_dir": "literature/9901.00001"},
            "candidates": [],
        }
        frozen = [{"identifiers": {"record_id": "9901.00001:cand-001"}}]
        prompt = plan_task_prompt(
            skeleton,
            self.fs,
            render_rule_profile(ROOT, "hvs_roster", "prompt"),
            frozen_roster_bundle={"candidates": frozen},
        )
        plan = {
            "extraction": {"status": "candidates_found", "summary": "one"},
            "method_chain": [],
            "candidate_groups_considered": [],
        }

        merged = assemble_plan_scaffold(skeleton, plan, frozen)

        self.assertIn("compact object under the `plan` key", prompt)
        self.assertIn("Do not return `candidates`", prompt)
        self.assertEqual(merged["schema"], skeleton["schema"])
        self.assertEqual(merged["paper"], skeleton["paper"])
        self.assertEqual(merged["candidates"], frozen)
        self.assertFalse(
            set(plan) - set(PLAN_PAYLOAD_SCHEMA["properties"])
        )
        plan_system = build_agentic_plan_system_prompt(ROOT, "core_prov")
        self.assertIn("candidate records", plan_system)
        self.assertNotIn("COORDINATE FRAME REFERENCE", plan_system)


def tool_call(name: str, arguments: dict, call_id: str = "call-1") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def raw_tool_call(name: str, arguments: str, call_id: str = "call-1") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def response_with(message: dict, *, finish_reason: str = "stop") -> dict:
    return {
        "model": "fake-model",
        "choices": [{"message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


class ScriptedTransport:
    def __init__(self, replies: list[dict]) -> None:
        self.replies = list(replies)
        self.requests: list[list[dict]] = []
        self.call_kwargs: list[dict] = []

    def __call__(self, *, messages: list[dict], **kwargs: object) -> dict:
        self.requests.append([dict(m) for m in messages])
        self.call_kwargs.append(dict(kwargs))
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


def make_review_unit(transport: ScriptedTransport) -> ReactUnit:
    return ReactUnit(
        name="review",
        kind="review",
        system_prompt="system",
        task_prompt="task",
        fs=ContextFS(packed_context()),
        submit_name="submit_review",
        submit_key="review",
        submit_check=review_structure_errors,
        transport=transport,
        transport_kwargs={"extra_body": {}},
        archive=lambda name, response, messages: None,
        usage_totals={},
        finalization_calls=2,
        stall_on_repeated_tool_batch=True,
    )


class ReactUnitTest(unittest.TestCase):
    def test_malformed_tool_arguments_are_reported_not_coerced_to_empty_object(self) -> None:
        transport = ScriptedTransport(
            [
                response_with(
                    {
                        "content": "",
                        "tool_calls": [
                            raw_tool_call(
                                "submit_candidate",
                                '{"candidate":{"ok":true}',
                            )
                        ],
                    }
                ),
                response_with(
                    {
                        "content": "",
                        "tool_calls": [
                            tool_call("submit_candidate", {"candidate": {"ok": True}})
                        ],
                    }
                ),
            ]
        )
        unit = make_unit(transport, lambda payload: [])

        self.assertEqual(unit.run(), {"ok": True})
        feedback = transport.requests[1][-1]["content"]
        self.assertIn("MALFORMED_TOOL_ARGUMENTS", feedback)
        self.assertIn("not treated as an empty object", feedback)

    def test_repeated_rejected_submit_forces_small_finalization(self) -> None:
        repeated = response_with(
            {
                "content": "",
                "tool_calls": [tool_call("submit_candidate", {})],
            }
        )
        transport = ScriptedTransport(
            [
                repeated,
                repeated,
                response_with(
                    {
                        "content": "",
                        "tool_calls": [
                            tool_call("submit_candidate", {"candidate": {"ok": True}})
                        ],
                    }
                ),
            ]
        )
        unit = ReactUnit(
            name="candidate",
            kind="candidate",
            system_prompt="system",
            task_prompt="task",
            fs=ContextFS(packed_context()),
            submit_name="submit_candidate",
            submit_key="candidate",
            submit_check=lambda payload: [],
            transport=transport,
            transport_kwargs={"extra_body": {}},
            archive=lambda name, response, messages: None,
            usage_totals={},
            finalization_calls=2,
            stall_on_repeated_tool_batch=True,
        )

        self.assertEqual(unit.run(budget=8), {"ok": True})
        self.assertEqual(unit.calls, 3)
        self.assertEqual(unit.stop_reason, "candidate_repeated_tool_stall")
        self.assertEqual(
            transport.call_kwargs[2]["extra_body"]["tool_choice"]["function"]["name"],
            "submit_candidate",
        )

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

    def test_repeated_review_tool_batch_forces_submission(self) -> None:
        read = response_with(
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
        )
        transport = ScriptedTransport(
            [
                read,
                read,
                response_with(
                    {
                        "content": "",
                        "tool_calls": [
                            tool_call(
                                "submit_review",
                                {
                                    "review": {
                                        "challenges": [],
                                        "summary": "sound",
                                    }
                                },
                            )
                        ],
                    }
                ),
            ]
        )
        unit = make_review_unit(transport)

        payload = unit.run(budget=8)

        self.assertEqual(payload, {"challenges": [], "summary": "sound"})
        self.assertEqual(unit.calls, 3)
        self.assertEqual(unit.stop_reason, "review_repeated_tool_stall")
        self.assertEqual(
            transport.call_kwargs[2]["extra_body"]["tool_choice"]["function"]["name"],
            "submit_review",
        )

    def test_review_length_response_forces_submission(self) -> None:
        transport = ScriptedTransport(
            [
                response_with(
                    {"content": "", "reasoning_content": "unfinished"},
                    finish_reason="length",
                ),
                response_with(
                    {
                        "content": "",
                        "tool_calls": [
                            tool_call(
                                "submit_review",
                                {
                                    "review": {
                                        "challenges": [],
                                        "summary": "recovered",
                                    }
                                },
                            )
                        ],
                    }
                ),
            ]
        )
        unit = make_review_unit(transport)

        payload = unit.run(budget=8)

        self.assertEqual(payload, {"challenges": [], "summary": "recovered"})
        self.assertEqual(unit.stop_reason, "review_length_exhausted")
        self.assertEqual(
            transport.call_kwargs[1]["extra_body"]["tool_choice"]["function"]["name"],
            "submit_review",
        )

    def test_review_finalization_failure_has_explicit_reason(self) -> None:
        repeated_read = response_with(
            {
                "content": "",
                "tool_calls": [tool_call("list_files", {})],
            }
        )
        transport = ScriptedTransport(
            [repeated_read, repeated_read, repeated_read, repeated_read]
        )
        unit = make_review_unit(transport)

        self.assertIsNone(unit.run(budget=8))

        self.assertEqual(unit.calls, 4)
        self.assertIn("review_submission_missing", unit.failure_reason)
        self.assertIn("review_repeated_tool_stall", unit.failure_reason)
        self.assertIn("submit_review", unit.failure_reason)

    def test_review_reserves_last_calls_for_budget_finalization(self) -> None:
        transport = ScriptedTransport(
            [
                response_with(
                    {
                        "content": "",
                        "tool_calls": [tool_call("list_files", {})],
                    }
                ),
                response_with(
                    {
                        "content": "",
                        "tool_calls": [tool_call("search", {"pattern": "HVS"})],
                    }
                ),
                response_with(
                    {
                        "content": "",
                        "tool_calls": [
                            tool_call(
                                "submit_review",
                                {
                                    "review": {
                                        "challenges": [],
                                        "summary": "budget bounded",
                                    }
                                },
                            )
                        ],
                    }
                ),
            ]
        )
        unit = make_review_unit(transport)

        payload = unit.run(budget=4)

        self.assertEqual(
            payload, {"challenges": [], "summary": "budget bounded"}
        )
        self.assertEqual(unit.stop_reason, "review_research_budget_exhausted")
        self.assertEqual(
            transport.call_kwargs[2]["extra_body"]["tool_choice"]["function"]["name"],
            "submit_review",
        )


class ReviewContractTest(unittest.TestCase):
    def test_review_structure_errors(self) -> None:
        self.assertTrue(review_structure_errors({"nope": []}))
        self.assertIn(
            "review.summary is required",
            review_structure_errors({"challenges": []}),
        )
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

    def test_method_semantics_are_forced_low_but_structural_breakage_stays_high(self) -> None:
        payload = normalize_review_payload(
            {
                "summary": "two method findings",
                "challenges": [
                    {
                        "candidate_index": 0,
                        "field": "method_chain",
                        "issue": "velocity lineage lacks a solar_position_and_motion step",
                        "severity": "high",
                    },
                    {
                        "candidate_index": 0,
                        "field": "method_refs",
                        "issue": "method_ref points to an unknown step id",
                        "severity": "high",
                    },
                ],
            }
        )
        self.assertEqual(payload["challenges"][0]["severity"], "low")
        self.assertEqual(payload["challenges"][1]["severity"], "high")
        self.assertEqual(
            challenges_by_candidate(payload["challenges"]),
            {0: ["method_refs: method_ref points to an unknown step id"]},
        )

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
            reviewed_delivery_status(review_failed=True, errors=[], cjk_paths=[]),
            "review_failed",
        )


def roster_stub(n: int) -> dict:
    identifiers = {
        "record_id": f"{ARXIV}:cand-{n:03d}",
        "paper_candidate_id": f"Star{n}",
        "gaia_source_id": "",
        "all": [
            {
                "value": f"Star{n}",
                "source_refs": [
                    {
                        "kind": "text",
                        "path": f"literature/{ARXIV}/arxiv_source/paper.tex",
                        "start_line": 2,
                        "end_line": 2,
                        "context": f"Star{n} has rv 612.3 km/s.",
                    }
                ],
            }
        ],
    }
    return {
        "identifiers": identifiers,
        "inclusion_anchor": {
            "summary": f"Star{n} is proposed as unbound.",
            "source_refs": [
                {
                    "kind": "text",
                    "path": f"literature/{ARXIV}/arxiv_source/paper.tex",
                    "start_line": 2,
                    "end_line": 2,
                    "context": f"Star{n} has rv 612.3 km/s.",
                }
            ],
        },
    }


def roster_doc(numbers: list[int]) -> dict:
    status = "candidates_found" if numbers else "no_candidates"
    return {
        "extraction": {"status": status, "summary": "roster"},
        "candidates": [roster_stub(n) for n in numbers],
        "candidate_groups_considered": [],
    }


def submit_response(submit_name: str, arguments: dict) -> dict:
    return response_with(
        {
            "content": "",
            "tool_calls": [tool_call(submit_name, arguments)],
        }
    )


class AgenticRosterReviewTest(unittest.TestCase):
    """Method C: one roster-only review runs before the roster is sealed."""

    def test_agentic_roster_review_receives_inclusion_anchors(self) -> None:
        captured: list[list[dict]] = []

        def transport(*, messages, extra_body=None, **kwargs):
            captured.append([dict(m) for m in messages])
            return submit_response(
                "submit_roster_review",
                {
                    "roster_review": {
                        "decision": "accept",
                        "challenges": [],
                        "summary": "membership is sound",
                    }
                },
            )

        outcome = run_agentic_roster_review(
            workspace=ROOT,
            roster=roster_doc([1, 2]),
            arxiv_id=ARXIV,
            fs=ContextFS(packed_context()),
            transport=transport,
            transport_kwargs={"extra_body": {}},
            archive=lambda name, response, messages: None,
            usage_totals={},
        )

        self.assertFalse(outcome.failed)
        self.assertEqual(outcome.calls, 1)
        self.assertEqual(outcome.payload["decision"], "accept")
        # Plan Step 2: the reviewer sees every inclusion_anchor, including
        # its paper-text source references.
        task_prompt = captured[0][1]["content"]
        self.assertIn("===== ROSTER UNDER REVIEW =====", task_prompt)
        self.assertIn('"inclusion_anchor"', task_prompt)
        self.assertIn("Star1 has rv 612.3 km/s.", task_prompt)
        self.assertIn("Star2 has rv 612.3 km/s.", task_prompt)
        # The only scientific rule source is the hvs_roster profile.
        self.assertIn(
            "===== ROSTER REVIEW RULE PROFILE: hvs_roster =====",
            captured[0][0]["content"],
        )

    def test_agentic_roster_review_rejects_malformed_revision(self) -> None:
        transport = ScriptedTransport(
            [
                submit_response(
                    "submit_roster_review",
                    {
                        "roster_review": {
                            "decision": "revise",
                            "challenges": [],
                            "summary": "broken revision",
                        }
                    },
                ),
                submit_response(
                    "submit_roster_review",
                    {
                        "roster_review": {
                            "decision": "accept",
                            "challenges": [],
                            "summary": "sound after all",
                        }
                    },
                ),
            ]
        )

        outcome = run_agentic_roster_review(
            workspace=ROOT,
            roster=roster_doc([1]),
            arxiv_id=ARXIV,
            fs=ContextFS(packed_context()),
            transport=transport,
            transport_kwargs={"extra_body": {}},
            archive=lambda name, response, messages: None,
            usage_totals={},
        )

        self.assertFalse(outcome.failed)
        self.assertEqual(outcome.payload["decision"], "accept")
        rejected = transport.requests[1][-1]["content"]
        self.assertIn("REJECTED", rejected)
        self.assertIn("revised_roster", rejected)


class AgenticRosterRunTest(unittest.TestCase):
    """End-to-end Method C run with a scripted tool transport."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name)
        make_paper_dir(self.workspace)
        make_skill_files(self.workspace)
        self.run_dir = self.workspace / "run"
        self.cache_root = self.workspace / "roster-cache"
        self.roster_review_requests: list[list[dict]] = []
        self.candidate_requests: list[list[dict]] = []
        self.review_requests: list[list[dict]] = []

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def dispatcher(self, roster_review_payload: dict):
        def transport(*, messages, extra_body=None, **kwargs):
            tools = (extra_body or {}).get("tools") or []
            submit_names = {
                tool.get("function", {}).get("name")
                for tool in tools
                if isinstance(tool, dict)
            }
            snapshot = [dict(m) for m in messages]
            if "submit_roster_review" in submit_names:
                self.roster_review_requests.append(snapshot)
                return submit_response(
                    "submit_roster_review", {"roster_review": roster_review_payload}
                )
            if "submit_roster" in submit_names:
                return submit_response(
                    "submit_roster", {"roster": roster_doc([1, 2])}
                )
            if "submit_scaffold" in submit_names:
                return submit_response(
                    "submit_scaffold",
                    {
                        "plan": {
                            "extraction": {
                                "status": "candidates_found",
                                "summary": "one candidate",
                            },
                            "method_chain": [
                                {"id": "step-01", "step_type": "input_catalog"}
                            ],
                            "candidate_groups_considered": [],
                        }
                    },
                )
            if "submit_review" in submit_names:
                self.review_requests.append(snapshot)
                return submit_response(
                    "submit_review",
                    {"review": {"challenges": [], "summary": "sound"}},
                )
            if "submit_candidate" in submit_names:
                self.candidate_requests.append(snapshot)
                task = snapshot[-1].get("content", "")
                number = 2 if f"{ARXIV}:cand-002" in task else 1
                return submit_response(
                    "submit_candidate",
                    {
                        "candidate": {
                            "identifiers": roster_stub(number)["identifiers"],
                            "filled": True,
                        }
                    },
                )
            raise AssertionError(f"no submit tool offered: {submit_names}")

        return transport

    def run_one(self, roster_review_payload: dict):
        return run_paper_agentic(
            workspace=self.workspace,
            arxiv_id=ARXIV,
            run_dir=self.run_dir,
            api_key="k",
            base_url="https://example.invalid/v1",
            model="deepseek-v4-pro",
            reviewer_model=DEFAULT_REVIEWER_MODEL,
            prompt_version="abc1234",
            validator_module=FakeValidator(),
            transport=self.dispatcher(roster_review_payload),
            roster_cache_root=self.cache_root,
        )

    def test_roster_reviewer_revises_membership_before_sealing(self) -> None:
        # Plan Step 1 for Method C: the producer over-includes Star2 and the
        # roster reviewer removes it before the bundle hash exists.
        result = self.run_one(
            {
                "decision": "revise",
                "challenges": [
                    {"record_id": f"{ARXIV}:cand-002", "issue": "cite-in-passing only"}
                ],
                "summary": "Star2 must go",
                "revised_roster": roster_doc([1]),
            }
        )

        self.assertEqual(result.status, "ok")
        bundle = json.loads(
            (self.run_dir / ARXIV / "roster_bundle.json").read_text()
        )
        self.assertEqual(bundle["review"]["status"], "revised")
        self.assertEqual(len(bundle["candidates"]), 1)
        self.assertEqual(
            bundle["candidates"][0]["identifiers"]["paper_candidate_id"], "Star1"
        )
        self.assertEqual(
            bundle["review"]["provenance"]["model"], DEFAULT_REVIEWER_MODEL
        )
        self.assertEqual(len(bundle["review"]["provenance"]["prompt_sha256"]), 64)
        components = bundle["key_components"]
        self.assertEqual(components["reviewer_model"], DEFAULT_REVIEWER_MODEL)
        self.assertEqual(
            components["reviewer_rule_sha256"], components["rule_sha256"]
        )
        # Step 2: the roster reviewer saw the produced roster with anchors.
        self.assertEqual(len(self.roster_review_requests), 1)
        task_prompt = self.roster_review_requests[0][1]["content"]
        self.assertIn('"inclusion_anchor"', task_prompt)
        self.assertIn("Star2 has rv 612.3 km/s.", task_prompt)
        # Step 6: the sealed anchor reached the candidate fill and the final
        # review as read-only evidence.
        candidate_prompt = self.candidate_requests[0][1]["content"]
        self.assertIn("SEALED INCLUSION ANCHOR (read-only evidence)", candidate_prompt)
        self.assertIn("Star1 has rv 612.3 km/s.", candidate_prompt)
        review_prompt = self.review_requests[0][1]["content"]
        self.assertIn("sealed_roster_inclusion_anchors", review_prompt)
        self.assertIn("Do not challenge membership", review_prompt)
        # The final document carries the revised roster and no anchor fields.
        final = json.loads(
            (self.run_dir / ARXIV / "literature_hvs_candidates.json").read_text()
        )
        self.assertEqual(len(final["candidates"]), 1)
        self.assertEqual(
            final["candidates"][0]["identifiers"]["record_id"],
            f"{ARXIV}:cand-001",
        )
        self.assertNotIn("inclusion_anchor", final["candidates"][0])

    def test_roster_reviewer_accept_path(self) -> None:
        result = self.run_one(
            {"decision": "accept", "challenges": [], "summary": "sound"}
        )

        self.assertEqual(result.status, "ok")
        bundle = json.loads(
            (self.run_dir / ARXIV / "roster_bundle.json").read_text()
        )
        self.assertEqual(bundle["review"]["status"], "accepted")
        self.assertEqual(len(bundle["candidates"]), 2)
        # The candidate fill receives the sealed stub for cand-001 first.
        self.assertEqual(len(self.candidate_requests), 2)

    def test_run_applies_shared_mechanical_normalization(self) -> None:
        # Task 4: Method C shares Method B's representation-only normalizer —
        # coordinate punctuation is canonicalized, citation selection is the
        # model's own and is never rewritten by code.
        candidate = {
            "identifiers": roster_stub(1)["identifiers"],
            "filled": True,
            "core": {
                "observed_phase_space": {
                    "ra": {"value": "16:03:04.06", "coordinate_format": "sexagesimal_hms"},
                    "dec": {"value": "-66:13:26.9", "coordinate_format": "sexagesimal_dms"},
                }
            },
            "candidate_origin": {
                "citation": {"bibkey": "model-chosen-key", "bibliography_refs": []}
            },
        }

        def transport(*, messages, extra_body=None, **kwargs):
            tools = (extra_body or {}).get("tools") or []
            submit_names = {
                tool.get("function", {}).get("name")
                for tool in tools
                if isinstance(tool, dict)
            }
            if "submit_roster_review" in submit_names:
                return submit_response(
                    "submit_roster_review",
                    {"roster_review": {"decision": "accept", "challenges": [], "summary": "sound"}},
                )
            if "submit_roster" in submit_names:
                return submit_response("submit_roster", {"roster": roster_doc([1])})
            if "submit_scaffold" in submit_names:
                return submit_response(
                    "submit_scaffold",
                    {
                        "plan": {
                            "extraction": {
                                "status": "candidates_found",
                                "summary": "one candidate",
                            },
                            "method_chain": [
                                {"id": "step-01", "step_type": "input_catalog"}
                            ],
                            "candidate_groups_considered": [],
                        }
                    },
                )
            if "submit_review" in submit_names:
                return submit_response(
                    "submit_review",
                    {"review": {"challenges": [], "summary": "sound"}},
                )
            if "submit_candidate" in submit_names:
                return submit_response("submit_candidate", {"candidate": candidate})
            raise AssertionError(f"no submit tool offered: {submit_names}")

        result = run_paper_agentic(
            workspace=self.workspace,
            arxiv_id=ARXIV,
            run_dir=self.run_dir,
            api_key="k",
            base_url="https://example.invalid/v1",
            model="deepseek-v4-pro",
            reviewer_model=DEFAULT_REVIEWER_MODEL,
            prompt_version="abc1234",
            validator_module=FakeValidator(),
            transport=transport,
            roster_cache_root=self.cache_root,
        )

        self.assertEqual(result.status, "ok")
        final = json.loads(
            (self.run_dir / ARXIV / "literature_hvs_candidates.json").read_text()
        )
        observed = final["candidates"][0]["core"]["observed_phase_space"]
        self.assertEqual(observed["ra"]["value"], "16h03m04.06s")
        self.assertEqual(observed["dec"]["value"], "-66d13m26.9s")
        self.assertEqual(
            final["candidates"][0]["candidate_origin"]["citation"]["bibkey"],
            "model-chosen-key",
        )
        report = json.loads((self.run_dir / ARXIV / "report.json").read_text())
        normalization_stages = [
            entry
            for entry in report["stage_log"]
            if entry.get("stage") == "deterministic_normalization"
        ]
        self.assertEqual(len(normalization_stages), 1)
        self.assertEqual(
            normalization_stages[0]["changes"],
            ["candidates[0].ra.value", "candidates[0].dec.value"],
        )


class PostSealMembershipTest(unittest.TestCase):
    """Plan Step 7 for Method C: plan payloads cannot mutate the sealed roster."""

    def test_plan_payload_cannot_override_the_sealed_roster(self) -> None:
        from stella.benchmark.extraction_run import scaffold_structure_errors

        skeleton = {
            "schema": {"name": "literature_hvs_candidates", "version": 2},
            "paper": {"arxiv_id": ARXIV},
            "inputs": {"paper_dir": f"literature/{ARXIV}"},
            "candidates": [],
        }
        frozen = [{"identifiers": roster_stub(1)["identifiers"]}]
        plan = {
            "extraction": {"status": "candidates_found", "summary": "one"},
            "method_chain": [{"id": "step-01", "step_type": "input_catalog"}],
            "candidate_groups_considered": [],
            # A mutated plan-side roster must be ignored by the merge.
            "candidates": [
                {"identifiers": {"record_id": f"{ARXIV}:cand-099"}}
            ],
        }

        merged = assemble_plan_scaffold(skeleton, plan, frozen)

        self.assertEqual(merged["candidates"], frozen)
        self.assertEqual(
            scaffold_structure_errors(merged, ARXIV, frozen_roster=frozen), []
        )
        mutated = dict(merged)
        mutated["candidates"] = [
            {"identifiers": {"record_id": f"{ARXIV}:cand-099"}}
        ]
        self.assertTrue(
            scaffold_structure_errors(mutated, ARXIV, frozen_roster=frozen)
        )


if __name__ == "__main__":
    unittest.main()
