"""Roster stage orchestration tests: single/ensemble variants (D022-D024, D047, D052)."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from stella.benchmark.scratch.method_config import (
    ScratchComponentHashes,
    ScratchContextBudget,
    ScratchMethodConfig,
    ScratchModelRoute,
)
from stella.benchmark.scratch.prepare import (
    build_prepared_input,
    write_prepared_input,
)
from stella.benchmark.scratch.roster_stage import (
    ROSTER_COMPLETE,
    ROSTER_FAILED,
    run_roster_stage,
)


ROOT = Path(__file__).resolve().parents[1]
ARXIV_ID = "2406.99998"
RUN_ID = "run-roster-test"
MAIN_TEX = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "We confirm HVS-1 is unbound from the Galaxy.\n"
    "Gaia DR3 123456789 is another name for HVS-1.\n"
    "WD-9 was reviewed and is bound.\n"
    "\\end{document}\n"
)

VALID_SUBMISSION = {
    "candidates": [
        {
            "identifiers": [
                {
                    "value": "HVS-1",
                    "source_refs": [{"path": "main.tex", "start_line": 3, "end_line": 3}],
                },
                {
                    "value": "Gaia DR3 123456789",
                    "source_refs": [{"path": "main.tex", "start_line": 4, "end_line": 4}],
                },
            ],
            "qualification": {
                "reason": "The paper concludes HVS-1 is unbound.",
                "source_refs": [{"path": "main.tex", "start_line": 3, "end_line": 3}],
            },
        }
    ],
    "reviewed_exclusions": [
        {
            "subject": "WD-9",
            "reason": "The paper concludes WD-9 is bound.",
            "source_refs": [{"path": "main.tex", "start_line": 5, "end_line": 5}],
        }
    ],
}

BROKEN_SUBMISSION = {
    "candidates": [
        {
            "identifiers": [
                {
                    "value": "GHOST-9",
                    "source_refs": [{"path": "main.tex", "start_line": 3, "end_line": 3}],
                }
            ],
            "qualification": {
                "reason": "The paper concludes GHOST-9 is unbound.",
                "source_refs": [{"path": "main.tex", "start_line": 3, "end_line": 3}],
            },
        }
    ],
    "reviewed_exclusions": [],
}


def budget() -> ScratchContextBudget:
    return ScratchContextBudget(
        model_context_limit=900000,
        reserve_system_and_rules=8000,
        reserve_tool_schema=4000,
        reserve_candidate_suffix=0,
        reserve_output=8000,
        reserve_provider_framing=1000,
    )


def frozen_config() -> ScratchMethodConfig:
    extractor = ScratchModelRoute(
        provider="deepseek",
        model="deepseek-v4-pro",
        structured_output_mode="tool_submission",
        temperature=0.2,
        top_p=1.0,
        seed_honored=True,
    )
    adjudicator = ScratchModelRoute(
        provider="bigmodel",
        model="glm-5.2",
        structured_output_mode="tool_submission",
        temperature=0.0,
        top_p=1.0,
        seed_honored=False,
    )
    return ScratchMethodConfig(
        roster_extractor=extractor,
        roster_adjudicator=adjudicator,
        field_extractor=extractor,
        roster_extractor_seeds=(101, 202, 303),
        roster_context_budget=budget(),
        field_context_budget=budget(),
        components=ScratchComponentHashes(
            rule_profile_sha256={"hvs_roster_scratch": "a" * 64},
            prompt_template_sha256={"roster_extractor": "b" * 64},
            submission_schema_sha256={"submit_candidate_roster": "c" * 64},
        ),
    )


def make_workspace(tmp: str) -> Path:
    workspace = Path(tmp)
    # The production workspace is the repository root; mirror the rule library.
    shutil.copytree(
        ROOT / "skills/hvs-candidates-extraction/rules",
        workspace / "skills/hvs-candidates-extraction/rules",
    )
    paper_dir = workspace / "literature" / ARXIV_ID
    (paper_dir / "arxiv_source").mkdir(parents=True)
    (paper_dir / "arxiv_source" / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    artifact = build_prepared_input(
        workspace,
        ARXIV_ID,
        roster_budget=budget(),
        field_budget=budget(),
    )
    assert artifact["status"] == "prepared", artifact.get("failure")
    write_prepared_input(workspace, RUN_ID, artifact)
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
                        }
                    ],
                },
            }
        ]
    }


def tool_name_of(kwargs: dict) -> str:
    return kwargs["extra_body"]["tools"][0]["function"]["name"]


def seed_of(kwargs: dict) -> int | None:
    return kwargs["extra_body"].get("seed")


class RecordingTransport:
    def __init__(self, handler) -> None:
        self.handler = handler
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.handler(kwargs)


class RosterStageSingleTest(unittest.TestCase):
    def test_single_variant_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            transport = RecordingTransport(
                lambda kwargs: fake_response(VALID_SUBMISSION, tool_name=tool_name_of(kwargs))
            )
            artifact = run_roster_stage(
                workspace,
                RUN_ID,
                ARXIV_ID,
                config=frozen_config(),
                variant="single",
                transport=transport,
                sleep=lambda _: None,
            )
            self.assertEqual(artifact["status"], ROSTER_COMPLETE)
            self.assertEqual(artifact["roster_status"], "candidates_found")
            self.assertFalse(artifact["degraded_ensemble"])
            (candidate,) = artifact["candidates"]
            self.assertEqual(candidate["record_id"], "candidate-001")
            self.assertEqual(candidate["display_name"], "HVS-1")
            gaia = candidate["identifiers"][1]
            self.assertEqual(
                gaia["recognition"],
                {"kind": "gaia", "release": "DR3", "source_id": "123456789"},
            )
            self.assertEqual(
                candidate["identifiers"][0]["recognition"], {"kind": "other"}
            )
            resolved = candidate["qualification"]["source_refs"][0]["resolved_text"]
            self.assertEqual(resolved, "We confirm HVS-1 is unbound from the Galaxy.")
            # Exactly one extractor call, no adjudicator call.
            self.assertEqual(len(transport.calls), 1)
            names = {tool_name_of(call) for call in transport.calls}
            self.assertEqual(names, {"submit_candidate_roster"})
            # Program-hidden context: paper identity never enters the prompts.
            for call in transport.calls:
                for message in call["messages"]:
                    self.assertNotIn(ARXIV_ID, message["content"])
            # Proposal and final artifacts persisted.
            paper_dir = (
                workspace
                / "benchmark/scratch/hvs-extraction/runs"
                / RUN_ID
                / "papers"
                / ARXIV_ID
            )
            proposal = json.loads(
                (paper_dir / "roster_proposal-slot-0.json").read_text(encoding="utf-8")
            )
            self.assertEqual(proposal["status"], "valid")
            self.assertEqual(proposal["seed"], 101)
            final = json.loads(
                (paper_dir / "roster_final.json").read_text(encoding="utf-8")
            )
            self.assertEqual(final["status"], ROSTER_COMPLETE)

    def test_empty_roster_derives_no_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            empty = {"candidates": [], "reviewed_exclusions": VALID_SUBMISSION["reviewed_exclusions"]}
            transport = RecordingTransport(
                lambda kwargs: fake_response(empty, tool_name=tool_name_of(kwargs))
            )
            artifact = run_roster_stage(
                workspace,
                RUN_ID,
                ARXIV_ID,
                config=frozen_config(),
                variant="single",
                transport=transport,
                sleep=lambda _: None,
            )
            self.assertEqual(artifact["status"], ROSTER_COMPLETE)
            self.assertEqual(artifact["roster_status"], "no_candidates")
            self.assertEqual(artifact["candidates"], [])
            self.assertEqual(len(artifact["reviewed_exclusions"]), 1)

    def test_single_variant_terminal_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            transport = RecordingTransport(
                lambda kwargs: fake_response(BROKEN_SUBMISSION, tool_name=tool_name_of(kwargs))
            )
            artifact = run_roster_stage(
                workspace,
                RUN_ID,
                ARXIV_ID,
                config=frozen_config(),
                variant="single",
                transport=transport,
                sleep=lambda _: None,
            )
            self.assertEqual(artifact["status"], ROSTER_FAILED)
            self.assertEqual(artifact["failure"]["code"], "extractor_terminal_failure")

    def test_failed_slot_records_attempts_and_usages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)

            def handler(kwargs: dict):
                response = fake_response(BROKEN_SUBMISSION, tool_name=tool_name_of(kwargs))
                response["usage"] = {"total_tokens": 5}
                return response

            transport = RecordingTransport(handler)
            artifact = run_roster_stage(
                workspace,
                RUN_ID,
                ARXIV_ID,
                config=frozen_config(),
                variant="single",
                transport=transport,
                sleep=lambda _: None,
            )
            self.assertEqual(artifact["status"], ROSTER_FAILED)
            paper_dir = (
                workspace
                / "benchmark/scratch/hvs-extraction/runs"
                / RUN_ID
                / "papers"
                / ARXIV_ID
            )
            proposal = json.loads(
                (paper_dir / "roster_proposal-slot-0.json").read_text(encoding="utf-8")
            )
            self.assertEqual(proposal["status"], "failed")
            # Initial call plus the evidence correction call: both consumed
            # tokens and both must reach the cost ledger.
            self.assertEqual(len(proposal["attempts"]), 2)
            self.assertEqual(
                [usage["total_tokens"] for usage in proposal["usages"]], [5, 5]
            )

    def test_context_mutation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            prepared_path = (
                workspace
                / "benchmark/scratch/hvs-extraction/runs"
                / RUN_ID
                / "prepared_inputs"
                / f"{ARXIV_ID}.json"
            )
            prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
            prepared["manuscript"]["files"]["main.tex"]["sha256"] = "0" * 64
            prepared_path.write_text(json.dumps(prepared), encoding="utf-8")
            transport = RecordingTransport(
                lambda kwargs: fake_response(VALID_SUBMISSION, tool_name=tool_name_of(kwargs))
            )
            artifact = run_roster_stage(
                workspace,
                RUN_ID,
                ARXIV_ID,
                config=frozen_config(),
                variant="single",
                transport=transport,
                sleep=lambda _: None,
            )
            self.assertEqual(artifact["status"], ROSTER_FAILED)
            self.assertEqual(artifact["failure"]["code"], "context_mutation")
            self.assertEqual(transport.calls, [])

    def test_oversize_request_stops_without_api_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            tiny = ScratchContextBudget(
                model_context_limit=100,
                reserve_system_and_rules=0,
                reserve_tool_schema=0,
                reserve_candidate_suffix=0,
                reserve_output=0,
                reserve_provider_framing=0,
            )
            config = frozen_config().model_copy(
                update={"roster_context_budget": tiny}
            )
            transport = RecordingTransport(
                lambda kwargs: fake_response(VALID_SUBMISSION, tool_name=tool_name_of(kwargs))
            )
            artifact = run_roster_stage(
                workspace,
                RUN_ID,
                ARXIV_ID,
                config=config,
                variant="single",
                transport=transport,
                sleep=lambda _: None,
            )
            self.assertEqual(artifact["status"], ROSTER_FAILED)
            self.assertEqual(transport.calls, [])
            paper_dir = (
                workspace
                / "benchmark/scratch/hvs-extraction/runs"
                / RUN_ID
                / "papers"
                / ARXIV_ID
            )
            proposal = json.loads(
                (paper_dir / "roster_proposal-slot-0.json").read_text(encoding="utf-8")
            )
            self.assertEqual(proposal["failure"]["status"], "input_too_large")


class RosterStageEnsembleTest(unittest.TestCase):
    def handler(self, kwargs: dict):
        name = tool_name_of(kwargs)
        seed = seed_of(kwargs)
        if name == "submit_candidate_roster" and seed == 202:
            return fake_response(BROKEN_SUBMISSION, tool_name=name)
        return fake_response(VALID_SUBMISSION, tool_name=name)

    def test_ensemble_three_valid_proposals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            transport = RecordingTransport(
                lambda kwargs: fake_response(VALID_SUBMISSION, tool_name=tool_name_of(kwargs))
            )
            artifact = run_roster_stage(
                workspace,
                RUN_ID,
                ARXIV_ID,
                config=frozen_config(),
                variant="ensemble",
                transport=transport,
                sleep=lambda _: None,
            )
            self.assertEqual(artifact["status"], ROSTER_COMPLETE)
            self.assertFalse(artifact["degraded_ensemble"])
            self.assertEqual(len(transport.calls), 4)
            adjudicator_calls = [
                call for call in transport.calls if tool_name_of(call) == "submit_final_candidate_roster"
            ]
            self.assertEqual(len(adjudicator_calls), 1)
            user = adjudicator_calls[0]["messages"][1]["content"]
            self.assertIn("Proposal A", user)
            self.assertIn("Proposal B", user)
            self.assertIn("Proposal C", user)
            mapping = artifact["proposals"]["label_mapping"]
            self.assertEqual(sorted(mapping.values()), [0, 1, 2])
            # Anonymity: no slot numbers or seeds visible in the adjudicator context.
            self.assertNotIn("slot", user)
            self.assertNotIn("101", user)
            self.assertNotIn("202", user)
            self.assertNotIn("303", user)

    def test_ensemble_degraded_with_two_valid_proposals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            transport = RecordingTransport(self.handler)
            artifact = run_roster_stage(
                workspace,
                RUN_ID,
                ARXIV_ID,
                config=frozen_config(),
                variant="ensemble",
                transport=transport,
                sleep=lambda _: None,
            )
            self.assertEqual(artifact["status"], ROSTER_COMPLETE)
            self.assertTrue(artifact["degraded_ensemble"])
            adjudicator_calls = [
                call for call in transport.calls if tool_name_of(call) == "submit_final_candidate_roster"
            ]
            self.assertEqual(len(adjudicator_calls), 1)
            user = adjudicator_calls[0]["messages"][1]["content"]
            self.assertIn("Proposal A", user)
            self.assertIn("Proposal B", user)
            self.assertNotIn("Proposal C", user)
            # The invalid slot's broken submission never reaches the adjudicator.
            self.assertNotIn("GHOST-9", user)
            slots = {item["slot"]: item["status"] for item in artifact["proposals"]["slots"]}
            self.assertEqual(slots[1], "failed")

    def test_ensemble_fails_below_two_valid_proposals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)

            def handler(kwargs: dict):
                if tool_name_of(kwargs) == "submit_final_candidate_roster":
                    return fake_response(VALID_SUBMISSION, tool_name=tool_name_of(kwargs))
                return fake_response(BROKEN_SUBMISSION, tool_name=tool_name_of(kwargs))

            transport = RecordingTransport(handler)
            artifact = run_roster_stage(
                workspace,
                RUN_ID,
                ARXIV_ID,
                config=frozen_config(),
                variant="ensemble",
                transport=transport,
                sleep=lambda _: None,
            )
            self.assertEqual(artifact["status"], ROSTER_FAILED)
            self.assertEqual(artifact["failure"]["code"], "insufficient_valid_proposals")
            self.assertFalse(
                any(tool_name_of(call) == "submit_final_candidate_roster" for call in transport.calls)
            )

    def test_adjudicator_failure_records_attempts_and_usages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)

            def handler(kwargs: dict):
                name = tool_name_of(kwargs)
                if name == "submit_final_candidate_roster":
                    response = fake_response(BROKEN_SUBMISSION, tool_name=name)
                    response["usage"] = {"total_tokens": 7}
                    return response
                return fake_response(VALID_SUBMISSION, tool_name=name)

            transport = RecordingTransport(handler)
            artifact = run_roster_stage(
                workspace,
                RUN_ID,
                ARXIV_ID,
                config=frozen_config(),
                variant="ensemble",
                transport=transport,
                sleep=lambda _: None,
            )
            self.assertEqual(artifact["status"], ROSTER_FAILED)
            self.assertEqual(
                artifact["failure"]["code"], "adjudicator_terminal_failure"
            )
            # Initial adjudicator call plus the evidence correction call:
            # attempts and tokens must reach the ledger even on failure.
            provenance = artifact["provenance"]
            self.assertEqual(len(provenance["adjudicator_attempts"]), 2)
            self.assertEqual(
                [usage["total_tokens"] for usage in provenance["adjudicator_usages"]],
                [7, 7],
            )

    def test_shuffle_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            mappings = []
            for _ in range(2):
                transport = RecordingTransport(
                    lambda kwargs: fake_response(VALID_SUBMISSION, tool_name=tool_name_of(kwargs))
                )
                artifact = run_roster_stage(
                    workspace,
                    RUN_ID,
                    ARXIV_ID,
                    config=frozen_config(),
                    variant="ensemble",
                    transport=transport,
                    sleep=lambda _: None,
                )
                mappings.append(artifact["proposals"]["label_mapping"])
            self.assertEqual(mappings[0], mappings[1])


class RosterStageCorrectionTest(unittest.TestCase):
    def test_evidence_correction_repair_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            state = {"extractor_calls": 0}
            # Only the first identifier is broken (not verbatim); the repair
            # changes exactly that subtree and nothing else.
            broken = json.loads(json.dumps(VALID_SUBMISSION))
            broken["candidates"][0]["identifiers"][0]["value"] = "GHOST-9"

            def handler(kwargs: dict):
                if tool_name_of(kwargs) == "submit_final_candidate_roster":
                    return fake_response(VALID_SUBMISSION, tool_name=tool_name_of(kwargs))
                state["extractor_calls"] += 1
                if state["extractor_calls"] == 1:
                    return fake_response(broken, tool_name=tool_name_of(kwargs))
                return fake_response(VALID_SUBMISSION, tool_name=tool_name_of(kwargs))

            transport = RecordingTransport(handler)
            artifact = run_roster_stage(
                workspace,
                RUN_ID,
                ARXIV_ID,
                config=frozen_config(),
                variant="single",
                transport=transport,
                sleep=lambda _: None,
            )
            self.assertEqual(artifact["status"], ROSTER_COMPLETE)
            self.assertEqual(state["extractor_calls"], 2)
            correction_message = transport.calls[1]["messages"][-1]["content"]
            self.assertIn("EVIDENCE CORRECTION", correction_message)
            self.assertIn("identifier_not_verbatim", correction_message)


if __name__ == "__main__":
    unittest.main()
