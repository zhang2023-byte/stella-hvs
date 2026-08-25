"""JSON-only storage contract for the contribution Gold form.

One expert/paper annotation has exactly one canonical JSON path. Saving
writes no YAML twin, validation consumes JSON alone, annotators cannot
overwrite one another, and a final save requires explicit expert
approval of a draft that passed its gate.
"""

from __future__ import annotations

import json
import threading
import tempfile
import unittest
import urllib.request
from pathlib import Path

from stella.benchmark.hvs_contribution_gold_form import (
    annotation_json_path,
    build_empty_contribution_payload,
    load_draft,
    resolve_paper_pdf,
    save_expert_annotation,
    save_draft,
    validate_save_gate,
)
from stella.benchmark.gold_form_controller import (
    GoldFormController,
    create_gold_form_server,
)
from tests.benchmark.test_hvs_contribution_gold import fictional_annotation_payload


class JsonOnlyStorageTest(unittest.TestCase):
    def test_pdf_resolver_prefers_canonical_and_supports_legacy_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paper_dir = root / "literature" / "2601.00001"
            assets = paper_dir / "assets"
            assets.mkdir(parents=True)
            fallback = assets / "paper.pdf"
            fallback.write_bytes(b"%PDF-1.4 fallback")
            self.assertEqual(
                resolve_paper_pdf(root, "2601.00001"), fallback
            )

            canonical = paper_dir / "arxiv.pdf"
            canonical.write_bytes(b"%PDF-1.4 canonical")
            self.assertEqual(
                resolve_paper_pdf(root, "2601.00001"), canonical
            )

    def test_annotation_has_exactly_one_canonical_json_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gold_dir = Path(tmp)
            path = annotation_json_path(gold_dir, "2601.00001", "expert-a")
            self.assertEqual(path.suffix, ".json")
            self.assertEqual(
                path.relative_to(gold_dir.resolve()).as_posix(),
                "2601.00001/annotation_expert-a.json",
            )

    def test_save_writes_json_and_no_yaml_twin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gold_dir = Path(tmp)
            result = save_expert_annotation(
                fictional_annotation_payload(),
                gold_dir,
                expert_approved=True,
            )
            json_path = Path(result["json_path"])
            self.assertTrue(json_path.is_file())
            json.loads(json_path.read_text(encoding="utf-8"))
            paper_dir = json_path.parent
            yaml_twins = list(paper_dir.glob("annotation_*.yaml"))
            self.assertEqual(
                [], yaml_twins, "save must not write a YAML twin"
            )
            self.assertEqual(
                sorted(path.name for path in paper_dir.iterdir()),
                ["annotation_expert-a.json"],
            )

    def test_annotators_cannot_overwrite_one_another(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gold_dir = Path(tmp)
            first = fictional_annotation_payload()
            save_expert_annotation(first, gold_dir, expert_approved=True)
            second = fictional_annotation_payload()
            second["annotator"] = "expert-b"
            save_expert_annotation(second, gold_dir, expert_approved=True)
            names = sorted(
                path.name
                for path in (gold_dir / "2601.00001").iterdir()
            )
            self.assertEqual(
                names,
                ["annotation_expert-a.json", "annotation_expert-b.json"],
            )

    def test_same_expert_cannot_overwrite_final_annotation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gold_dir = Path(tmp)
            payload = fictional_annotation_payload()
            save_expert_annotation(payload, gold_dir, expert_approved=True)
            with self.assertRaisesRegex(Exception, "already exists"):
                save_expert_annotation(payload, gold_dir, expert_approved=True)

    def test_unapproved_or_invalid_draft_never_becomes_final(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gold_dir = Path(tmp)
            work_dir = gold_dir / "work"
            payload = build_empty_contribution_payload(
                arxiv_id="2601.00001", annotator="expert-a"
            )
            save_draft(payload, work_dir)
            # An empty draft fails validation, so the gate blocks the save.
            draft = load_draft(work_dir, "2601.00001", "expert-a")
            self.assertNotEqual(draft, fictional_annotation_payload())
            with self.assertRaises(Exception):
                save_expert_annotation(
                    draft,
                    gold_dir,
                    work_dir=work_dir,
                    expected_arxiv_id="2601.00001",
                    expected_annotator="expert-a",
                    expert_approved=True,
                )
            self.assertFalse(
                annotation_json_path(
                    gold_dir, "2601.00001", "expert-a"
                ).is_file()
            )

    def test_final_save_requires_explicit_expert_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(Exception) as ctx:
                save_expert_annotation(
                    fictional_annotation_payload(), Path(tmp)
                )
            self.assertIn("expert approval", str(ctx.exception))

    def test_completed_save_gate_revalidates_schema_and_rejects_yaml_twin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gold_dir = Path(tmp)
            payload = fictional_annotation_payload()
            saved = save_expert_annotation(
                payload, gold_dir, expert_approved=True
            )
            result = {
                "status": "complete",
                "paper_id": payload["arxiv_id"],
                "detail": {"save": {"annotation_path": saved["json_path"]}},
            }
            request = {"expert": payload["annotator"]}
            self.assertEqual(
                validate_save_gate(request, result, root=gold_dir), []
            )

            yaml_path = Path(saved["json_path"]).with_suffix(".yaml")
            yaml_path.write_text("legacy: twin", encoding="utf-8")
            errors = validate_save_gate(request, result, root=gold_dir)
            self.assertTrue(any("YAML twin" in error for error in errors))


class LocalGoldFormHttpTest(unittest.TestCase):
    def test_loopback_server_serves_a_usable_html_form_and_json_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paper_dir = root / "literature" / "2601.00001"
            paper_dir.mkdir(parents=True)
            (paper_dir / "arxiv.pdf").write_bytes(b"%PDF-1.4 fake")
            gold_dir = root / "private-gold"
            work_dir = root / "work"
            gold_dir.mkdir()
            work_dir.mkdir()
            controller = GoldFormController(
                root=root,
                gold_dir=gold_dir,
                work_dir=work_dir,
                expert="expert-a",
            )
            server = create_gold_form_server(
                controller, paper_id="2601.00001", host="127.0.0.1", port=0
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                with urllib.request.urlopen(
                    f"{base}/papers/2601.00001", timeout=2
                ) as response:
                    html = response.read().decode("utf-8")
                self.assertIn("Stella contribution Gold", html)
                self.assertIn("Validate draft", html)
                with urllib.request.urlopen(
                    f"{base}/api/papers/2601.00001", timeout=2
                ) as response:
                    document = json.loads(response.read())
                self.assertEqual(document["draft"]["arxiv_id"], "2601.00001")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
