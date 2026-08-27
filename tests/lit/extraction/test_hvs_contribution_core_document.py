"""Canonical contribution document assembly tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.hvs_contribution_fixtures import (
    ARXIV_ID,
    RUN_ID,
    make_workspace,
)
from stella.lit.extraction.core_document import (
    build_contribution_document,
    write_contribution_document,
)
from stella.lit.extraction.finalize import (
    assemble_contribution_paper_result,
)
from stella.lit.extraction.schema_check import (
    validate_contribution_document,
)


def paper_result_for(workspace: Path) -> dict:
    return assemble_contribution_paper_result(
        workspace,
        RUN_ID,
        ARXIV_ID,
        run_dir=workspace / "runs" / "hvs-contribution-extraction" / RUN_ID,
    )


class ContributionCoreDocumentTest(unittest.TestCase):
    def test_document_from_partial_paper_result_validates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            result = paper_result_for(workspace)
            document = build_contribution_document(
                result,
                method_fingerprint="fp",
                component_hashes={"rule_profile_sha256": {"hvs_contribution_v1": "a" * 64}},
                paper_context_sha256="b" * 64,
            )
            record = validate_contribution_document(document)
            self.assertEqual(record.extraction.status, "partial")
            self.assertEqual(record.extraction.roster_status, "contributions_found")
            self.assertEqual(len(record.object_contributions), 10)
            # A missing quantity artifact yields explicit failure, empty
            # quantities, and L1 identity preserved.
            first = record.object_contributions[0]
            self.assertEqual(first.quantity_extraction_status, "failed")
            self.assertEqual(first.quantities, [])
            self.assertIsNotNone(first.failure)
            self.assertEqual(first.contribution_type, "candidates_found")
            self.assertEqual(first.identifiers[0].value, "J1234")
            self.assertEqual(document["inputs"]["paper_context_sha256"], "b" * 64)
            self.assertEqual(document["production"]["producer"], "hvs_contribution_extraction")
            self.assertEqual(len(document["reviewed_exclusions"]), 2)
            range_identifier = next(
                item.identifiers[0]
                for item in record.object_contributions
                if item.identifiers[0].value == "J12"
            )
            self.assertEqual(
                set(range_identifier.model_dump()), {"value", "evidence"}
            )

    def test_write_document_beside_paper_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            result = paper_result_for(workspace)
            paper_dir = workspace / "runs" / "hvs-contribution-extraction" / RUN_ID / "papers" / ARXIV_ID
            document = write_contribution_document(
                paper_dir / "paper_result.json",
                method_fingerprint="fp",
            )
            persisted = json.loads(
                (paper_dir / "literature_hvs_contributions.json").read_text(encoding="utf-8")
            )
            self.assertEqual(persisted, document)
            self.assertEqual(
                persisted["schema"], {"name": "literature_hvs_contributions", "version": 1}
            )

    def test_failed_roster_document_has_no_contributions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = make_workspace(tmp)
            paper_dir = workspace / "runs" / "hvs-contribution-extraction" / RUN_ID / "papers" / ARXIV_ID
            roster_path = paper_dir / "contribution_roster_final.json"
            roster = json.loads(roster_path.read_text(encoding="utf-8"))
            roster["status"] = "roster_failed"
            roster["failure"] = {"code": "extractor_terminal_failure", "detail": "x"}
            roster_path.write_text(json.dumps(roster), encoding="utf-8")
            result = paper_result_for(workspace)
            document = build_contribution_document(result)
            record = validate_contribution_document(document)
            self.assertEqual(record.extraction.status, "failed")
            self.assertIsNone(record.extraction.roster_status)
            self.assertEqual(record.object_contributions, [])


if __name__ == "__main__":
    unittest.main()
