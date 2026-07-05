from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

import yaml

from stella.benchmark.gold import GoldAnnotation, upgrade_annotation
from stella.benchmark.gold_form import (
    GoldFormConfig,
    GoldFormError,
    bootstrap_state,
    create_server,
    load_draft,
    output_annotation_paths,
    output_draft_path,
    render_page,
    save_annotation,
    save_draft,
    validate_payload,
)


ROOT = Path(__file__).resolve().parents[1]


def write_manifest(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "papers": [
                    {
                        "arxiv_id": "1902.05061",
                        "legacy_status": "candidates_found",
                    },
                    {
                        "arxiv_id": "1804.09677",
                        "legacy_status": "candidates_found",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def valid_payload(unit: str = "km/s") -> dict:
    return {
        "schema_version": "stella.benchmark_gold_annotation.v0.1",
        "arxiv_id": "1902.05061",
        "annotator": "will",
        "annotated_at": "2026-06-25",
        "guideline_version": "abcdef0",
        "evidence_basis": "pdf",
        "status": "candidates_found",
        "candidates": [
            {
                "paper_candidate_id": "J1603-6613",
                "gaia_source_id": "",
                "aliases": [],
                "origin_type": "introduced_by_this_paper",
                "quantities": [
                    {
                        "field": "observed_phase_space.radial_velocity",
                        "value": "612.3",
                        "unit": unit,
                        "evidence": [{"location": "Table 1, row J1603-6613"}],
                    }
                ],
                "evidence": [
                    {
                        "location": "Sec 4.1",
                        "quote": "candidate high-velocity star",
                    }
                ],
                "notes": "",
            }
        ],
        "notes": "",
    }


class GoldFormBootstrapTest(unittest.TestCase):
    def test_bootstrap_payload_and_manifest_papers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.json"
            write_manifest(manifest)
            gold_dir = Path(tmp) / "gold"
            paper_gold = gold_dir / "1902.05061"
            paper_gold.mkdir(parents=True)
            (paper_gold / "annotation_will.yaml").write_text("placeholder\n", encoding="utf-8")
            save_draft(
                {"arxiv_id": "1902.05061", "annotator": "will", "status": "incomplete"},
                gold_dir,
            )
            state = bootstrap_state(
                GoldFormConfig(
                    workspace=ROOT,
                    manifest_path=manifest,
                    gold_dir=gold_dir,
                    arxiv_id="1902.05061",
                    annotator="will",
                )
            )

        payload = state["payload"]
        self.assertEqual(payload["schema_version"], "stella.benchmark_gold_annotation.v0.1")
        self.assertEqual(payload["arxiv_id"], "1902.05061")
        self.assertEqual(payload["annotator"], "will")
        self.assertEqual(payload["evidence_basis"], "pdf")
        self.assertNotIn("manifest_role", state["selected"])
        self.assertNotIn("manifest_overlap", state["selected"])
        self.assertTrue(state["selected"]["gold_exists"])
        self.assertEqual(state["selected"]["gold_files"], ["annotation_will.yaml"])
        self.assertTrue(state["selected"]["draft_exists"])
        self.assertTrue(state["selected"]["draft_path"].endswith("draft_will.json"))
        self.assertTrue(state["selected"]["pdf_path"].endswith("literature/1902.05061/arxiv.pdf"))
        self.assertEqual(
            [paper["arxiv_id"] for paper in state["papers"]],
            ["1902.05061", "1804.09677"],
        )
        self.assertTrue(state["papers"][0]["gold_exists"])
        self.assertTrue(state["papers"][0]["draft_exists"])
        self.assertNotIn("bound_claims", state["options"])
        fields = [
            field
            for group in state["options"]["quantity_field_groups"].values()
            for field in group
        ]
        self.assertNotIn("derived_kinematics.total_velocity", fields)
        self.assertIn("derived_kinematics.galactic_rest_frame_velocity", fields)

    def test_any_manifest_paper_can_be_preselected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.json"
            write_manifest(manifest)
            state = bootstrap_state(
                GoldFormConfig(
                    workspace=ROOT,
                    manifest_path=manifest,
                    gold_dir=Path(tmp) / "gold",
                    arxiv_id="1804.09677",
                    annotator="will",
                )
            )

        self.assertEqual(state["payload"]["arxiv_id"], "1804.09677")
        self.assertEqual(state["selected"]["legacy_status"], "candidates_found")


class GoldFormValidationTest(unittest.TestCase):
    def test_rendered_page_has_candidate_annotation_regions(self) -> None:
        page = render_page({"payload": valid_payload()})

        self.assertIn('class="annotation-shell"', page)
        self.assertIn('class="candidate-rail"', page)
        self.assertIn('id="candidate-nav"', page)
        self.assertIn('id="candidate-workspace"', page)
        self.assertIn('id="annotation-summary"', page)
        self.assertIn("function renderCandidateNav()", page)
        self.assertIn("function renderQuantityGroup", page)

    def test_validate_payload_returns_lint_warning(self) -> None:
        result = validate_payload(valid_payload(unit="m/s"))

        self.assertTrue(result["valid"])
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("unusual", result["warnings"][0])

    def test_validate_payload_reports_error_path(self) -> None:
        payload = valid_payload()
        payload["candidates"][0]["quantities"][0]["value"] = "~612"

        result = validate_payload(payload)

        self.assertFalse(result["valid"])
        self.assertTrue(result["errors"])
        self.assertIn("candidates", result["errors"][0]["path"])
        self.assertIn("plain number", result["errors"][0]["message"])

    def test_no_candidates_requires_notes_in_form(self) -> None:
        payload = valid_payload()
        payload["status"] = "no_candidates"
        payload["candidates"] = []
        payload["notes"] = ""

        result = validate_payload(payload)

        self.assertFalse(result["valid"])
        self.assertEqual(result["errors"][0]["path"], ["notes"])


class GoldFormSaveTest(unittest.TestCase):
    def test_save_writes_yaml_and_json_from_same_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gold_dir = Path(tmp) / "gold"
            saved = save_annotation(
                valid_payload(),
                gold_dir,
                expected_arxiv_id="1902.05061",
                expected_annotator="will",
            )
            yaml_path = Path(saved["yaml_path"])
            json_path = Path(saved["json_path"])
            yaml_payload = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            json_payload = json.loads(json_path.read_text(encoding="utf-8"))

        # The YAML stays the expert-shaped compact document; the JSON twin
        # additionally carries the deterministic leak-audit canary.
        expected_json = upgrade_annotation(valid_payload())
        expected_yaml = {
            key: value for key, value in expected_json.items() if key != "canary"
        }
        self.assertEqual(yaml_payload, expected_yaml)
        self.assertEqual(json_payload, expected_json)
        self.assertTrue(
            json_payload["canary"].startswith("stella-gold-canary-"),
            json_payload["canary"],
        )

    def test_invalid_path_components_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(GoldFormError):
                output_annotation_paths(Path(tmp) / "gold", "../1902.05061", "will")
            with self.assertRaises(GoldFormError):
                output_annotation_paths(Path(tmp) / "gold", "1902.05061", "../will")
            with self.assertRaises(GoldFormError):
                output_draft_path(Path(tmp) / "gold", "1902.05061", "../will")

    def test_selected_arxiv_mismatch_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gold_dir = Path(tmp) / "gold"
            with self.assertRaises(GoldFormError):
                save_annotation(
                    valid_payload(),
                    gold_dir,
                    expected_arxiv_id="1902.99999",
                    expected_annotator="will",
                )
            self.assertFalse(gold_dir.exists())

    def test_invalid_payload_does_not_write(self) -> None:
        payload = valid_payload()
        payload["candidates"] = []
        with tempfile.TemporaryDirectory() as tmp:
            gold_dir = Path(tmp) / "gold"
            with self.assertRaises(GoldFormError):
                save_annotation(payload, gold_dir)
            self.assertFalse(gold_dir.exists())


class GoldFormDraftTest(unittest.TestCase):
    def test_save_draft_writes_unvalidated_payload(self) -> None:
        payload = valid_payload()
        payload["candidates"] = []
        with tempfile.TemporaryDirectory() as tmp:
            saved = save_draft(payload, Path(tmp) / "gold")
            draft_path = Path(saved["draft_path"])
            document = json.loads(draft_path.read_text(encoding="utf-8"))

        self.assertEqual(document["draft_schema"], "stella.benchmark_gold_form_draft.v0.1")
        self.assertEqual(document["payload"], payload)

    def test_load_draft_returns_payload(self) -> None:
        payload = valid_payload()
        payload["notes"] = "halfway through review"
        with tempfile.TemporaryDirectory() as tmp:
            gold_dir = Path(tmp) / "gold"
            save_draft(payload, gold_dir)
            loaded = load_draft(gold_dir, "1902.05061", "will")

        self.assertTrue(loaded["exists"])
        self.assertEqual(loaded["payload"], payload)


class GoldFormHttpTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.manifest = self.root / "manifest.json"
        write_manifest(self.manifest)
        self.server = create_server(
            "127.0.0.1",
            0,
            GoldFormConfig(
                workspace=ROOT,
                manifest_path=self.manifest,
                gold_dir=self.root / "gold",
                arxiv_id="1902.05061",
                annotator="will",
            ),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.tmp.cleanup()

    def request_json(self, method: str, path: str, payload: dict | None = None) -> dict:
        conn = http.client.HTTPConnection(
            self.server.server_address[0],
            self.server.server_address[1],
            timeout=5,
        )
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        data = json.loads(response.read().decode("utf-8"))
        conn.close()
        return data

    def test_bootstrap_endpoint(self) -> None:
        data = self.request_json("GET", "/api/bootstrap")

        self.assertEqual(data["payload"]["arxiv_id"], "1902.05061")
        self.assertNotIn("manifest_role", data["selected"])

    def test_validate_endpoint(self) -> None:
        data = self.request_json(
            "POST",
            "/api/validate",
            {"payload": valid_payload(unit="m/s")},
        )

        self.assertTrue(data["valid"])
        self.assertEqual(len(data["warnings"]), 1)

    def test_save_endpoint(self) -> None:
        data = self.request_json(
            "POST",
            "/api/save",
            {"payload": valid_payload()},
        )

        self.assertTrue(data["valid"])
        self.assertTrue(Path(data["yaml_path"]).is_file())
        self.assertTrue(Path(data["json_path"]).is_file())

    def test_save_draft_endpoint_does_not_validate_annotation_schema(self) -> None:
        payload = valid_payload()
        payload["candidates"] = []
        data = self.request_json(
            "POST",
            "/api/save-draft",
            {"payload": payload},
        )

        self.assertTrue(data["valid"])
        self.assertIn("without schema validation", data["message"])
        self.assertTrue(Path(data["draft_path"]).is_file())

    def test_load_draft_endpoint(self) -> None:
        payload = valid_payload()
        payload["notes"] = "saved midway"
        self.request_json("POST", "/api/save-draft", {"payload": payload})

        data = self.request_json(
            "POST",
            "/api/load-draft",
            {"payload": {"arxiv_id": "1902.05061", "annotator": "will"}},
        )

        self.assertTrue(data["valid"])
        self.assertTrue(data["exists"])
        self.assertEqual(data["payload"], payload)

    def test_save_endpoint_accepts_any_manifest_paper(self) -> None:
        payload = valid_payload()
        payload["arxiv_id"] = "1804.09677"
        data = self.request_json(
            "POST",
            "/api/save",
            {"payload": payload},
        )

        self.assertTrue(data["valid"])
        self.assertTrue(Path(data["yaml_path"]).is_file())
        self.assertTrue(Path(data["json_path"]).is_file())

    def test_save_draft_endpoint_accepts_any_manifest_paper(self) -> None:
        payload = valid_payload()
        payload["arxiv_id"] = "1804.09677"
        data = self.request_json(
            "POST",
            "/api/save-draft",
            {"payload": payload},
        )

        self.assertTrue(data["valid"])
        self.assertTrue(Path(data["draft_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
