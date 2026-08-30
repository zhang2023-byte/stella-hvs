"""Contribution measurement stage orchestration tests (fake transports only)."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

from tests.hvs_contribution_fixtures import (
    MEASUREMENT_ARXIV_ID,
    MEASUREMENT_RUN_ID,
    MEASUREMENT_SUBMISSION,
    RecordingTransport,
    fake_response,
    frozen_contribution_config,
    make_measurement_workspace,
    measurement_value,
    tool_name_of,
)
from stella.lit.extraction.quantity_stage import (
    QUANTITY_EXTRACTION_COMPLETE,
    QUANTITY_EXTRACTION_FAILED,
    resume_quantity_stage,
    run_quantity_stage,
)
from stella.lit.extraction.transport import TransportExhausted

ROOT = Path(__file__).resolve().parents[3]


def run_dir_for(workspace: Path) -> Path:
    return workspace / "runs" / "hvs-contribution-extraction" / MEASUREMENT_RUN_ID


class MeasurementStageTest(unittest.TestCase):
    def test_resume_retries_only_network_failed_objects_and_archives_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_measurement_workspace(tmp)
            roster_path = (
                run_dir_for(workspace)
                / "papers"
                / MEASUREMENT_ARXIV_ID
                / "contribution_roster_final.json"
            )
            roster = json.loads(roster_path.read_text(encoding="utf-8"))
            base = roster["object_contributions"][0]
            roster["object_contributions"] = [
                {**base, "record_id": "obj-001"},
                {**base, "record_id": "obj-002"},
            ]
            roster_path.write_text(json.dumps(roster), encoding="utf-8")

            def initial_handler(kwargs: dict):
                content = kwargs["messages"][1]["content"]
                if "obj-002" in content:
                    raise TransportExhausted("temporary gateway failure")
                return fake_response(
                    MEASUREMENT_SUBMISSION,
                    tool_name=tool_name_of(kwargs),
                )

            initial = run_quantity_stage(
                workspace,
                MEASUREMENT_RUN_ID,
                MEASUREMENT_ARXIV_ID,
                config=frozen_contribution_config(),
                transport=RecordingTransport(initial_handler),
                quantity_concurrency=1,
                sleep=lambda _: None,
                run_dir=run_dir_for(workspace),
            )
            self.assertEqual(initial["status"], "complete_with_failures")
            objects_dir = (
                run_dir_for(workspace)
                / "papers"
                / MEASUREMENT_ARXIV_ID
                / "object_quantities"
            )
            successful_bytes = (objects_dir / "obj-001.json").read_bytes()
            calls: list[dict] = []

            def resumed_handler(kwargs: dict):
                calls.append(kwargs)
                return fake_response(
                    MEASUREMENT_SUBMISSION,
                    tool_name=tool_name_of(kwargs),
                )

            resumed = resume_quantity_stage(
                workspace,
                MEASUREMENT_RUN_ID,
                MEASUREMENT_ARXIV_ID,
                config=frozen_contribution_config(),
                transport=RecordingTransport(resumed_handler),
                quantity_concurrency=50,
                sleep=lambda _: None,
                run_dir=run_dir_for(workspace),
            )

            self.assertEqual(resumed["resumed_record_ids"], ["obj-002"])
            self.assertEqual(len(calls), 1)
            self.assertEqual((objects_dir / "obj-001.json").read_bytes(), successful_bytes)
            self.assertTrue(
                (
                    objects_dir.parent
                    / "object_quantity_attempts"
                    / "obj-002"
                    / "attempt-1.json"
                ).is_file()
            )

    def test_quantity_objects_run_concurrently_and_report_in_roster_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_measurement_workspace(tmp)
            roster_path = (
                run_dir_for(workspace)
                / "papers"
                / MEASUREMENT_ARXIV_ID
                / "contribution_roster_final.json"
            )
            roster = json.loads(roster_path.read_text(encoding="utf-8"))
            base = roster["object_contributions"][0]
            roster["object_contributions"] = [
                {**base, "record_id": f"obj-{index:03d}"}
                for index in range(1, 4)
            ]
            roster_path.write_text(json.dumps(roster), encoding="utf-8")

            barrier = threading.Barrier(3)
            lock = threading.Lock()
            active = 0
            maximum = 0

            def handler(kwargs: dict):
                nonlocal active, maximum
                with lock:
                    active += 1
                    maximum = max(maximum, active)
                try:
                    barrier.wait(timeout=2)
                    return fake_response(
                        MEASUREMENT_SUBMISSION,
                        tool_name=tool_name_of(kwargs),
                    )
                finally:
                    with lock:
                        active -= 1

            result = run_quantity_stage(
                workspace,
                MEASUREMENT_RUN_ID,
                MEASUREMENT_ARXIV_ID,
                config=frozen_contribution_config(),
                transport=RecordingTransport(handler),
                transport_factory=lambda: RecordingTransport(handler),
                quantity_concurrency=50,
                sleep=lambda _: None,
                run_dir=run_dir_for(workspace),
            )

            self.assertEqual(maximum, 3)
            self.assertEqual(
                list(result["objects"]),
                ["obj-001", "obj-002", "obj-003"],
            )

    def test_happy_path_delivers_grouped_multivalues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_measurement_workspace(tmp)
            transport = RecordingTransport(
                lambda kwargs: fake_response(MEASUREMENT_SUBMISSION, tool_name=tool_name_of(kwargs))
            )
            result = run_quantity_stage(
                workspace,
                MEASUREMENT_RUN_ID,
                MEASUREMENT_ARXIV_ID,
                config=frozen_contribution_config(),
                transport=transport,
                sleep=lambda _: None,
                run_dir=run_dir_for(workspace),
            )
            self.assertEqual(result["status"], "complete")
            self.assertEqual(len(transport.calls), 1)
            self.assertEqual(
                {tool_name_of(call) for call in transport.calls},
                {"submit_object_quantities"},
            )
            artifact = json.loads(
                (
                    run_dir_for(workspace)
                    / "papers"
                    / MEASUREMENT_ARXIV_ID
                    / "object_quantities"
                    / "obj-001.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(artifact["status"], QUANTITY_EXTRACTION_COMPLETE)
            self.assertIsNone(artifact["failure"])
            groups = {group["quantity"]: group for group in artifact["quantities"]}
            self.assertEqual(len(groups["observed_phase_space.distance"]["values"]), 4)
            self.assertEqual(len(groups["bound_assessment.unbound_probability"]["values"]), 1)
            # Assigned contribution context in the user message.
            self.assertIn("obj-001", transport.calls[0]["messages"][1]["content"])
            # Quantity rules, not roster or V6 rules.
            system = transport.calls[0]["messages"][0]["content"]
            self.assertIn("[hvs.contrib.all_values_after_l1]", system)
            self.assertNotIn("[hvs.contrib.follow_up]", system)
            self.assertNotIn("hvs.field.multiple_estimates", system)

    def test_failure_preserves_l1_deliverability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_measurement_workspace(tmp)
            invalid = {
                "quantities": [
                    {
                        "quantity": "observed_phase_space.distance",
                        "values": [
                            # Identifier-free locator pointing outside the file.
                            {
                                **measurement_value(),
                                "direct_evidence": [
                                    {
                                        "part": "value",
                                        "source": {
                                            "kind": "text",
                                            "path": "main.tex",
                                            "start_line": 999,
                                            "end_line": 999,
                                            "raw_value": "8.2",
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
            transport = RecordingTransport(
                lambda kwargs: fake_response(invalid, tool_name=tool_name_of(kwargs))
            )
            result = run_quantity_stage(
                workspace,
                MEASUREMENT_RUN_ID,
                MEASUREMENT_ARXIV_ID,
                config=frozen_contribution_config(),
                transport=transport,
                sleep=lambda _: None,
                run_dir=run_dir_for(workspace),
            )
            # The single roster object failed, so the paper-level status is
            # all_objects_failed while the L1 contribution stays deliverable.
            self.assertEqual(result["status"], "all_objects_failed")
            artifact = json.loads(
                (
                    run_dir_for(workspace)
                    / "papers"
                    / MEASUREMENT_ARXIV_ID
                    / "object_quantities"
                    / "obj-001.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(artifact["status"], QUANTITY_EXTRACTION_FAILED)
            self.assertEqual(artifact["quantities"], [])
            self.assertIsNotNone(artifact["failure"])
            self.assertIn("obj-001", artifact["record_id"])

    def test_missing_run_dir_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_measurement_workspace(tmp)
            with self.assertRaisesRegex(ValueError, "run_dir is required"):
                run_quantity_stage(
                    workspace,
                    MEASUREMENT_RUN_ID,
                    MEASUREMENT_ARXIV_ID,
                    config=frozen_contribution_config(),
                    transport=RecordingTransport(lambda kwargs: {}),
                    sleep=lambda _: None,
                )

    def test_no_trusted_roster_short_circuits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_measurement_workspace(tmp)
            roster_path = (
                run_dir_for(workspace)
                / "papers"
                / MEASUREMENT_ARXIV_ID
                / "contribution_roster_final.json"
            )
            roster = json.loads(roster_path.read_text(encoding="utf-8"))
            roster["status"] = "roster_failed"
            roster_path.write_text(json.dumps(roster), encoding="utf-8")
            transport = RecordingTransport(lambda kwargs: {})
            result = run_quantity_stage(
                workspace,
                MEASUREMENT_RUN_ID,
                MEASUREMENT_ARXIV_ID,
                config=frozen_contribution_config(),
                transport=transport,
                sleep=lambda _: None,
                run_dir=run_dir_for(workspace),
            )
            self.assertEqual(result["status"], "no_trusted_roster")
            self.assertEqual(transport.calls, [])


if __name__ == "__main__":
    unittest.main()
