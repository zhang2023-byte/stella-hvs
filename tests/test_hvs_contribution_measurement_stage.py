"""Contribution measurement stage orchestration tests (fake transports only)."""

from __future__ import annotations

import json
import tempfile
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
from stella.hvs_contribution_extraction.measurement_stage import (
    MEASUREMENTS_COMPLETE,
    MEASUREMENT_EXTRACTION_FAILED,
    run_measurement_stage,
)

ROOT = Path(__file__).resolve().parents[1]


def run_dir_for(workspace: Path) -> Path:
    return workspace / "runs" / "hvs-contribution-extraction" / MEASUREMENT_RUN_ID


class MeasurementStageTest(unittest.TestCase):
    def test_happy_path_delivers_grouped_multivalues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_measurement_workspace(tmp)
            transport = RecordingTransport(
                lambda kwargs: fake_response(MEASUREMENT_SUBMISSION, tool_name=tool_name_of(kwargs))
            )
            result = run_measurement_stage(
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
                {"submit_object_measurements"},
            )
            artifact = json.loads(
                (
                    run_dir_for(workspace)
                    / "papers"
                    / MEASUREMENT_ARXIV_ID
                    / "object_measurements"
                    / "obj-001.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(artifact["status"], MEASUREMENTS_COMPLETE)
            self.assertIsNone(artifact["failure"])
            groups = {group["field"]: group for group in artifact["measurements"]}
            self.assertEqual(len(groups["observed_phase_space.distance"]["values"]), 4)
            self.assertEqual(len(groups["bound_assessment.unbound_probability"]["values"]), 1)
            # Assigned contribution context in the user message.
            self.assertIn("obj-001", transport.calls[0]["messages"][1]["content"])
            # Measurement rules, not roster or V6 rules.
            system = transport.calls[0]["messages"][0]["content"]
            self.assertIn("[hvs.contrib.all_values_after_l1]", system)
            self.assertNotIn("[hvs.contrib.follow_up]", system)
            self.assertNotIn("hvs.field.multiple_estimates", system)

    def test_failure_preserves_l1_deliverability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_measurement_workspace(tmp)
            invalid = {
                "measurements": [
                    {
                        "field": "observed_phase_space.distance",
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
            result = run_measurement_stage(
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
                    / "object_measurements"
                    / "obj-001.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(artifact["status"], MEASUREMENT_EXTRACTION_FAILED)
            self.assertEqual(artifact["measurements"], [])
            self.assertIsNotNone(artifact["failure"])
            self.assertIn("obj-001", artifact["record_id"])

    def test_peer_audit_disabled_in_v1(self) -> None:
        config = frozen_contribution_config()
        self.assertFalse(config.measurement_peer_audit_enabled)

    def test_missing_run_dir_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_measurement_workspace(tmp)
            with self.assertRaisesRegex(ValueError, "run_dir is required"):
                run_measurement_stage(
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
            result = run_measurement_stage(
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
