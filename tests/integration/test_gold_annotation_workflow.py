"""One-action offline tests for the gold_annotation workflow.

Each invocation performs exactly one human action against a temporary
private gold root: queue lists work, open prepares the PDF-only form
draft, validate checks the draft without saving final gold, save applies
the expert-approval gate and writes one JSON per paper and expert, and
selection publishes the value-free manifest. No unattended invocation
chains open->validate->save, no YAML twin is written, and no real
private-gold store or network is touched.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from stella import workflow_runtime
from stella.benchmark.gold_form_controller import GoldFormController
from stella.workflows import Authorities, GoldAnnotationRequest
from tests.integration.netguard import guard

ROOT = Path(__file__).resolve().parents[2]
PAPER = "2601.08888"
EXPERT = "expert-a"


def _seed_pdf(root: Path) -> None:
    paper_dir = root / "literature" / PAPER
    paper_dir.mkdir(parents=True)
    (paper_dir / "arxiv.pdf").write_bytes(b"%PDF-1.4 fake")


class GoldAnnotationWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        guard(self)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.gold_dir = self.root / "private-gold"
        self.work_dir = self.root / "gold-work"
        self.gold_dir.mkdir()
        self.work_dir.mkdir()
        _seed_pdf(self.root)
        self._env = {
            "STELLA_GOLD_DIR": str(self.gold_dir),
            "STELLA_GOLD_WORK_DIR": str(self.work_dir),
        }
        self._old = {key: os.environ.get(key) for key in self._env}

    def tearDown(self) -> None:
        for key, value in self._old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    def _run(self, action: str, **payload_extra: object) -> dict:
        os.environ.update(self._env)
        request = GoldAnnotationRequest(
            expert=EXPERT,
            papers=[PAPER],
            action=action,
            authorities=Authorities(execute=True, gold_private=True),
            **payload_extra,  # type: ignore[arg-type]
        )
        return workflow_runtime.run_workflow(
            root=self.root,
            workflow_id="gold_annotation",
            request=request,
            env_extra=self._env,
        )

    def test_queue_action_only_lists_and_never_touches_annotation(self) -> None:
        summary = self._run("queue")
        self.assertEqual(summary["status"], "complete")
        run_dir = Path(summary["run_dir"])
        events = [
            json.loads(line)
            for line in (run_dir / "events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        operations = sorted(
            {
                item["operation"]
                for item in events
                if item.get("event") == "operation_started"
            }
        )
        self.assertEqual(operations, ["gold.list_queue"])
        # A queue action never creates an annotation attempt.
        self.assertEqual([], list(run_dir.rglob("papers/*/attempts")))
        self.assertEqual([], list(self.gold_dir.rglob("annotation_*.json")))

    def test_open_action_prepares_the_pdf_only_draft(self) -> None:
        summary = self._run("open")
        self.assertEqual(summary["status"], "complete")
        draft = self.work_dir / PAPER / f"draft_{EXPERT}.json"
        self.assertTrue(draft.is_file())
        document = json.loads(draft.read_text(encoding="utf-8"))
        self.assertEqual(document["arxiv_id"], PAPER)
        # An open must never write final gold.
        self.assertEqual(
            [], list(self.gold_dir.rglob("annotation_*.json"))
        )

    def test_validate_action_checks_without_saving(self) -> None:
        self._run("open")
        summary = self._run("validate")
        # The empty draft fails its gate: blocked, but nothing is saved.
        self.assertNotEqual(summary["status"], "complete")
        self.assertEqual(
            [], list(self.gold_dir.rglob("annotation_*.json"))
        )

    def test_save_action_requires_expert_approval(self) -> None:
        self._run("open")
        blocked = self._run("save")
        self.assertNotEqual(blocked["status"], "complete")
        self.assertEqual(
            [], list(self.gold_dir.rglob("annotation_*.json"))
        )

    def test_save_action_can_carry_explicit_expert_approval(self) -> None:
        request = GoldAnnotationRequest(
            expert=EXPERT,
            papers=[PAPER],
            action="save",
            expert_approved=True,
            authorities=Authorities(execute=True, gold_private=True),
        )
        self.assertTrue(request.expert_approved)

    def test_selection_action_publishes_value_free_manifest(self) -> None:
        # Without an approved annotation the selection fails closed.
        missing = self._run("selection")
        self.assertNotEqual(missing["status"], "complete")
        self.assertFalse(
            (self.root / "benchmark" / "gold_selection.json").is_file()
        )


class GoldFormControllerTest(unittest.TestCase):
    """The controller core is GUI-free and enforces the expert gates."""

    def setUp(self) -> None:
        guard(self)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.gold_dir = self.root / "private-gold"
        self.work_dir = self.root / "gold-work"
        self.gold_dir.mkdir()
        self.work_dir.mkdir()
        _seed_pdf(self.root)
        self.controller = GoldFormController(
            root=self.root,
            gold_dir=self.gold_dir,
            work_dir=self.work_dir,
            expert=EXPERT,
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_get_previews_draft_and_pdf(self) -> None:
        status, payload = self.controller.handle_request(
            "GET", f"/papers/{PAPER}"
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["pdf"].endswith("arxiv.pdf"))
        self.assertEqual(payload["draft"]["arxiv_id"], PAPER)

    def test_save_route_enforces_gate_and_approval(self) -> None:
        self.controller.handle_request("GET", f"/papers/{PAPER}")
        status, payload = self.controller.handle_request(
            "POST", f"/papers/{PAPER}/save", {"expert_approved": True}
        )
        # The empty draft fails validation, so the gate blocks saving.
        self.assertEqual(status, 422)
        self.assertIn("gate", payload)
        self.assertEqual(
            [], list(self.gold_dir.rglob("annotation_*.json"))
        )

    def test_validate_route_reports_gate_without_side_effects(self) -> None:
        self.controller.handle_request("GET", f"/papers/{PAPER}")
        status, payload = self.controller.handle_request(
            "POST", f"/papers/{PAPER}/validate"
        )
        self.assertEqual(status, 200)
        self.assertIn("ok", payload)
        self.assertEqual(
            [], list(self.gold_dir.rglob("annotation_*.json"))
        )

    def test_unknown_route_is_a_404(self) -> None:
        status, _ = self.controller.handle_request("GET", "/nope")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
