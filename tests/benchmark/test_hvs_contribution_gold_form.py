"""Contribution gold form mechanics tests (TemporaryDirectory only)."""

from __future__ import annotations

import tempfile
import unittest
import json
from datetime import date
from pathlib import Path

import yaml

from stella.benchmark.hvs_contribution_gold_form import (
    CONTRIBUTION_GOLD_NOTICE,
    ContributionGoldFormError,
    annotation_json_path,
    build_empty_contribution_payload,
    draft_artifact_summary,
    load_draft,
    save_expert_annotation,
    save_draft,
    validate_and_lint,
)
from tests.benchmark.test_hvs_contribution_gold import fictional_annotation_payload

ROOT = Path(__file__).resolve().parents[2]


class ContributionGoldFormTest(unittest.TestCase):
    def test_notice_declares_ai_assisted_expert_approved_boundary(self) -> None:
        for phrase in ("AI-assisted", "paper-level", "PDF", "forbidden"):
            self.assertIn(phrase, CONTRIBUTION_GOLD_NOTICE)

    def test_final_save_requires_explicit_expert_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ContributionGoldFormError) as ctx:
                save_expert_annotation(fictional_annotation_payload(), Path(tmp))
            self.assertIn("expert approval", str(ctx.exception))

    def test_draft_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gold_dir = Path(tmp)
            payload = build_empty_contribution_payload(
                arxiv_id="2601.00001",
                annotator="expert-a",
                guideline_version="abc1234",
            )
            self.assertEqual(payload["annotated_at"], date.today().isoformat())
            self.assertEqual(payload["guideline_version"], "abc1234")
            result = save_draft(payload, gold_dir)
            self.assertEqual(result["status"], "draft_saved")
            loaded = load_draft(gold_dir, "2601.00001", "expert-a")
            self.assertEqual(loaded, payload)
            summary = draft_artifact_summary(gold_dir, "2601.00001", "expert-a")
            self.assertTrue(summary["exists"])
            self.assertFalse(summary["is_reservation_marker"])
            self.assertFalse(summary["formal_input"])

    def test_draft_requires_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ContributionGoldFormError):
                save_draft({"arxiv_id": "", "annotator": ""}, Path(tmp))

    def test_validate_and_lint_reports_notice(self) -> None:
        result = validate_and_lint(fictional_annotation_payload(version=2))
        self.assertTrue(result["valid"])
        self.assertEqual(result["notice"], CONTRIBUTION_GOLD_NOTICE)
        self.assertIsInstance(result["lint_warnings"], list)

    def test_normal_write_path_rejects_readable_v1_history(self) -> None:
        with self.assertRaises(ValueError):
            validate_and_lint(fictional_annotation_payload(version=1))

    def test_approved_save_writes_one_json_and_deletes_known_work_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gold_dir = root / "gold"
            work_dir = root / "work"
            payload = fictional_annotation_payload(version=2)
            paper_work = work_dir / payload["arxiv_id"]
            paper_work.mkdir(parents=True)
            for name in (
                "preannotation.json",
                "conflict_report.json",
                f"draft_{payload['annotator']}.json",
            ):
                (paper_work / name).write_text("{}", encoding="utf-8")

            result = save_expert_annotation(
                payload,
                gold_dir,
                work_dir=work_dir,
                expected_arxiv_id=payload["arxiv_id"],
                expected_annotator=payload["annotator"],
                expert_approved=True,
            )

            json_path = annotation_json_path(
                gold_dir, payload["arxiv_id"], payload["annotator"]
            )
            self.assertEqual(Path(result["json_path"]), json_path)
            self.assertTrue(json_path.is_file())
            self.assertFalse(paper_work.exists())
            # One canonical JSON per paper and expert; no YAML twin.
            self.assertEqual(
                [], list(json_path.parent.glob("annotation_*.yaml"))
            )
            json_payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertIn("canary", json_payload)
            self.assertEqual(
                json_payload["annotation_process"]["expert_review_scope"],
                "paper_level",
            )

    def test_invalid_path_components_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ContributionGoldFormError):
                annotation_json_path(root, "../2601.00001", "expert-a")
            with self.assertRaises(ContributionGoldFormError):
                annotation_json_path(root, "2601.00001", "../expert-a")


if __name__ == "__main__":
    unittest.main()
