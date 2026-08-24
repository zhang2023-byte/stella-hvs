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
    annotation_paths,
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
        result = validate_and_lint(fictional_annotation_payload())
        self.assertTrue(result["valid"])
        self.assertEqual(result["notice"], CONTRIBUTION_GOLD_NOTICE)
        self.assertIsInstance(result["lint_warnings"], list)

    def test_approved_save_writes_twins_and_deletes_known_work_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gold_dir = root / "gold"
            work_dir = root / "work"
            payload = fictional_annotation_payload()
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

            yaml_path, json_path = annotation_paths(
                gold_dir, payload["arxiv_id"], payload["annotator"]
            )
            self.assertEqual(Path(result["yaml_path"]), yaml_path)
            self.assertTrue(yaml_path.is_file())
            self.assertTrue(json_path.is_file())
            self.assertFalse(paper_work.exists())
            yaml_payload = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            json_payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertNotIn("canary", yaml_payload)
            self.assertIn("canary", json_payload)
            self.assertEqual(
                json_payload["annotation_process"]["expert_review_scope"],
                "paper_level",
            )

    def test_invalid_path_components_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ContributionGoldFormError):
                annotation_paths(root, "../2601.00001", "expert-a")
            with self.assertRaises(ContributionGoldFormError):
                annotation_paths(root, "2601.00001", "../expert-a")


if __name__ == "__main__":
    unittest.main()
