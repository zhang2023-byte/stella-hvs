"""Operation-adapter tests for the contribution-only site builder."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from stella.web.catalog_site import build_contribution_site

OBJECT_RECORD = {
    "schema": {"name": "hvs_contribution_catalog.object", "version": 1},
    "object_id": "hvc-001",
    "display_name": "J1234",
    "timeline": [
        {
            "arxiv_id": "2601.08888",
            "record_id": "obj-001",
            "display_name": "J1234",
            "identifiers": [{"value": "J1234", "evidence": []}],
            "contribution_type": "candidates_found",
            "contribution_summary": "Retained as an unbound candidate.",
            "contribution_evidence": [
                {"kind": "text", "path": "main.tex", "start_line": 3, "end_line": 3}
            ],
            "paper_boundness": {"status": "unbound", "evidence": []},
        }
    ],
}


def _make_catalog(root: Path) -> None:
    catalog_dir = root / "literature" / "hvs_contribution_catalog"
    catalog_dir.mkdir(parents=True)
    (catalog_dir / "index.json").write_text(
        json.dumps(
            {
                "schema": {"name": "hvs_contribution_catalog.index", "version": 1},
                "objects": [{"object_id": "hvc-001"}],
            }
        ),
        encoding="utf-8",
    )
    (catalog_dir / "hvc-001.json").write_text(
        json.dumps(OBJECT_RECORD), encoding="utf-8"
    )


class BuildContributionSiteAdapterTest(unittest.TestCase):
    def test_site_builds_into_temporary_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as out:
            root = Path(tmp)
            _make_catalog(root)
            output = Path(out)
            result = build_contribution_site(
                {"site_output_dir": str(output)}, root=root
            )
            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["object_count"], 1)
            self.assertTrue((output / "index.html").is_file())
            self.assertTrue((output / "objects" / "hvc-001.html").is_file())
            # Nothing is written into the repository's tracked pages/.
            self.assertFalse((root / "pages").exists())

    def test_site_reports_optional_dynamics_presence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as out:
            root = Path(tmp)
            _make_catalog(root)
            (root / "literature" / "hvs_dynamics_results").mkdir()
            result = build_contribution_site(
                {"site_output_dir": str(out)}, root=root
            )
            self.assertTrue(result["dynamics_included"])

    def test_site_fails_closed_without_timelines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = build_contribution_site({}, root=Path(tmp))
            self.assertEqual(result["status"], "failed")
            self.assertIn("contribution catalog", result["reason"])

    def test_site_reads_only_contribution_inputs(self) -> None:
        # The adapter touches literature/ inputs only; no candidate catalog,
        # benchmark, or gold path participates in site generation.
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as out:
            root = Path(tmp)
            _make_catalog(root)
            import inspect

            from stella.web import catalog_site

            source = inspect.getsource(catalog_site)
            self.assertNotIn("hvs_candidate_catalog", source)
            self.assertNotIn("benchmark", source)
            result = build_contribution_site(
                {"site_output_dir": str(out)}, root=root
            )
            self.assertFalse((root / "benchmark").exists())


if __name__ == "__main__":
    unittest.main()
