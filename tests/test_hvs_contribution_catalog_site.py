"""Contribution catalog web view tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.test_hvs_contribution_scoring import ai_contribution, ai_document, ai_value
from stella.web.contribution_catalog_site import (
    LATEST_REPORT_DISCLAIMER,
    build_contribution_catalog_site,
    latest_reported_status,
    render_index,
    render_object_page,
)


def timeline_entry(arxiv_id: str, status: str, contribution_type: str) -> dict:
    return {
        "arxiv_id": arxiv_id,
        "record_id": "obj-001",
        "display_name": "FIC-1",
        "identifiers": {"gaia_source_id": "", "all": [{"value": "FIC-1", "evidence": []}]},
        "contribution_type": contribution_type,
        "contribution_note": "The paper did substantive work.",
        "contribution_evidence": [
            {"kind": "text", "path": "main.tex", "start_line": 3, "end_line": 3}
        ],
        "paper_boundness": {
            "status": status,
            "evidence": [
                {"kind": "text", "path": "main.tex", "start_line": 3, "end_line": 3}
            ],
        },
        "measurement_status": "measurements_complete",
        "measurements": [
            {
                "field": "observed_phase_space.distance",
                "values": [
                    ai_value("8.2", paper_preferred=True),
                    ai_value("8.6", paper_preferred=None),
                ],
            }
        ],
        "failure": None,
    }


def catalog_record() -> dict:
    return {
        "schema": {"name": "hvs_contribution_catalog.object", "version": 1},
        "generated_at": "2026-08-22T00:00:00+00:00",
        "object_id": "hvc-fic-1",
        "display_name": "FIC-1",
        "aliases": ["FIC-1"],
        "gaia_source_keys": [],
        "timeline": [
            timeline_entry("2601.00001", "unbound", "candidates_found"),
            timeline_entry("2601.00002", "bound", "follow_up"),
        ],
        "display_note": "timeline record",
    }


class ContributionCatalogSiteTest(unittest.TestCase):
    def test_latest_reported_status_is_derived_and_labeled(self) -> None:
        record = catalog_record()
        latest = latest_reported_status(record)
        self.assertEqual(latest, {"status": "bound", "arxiv_id": "2601.00002"})
        page = render_object_page(record)
        self.assertIn("Latest reported status", page)
        self.assertIn("reported by 2601.00002", page)
        self.assertIn("paper report", page)
        self.assertIn(LATEST_REPORT_DISCLAIMER, page)
        for forbidden in (
            "canonical",
            "authoritative",
            "Stella truth",
            "current physical state",
            "adopted by Stella",
        ):
            self.assertNotIn(forbidden.replace("Stella truth", "stella truth"), page.replace(LATEST_REPORT_DISCLAIMER, ""))

    def test_bound_reassessment_visible_and_all_values_kept(self) -> None:
        page = render_object_page(catalog_record())
        self.assertIn("bound (paper report)", page)
        self.assertIn("unbound (paper report)", page)
        self.assertIn("candidates_found", page)
        self.assertIn("follow_up", page)
        self.assertIn("8.2", page)
        self.assertIn("8.6", page)
        self.assertIn("condition:", page)
        self.assertIn("paper-preferred:", page)
        self.assertIn("The paper did substantive work.", page)

    def test_index_lists_objects(self) -> None:
        page = render_index([catalog_record()])
        self.assertIn("hvc-fic-1", page)
        self.assertIn("objects/hvc-fic-1.html", page)
        self.assertIn("paper report only", page)

    def test_site_build_writes_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalog_dir = Path(tmp) / "contributions"
            catalog_dir.mkdir()
            (catalog_dir / "hvc-fic-1.json").write_text(
                json.dumps(catalog_record()), encoding="utf-8"
            )
            (catalog_dir / "index.json").write_text(
                json.dumps({"objects": [{"object_id": "hvc-fic-1"}]}),
                encoding="utf-8",
            )
            web_dir = Path(tmp) / "web"
            stale_page = web_dir / "objects" / "hvc-stale.html"
            stale_page.parent.mkdir(parents=True)
            stale_page.write_text("stale", encoding="utf-8")
            result = build_contribution_catalog_site(catalog_dir, web_dir=web_dir)
            self.assertEqual(result["object_count"], 1)
            self.assertTrue((web_dir / "index.html").is_file())
            object_page = (web_dir / "objects" / "hvc-fic-1.html").read_text(encoding="utf-8")
            self.assertIn("FIC-1", object_page)
            self.assertFalse(stale_page.exists())

    def test_no_private_gold_or_scoring_content(self) -> None:
        page = render_object_page(catalog_record())
        for forbidden in ("gold_annotation", "scorecard", "scoring_details", "annotator"):
            self.assertNotIn(forbidden, page)


if __name__ == "__main__":
    unittest.main()
