"""Contribution gold form mechanics tests (TemporaryDirectory only)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stella.benchmark.hvs_contribution_gold_form import (
    PRE_ACTIVATION_BANNER,
    ContributionGoldFormError,
    build_empty_contribution_payload,
    draft_artifact_summary,
    load_draft,
    save_annotation,
    save_draft,
    validate_and_lint,
)
from tests.test_hvs_contribution_gold import fictional_annotation_payload

ROOT = Path(__file__).resolve().parents[1]


class ContributionGoldFormTest(unittest.TestCase):
    def test_banner_declares_disabled_formal_saving(self) -> None:
        for phrase in ("PRE-ACTIVATION", "disabled", "guideline", "campaign"):
            self.assertIn(phrase, PRE_ACTIVATION_BANNER)

    def test_formal_save_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ContributionGoldFormError) as ctx:
                save_annotation(fictional_annotation_payload(), Path(tmp))
            self.assertIn("PRE-ACTIVATION", str(ctx.exception))

    def test_draft_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gold_dir = Path(tmp)
            payload = build_empty_contribution_payload(
                arxiv_id="2601.00001", annotator="expert-a"
            )
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

    def test_validate_and_lint_reports_banner(self) -> None:
        result = validate_and_lint(fictional_annotation_payload())
        self.assertTrue(result["valid"])
        self.assertEqual(result["banner"], PRE_ACTIVATION_BANNER)
        self.assertIsInstance(result["lint_warnings"], list)

    def test_serve_script_gate(self) -> None:
        import importlib.util

        script = ROOT / "scripts/serve_hvs_contribution_gold_annotation.py"
        spec = importlib.util.spec_from_file_location("serve_contribution", script)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        # Formal save is rejected regardless of flags.
        status, body = module.handle_post(
            {"action": "save_annotation", "payload": {}},
            allow_drafts=True,
            gold_dir=None,
        )
        self.assertEqual(status, 403)
        self.assertIn("PRE-ACTIVATION", body["error"])
        # Drafts require explicit opt-in plus directory.
        status, body = module.handle_post(
            {"action": "save_draft", "payload": {"arxiv_id": "x", "annotator": "y"}},
            allow_drafts=False,
            gold_dir=None,
        )
        self.assertEqual(status, 403)
        page = module.render_form_page(ROOT)
        self.assertIn("PRE-ACTIVATION", page)
        self.assertIn("hvs_contribution_annotation", page)


if __name__ == "__main__":
    unittest.main()
