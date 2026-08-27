"""Local immutable contribution run orchestration tests (fake transports only)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.hvs_contribution_fixtures import (
    MEASUREMENT_ARXIV_ID,
    MEASUREMENT_ROSTER_SUBMISSION,
    MEASUREMENT_RUN_ID,
    MEASUREMENT_SUBMISSION,
    RecordingTransport,
    fake_response,
    frozen_contribution_config,
    make_measurement_workspace,
    tool_name_of,
)
from stella.lit.extraction.run import (
    freeze_contribution_method_config,
    run_local_contribution_extraction,
)
from stella.lit.extraction.run_policy import (
    assert_contribution_run_dir,
    contribution_run_dir,
    reserve_contribution_run_dir,
)
from stella.lit.extraction.schema_check import (
    validate_contribution_document_file,
)


def routing_transport() -> RecordingTransport:
    def handler(kwargs: dict):
        name = tool_name_of(kwargs)
        payload = (
            MEASUREMENT_ROSTER_SUBMISSION
            if name == "submit_contribution_roster"
            else MEASUREMENT_SUBMISSION
        )
        return fake_response(payload, tool_name=name)

    return RecordingTransport(handler)


class ContributionRunTest(unittest.TestCase):
    def test_end_to_end_run_writes_canonical_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_measurement_workspace(tmp)
            summary = run_local_contribution_extraction(
                workspace,
                [MEASUREMENT_ARXIV_ID],
                config=frozen_contribution_config(),
                transport=routing_transport(),
                run_id="crun-test-001",
                sleep=lambda _: None,
            )
            self.assertEqual(summary["status"], "complete")
            self.assertIn("not a benchmark result", summary["non_formal_note"])
            run_dir = contribution_run_dir(workspace, "crun-test-001")
            paper = summary["papers"][MEASUREMENT_ARXIV_ID]
            self.assertEqual(paper["status"], "complete")
            canonical = Path(paper["canonical_path"])
            record = validate_contribution_document_file(canonical)
            self.assertEqual(record.extraction.status, "complete")
            self.assertEqual(len(record.object_contributions), 1)
            contribution = record.object_contributions[0]
            self.assertEqual(contribution.quantity_extraction_status, "complete")
            self.assertIsNone(contribution.failure)
            self.assertEqual(
                len(contribution.quantities[0].values), 4
            )
            # Method config frozen with computed component hashes.
            config_artifact = json.loads(
                (run_dir / "method_config.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                config_artifact["schema"],
                {"name": "hvs_contribution_extraction.method_config", "version": 1},
            )
            profile_hash = config_artifact["components"]["rule_profile_sha256"][
                "hvs_contribution_v1"
            ]
            self.assertEqual(len(profile_hash), 64)
            self.assertEqual(
                config_artifact["method_fingerprint"], summary["method_fingerprint"]
            )
            # run_summary persisted.
            persisted_summary = json.loads(
                (run_dir / "run_summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(persisted_summary["run_id"], "crun-test-001")
            # Nothing under any benchmark campaign.
            self.assertFalse((workspace / "benchmark").exists())

    def test_run_ids_are_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_measurement_workspace(tmp)
            run_local_contribution_extraction(
                workspace,
                [MEASUREMENT_ARXIV_ID],
                config=frozen_contribution_config(),
                transport=routing_transport(),
                run_id="crun-test-immutable",
                sleep=lambda _: None,
            )
            with self.assertRaises(FileExistsError):
                run_local_contribution_extraction(
                    workspace,
                    [MEASUREMENT_ARXIV_ID],
                    config=frozen_contribution_config(),
                    transport=routing_transport(),
                    run_id="crun-test-immutable",
                    sleep=lambda _: None,
                )

    def test_reserve_fails_when_directory_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            first = reserve_contribution_run_dir(workspace, "crun-x")
            self.assertTrue(first.is_dir())
            with self.assertRaises(FileExistsError):
                reserve_contribution_run_dir(workspace, "crun-x")

    def test_run_id_cannot_escape_fixed_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            for run_id in ("../escape", "../../outside", "a/b", ""):
                with self.subTest(run_id=run_id):
                    with self.assertRaises(ValueError):
                        reserve_contribution_run_dir(workspace, run_id)
            self.assertFalse((workspace / "outside").exists())
            with self.assertRaisesRegex(ValueError, "contribution run_dir must be"):
                assert_contribution_run_dir(
                    workspace,
                    "crun-safe",
                    workspace
                    / "benchmark"
                    / "campaigns"
                    / "hvs-extraction-v6"
                    / "runs"
                    / "crun-safe",
                )

    def test_frozen_components_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_measurement_workspace(tmp)
            frozen_a = freeze_contribution_method_config(
                workspace, frozen_contribution_config()
            )
            frozen_b = freeze_contribution_method_config(
                workspace, frozen_contribution_config()
            )
            self.assertEqual(
                frozen_a.components.model_dump(), frozen_b.components.model_dump()
            )
            self.assertNotIn(
                "pending",
                json.dumps(frozen_a.components.model_dump()),
            )

    def test_user_prompt_templates_change_the_method_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_measurement_workspace(tmp)
            original = freeze_contribution_method_config(
                workspace, frozen_contribution_config()
            )
            with mock.patch(
                "stella.lit.extraction.run.EXTRACTOR_USER_TEMPLATE",
                "changed roster user template",
            ):
                changed = freeze_contribution_method_config(
                    workspace, frozen_contribution_config()
                )
            self.assertNotEqual(
                original.method_fingerprint(), changed.method_fingerprint()
            )

    def test_frozen_schema_hash_covers_the_ecsv_evidence_branch(self) -> None:
        """Empty path lists would freeze the schema without its ECSV branch."""

        import hashlib

        from stella.lit.extraction.quantity_schema import (
            build_quantity_submission_schema,
        )

        def schema_hash(schema: dict) -> str:
            return hashlib.sha256(
                json.dumps(schema, ensure_ascii=False, sort_keys=True).encode()
            ).hexdigest()

        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_measurement_workspace(tmp)
            frozen = freeze_contribution_method_config(
                workspace, frozen_contribution_config()
            )
        frozen_hash = frozen.components.submission_schema_sha256[
            "submit_object_quantities"
        ]
        self.assertEqual(
            frozen_hash,
            schema_hash(
                build_quantity_submission_schema(
                    ["main.tex"], ["catalog_tables/table.ecsv"]
                )
            ),
        )
        self.assertNotEqual(
            frozen_hash,
            schema_hash(build_quantity_submission_schema([], [])),
        )

    def test_quantity_failure_still_delivers_l1_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_measurement_workspace(tmp)
            bad_measurement = {
                "quantities": [
                    {
                        "quantity": "observed_phase_space.distance",
                        "values": [
                            {
                                **MEASUREMENT_SUBMISSION["quantities"][0]["values"][0],
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

            def handler(kwargs: dict):
                name = tool_name_of(kwargs)
                payload = (
                    MEASUREMENT_ROSTER_SUBMISSION
                    if name == "submit_contribution_roster"
                    else bad_measurement
                )
                return fake_response(payload, tool_name=name)

            summary = run_local_contribution_extraction(
                workspace,
                [MEASUREMENT_ARXIV_ID],
                config=frozen_contribution_config(),
                transport=RecordingTransport(handler),
                run_id="crun-test-failure",
                sleep=lambda _: None,
            )
            self.assertEqual(summary["status"], "partial")
            record = validate_contribution_document_file(
                Path(summary["papers"][MEASUREMENT_ARXIV_ID]["canonical_path"])
            )
            contribution = record.object_contributions[0]
            self.assertEqual(
                contribution.quantity_extraction_status, "failed"
            )
            self.assertIsNotNone(contribution.failure)
            self.assertEqual(contribution.contribution_type, "candidates_found")


if __name__ == "__main__":
    unittest.main()
