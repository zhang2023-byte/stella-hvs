from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from high_velocity_lit.literature_catalog import (  # noqa: E402
    analyze_catalog_text,
    extract_tables_from_tex,
    load_index_md_candidates,
    parse_abs_page,
    resolve_catalog_location,
    select_relevant_sections,
    verify_paper_catalog,
)


class FakeDeepXivClient:
    def head(self, arxiv_id: str) -> dict[str, object]:
        return {
            "title": "A stellar catalog paper",
            "abstract": "We present a catalog of high-velocity stars with Gaia astrometry.",
            "sections": [
                {"name": "1. Introduction"},
                {"name": "2. Observations"},
                {"name": "Appendix A Catalog"},
            ],
        }

    def section(self, arxiv_id: str, section_name: str) -> str:
        if "Catalog" in section_name:
            return "The full machine-readable table is available at CDS https://vizier.cds.unistra.fr/"
        return "We measure proper motion, parallax, and radial velocity for 42 stars."

    def raw(self, arxiv_id: str) -> str:
        return "Raw full text."


class FakeArxivClient:
    def metadata(self, arxiv_id: str) -> dict[str, object]:
        return {
            "arxiv_id": arxiv_id,
            "title": "A stellar catalog paper",
            "doi": "10.1000/example",
            "journal_ref": "Astronomy Journal 1, 1-10 (2026)",
            "comment": "Machine-readable catalog at CDS.",
            "links": {
                "abs": f"https://arxiv.org/abs/{arxiv_id}",
                "pdf": f"https://arxiv.org/pdf/{arxiv_id}",
            },
        }


class LiteratureCatalogTest(unittest.TestCase):
    def test_analyze_catalog_text_detects_external_catalog(self) -> None:
        result = analyze_catalog_text(
            "We present a catalog of 42 stars. The full machine-readable table is available at CDS.",
            source="test",
        )

        self.assertEqual(result["verdict"], "present")
        self.assertEqual(result["location_hint"], "mixed")
        self.assertIn("catalog", result["catalog_hits"])
        self.assertIn("cds", result["external_hits"])

    def test_analyze_catalog_text_ignores_background_mentions_of_vizier(self) -> None:
        result = analyze_catalog_text(
            "We present a catalog in Table 1 with stellar parameters and radial velocity measurements. "
            "Background cross-matches to VizieR are discussed for prior work only.",
            source="test",
        )

        self.assertEqual(result["verdict"], "present")
        self.assertEqual(result["location_hint"], "internal")
        self.assertEqual(result["external_hits"], [])

    def test_select_relevant_sections_prioritizes_catalog_and_appendix(self) -> None:
        sections = select_relevant_sections(
            {
                "sections": [
                    {"name": "1. Introduction"},
                    {"name": "2. Results"},
                    {"name": "Appendix B Catalog"},
                    {"name": "Data Availability"},
                ]
            },
            max_sections=2,
        )

        self.assertEqual(sections, ["Appendix B Catalog", "Data Availability"])

    def test_parse_abs_page_extracts_core_links(self) -> None:
        parsed = parse_abs_page(
            """
            <div class="full-text">
              <li><a href="/pdf/2601.00001" class="abs-button download-pdf">View PDF</a></li>
              <li><a href="https://arxiv.org/html/2601.00001v1" id="latexml-download-link">HTML</a></li>
              <li><a href="/src/2601.00001" class="abs-button download-eprint">TeX Source</a></li>
              <li><a href="https://vizier.cds.unistra.fr/viz-bin/VizieR">CDS</a></li>
            </div>
            <td class="tablecell comments"><span class="descriptor">Comments:</span> Full machine-readable table at CDS.</td>
            """
        )

        self.assertEqual(parsed["pdf_url"], "https://arxiv.org/pdf/2601.00001")
        self.assertEqual(parsed["source_url"], "https://arxiv.org/src/2601.00001")
        self.assertEqual(parsed["html_url"], "https://arxiv.org/html/2601.00001v1")
        self.assertEqual(parsed["descriptors"]["comments"], "Full machine-readable table at CDS.")
        self.assertEqual(parsed["external_links"][0]["url"], "https://vizier.cds.unistra.fr/viz-bin/VizieR")

    def test_resolve_catalog_location_treats_mixed_hints_as_external_and_internal(self) -> None:
        location = resolve_catalog_location(
            deepxiv={"analysis": {"location_hint": "mixed", "external_urls": []}},
            pdf={"analysis": {"location_hint": "unknown", "external_urls": []}},
            source={"analysis": {"location_hint": "unknown", "external_urls": []}, "data_files": [], "tables": []},
        )

        self.assertEqual(location, "mixed")

    def test_load_index_md_candidates_resolves_titles_back_to_month_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            notes_dir = root / "notes"
            month_dir = notes_dir / "2026" / "2026-03"
            month_dir.mkdir(parents=True)
            (notes_dir / "index.md").write_text(
                "- [A stellar catalog paper](2026/2026-03/2026-03.md) (2026-03) - `2026/2026-03/2026-03.md`\n",
                encoding="utf-8",
            )
            (month_dir / "2026-03.json").write_text(
                json.dumps(
                    {
                        "papers": [
                            {
                                "title": "A stellar catalog paper",
                                "arxiv_id": "2603.00001",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            candidates = load_index_md_candidates(notes_dir / "index.md")

        self.assertEqual(candidates[0]["arxiv_id"], "2603.00001")

    def test_extract_tables_from_tex_writes_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tex_path = root / "paper.tex"
            tex_path.write_text(
                r"""
                \begin{deluxetable}{ccc}
                \tablecaption{Catalog excerpt}
                \tablehead{\colhead{Name} & \colhead{RV} & \colhead{Distance}}
                \startdata
                HVS1 & 720 & 50 \\
                HVS2 & 680 & 45 \\
                \enddata
                \end{deluxetable}
                """,
                encoding="utf-8",
            )

            tables = extract_tables_from_tex(tex_path, root / "tables", root=root)

            self.assertEqual(len(tables), 1)
            csv_path = Path(tables[0]["csv_path"])
            self.assertTrue(csv_path.exists())
            csv_text = csv_path.read_text(encoding="utf-8")
            self.assertIn("Name,RV,Distance", csv_text)
            self.assertIn("HVS1,720,50", csv_text)

    def test_verify_paper_catalog_runs_end_to_end_with_mocked_downloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp) / "literature"

            def fake_download_text(url: str, timeout: int = 45) -> str:
                if url.endswith("/abs/2603.00001"):
                    return """
                    <div class="full-text">
                      <li><a href="/pdf/2603.00001" class="abs-button download-pdf">View PDF</a></li>
                      <li><a href="https://arxiv.org/html/2603.00001v1" id="latexml-download-link">HTML</a></li>
                      <li><a href="/src/2603.00001" class="abs-button download-eprint">TeX Source</a></li>
                    </div>
                    """
                return "<html><body>The full machine-readable table is available at CDS.</body></html>"

            def fake_download_to_path(url: str, destination: Path, retries: int = 3, timeout: int = 60) -> dict[str, object]:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"placeholder")
                return {"ok": True, "url": url, "path": str(destination), "size_bytes": 11, "sha256": "abc"}

            def fake_extract_pdf_text(pdf_path: Path) -> dict[str, object]:
                return {
                    "text": "We present a catalog of 42 stars. Full machine-readable table at CDS.",
                    "page_count": 12,
                    "extractor": "fake",
                }

            def fake_safe_extract_tar(archive_path: Path, destination: Path) -> list[str]:
                destination.mkdir(parents=True, exist_ok=True)
                (destination / "paper.tex").write_text(
                    r"""
                    Full machine-readable table is available at CDS https://vizier.cds.unistra.fr/
                    \begin{deluxetable}{cc}
                    \tablehead{\colhead{Name} & \colhead{RV}}
                    \startdata
                    HVS1 & 720 \\
                    \enddata
                    \end{deluxetable}
                    """,
                    encoding="utf-8",
                )
                (destination / "catalog.csv").write_text("name,rv\nHVS1,720\n", encoding="utf-8")
                return ["paper.tex", "catalog.csv"]

            with (
                patch("high_velocity_lit.literature_catalog.download_text", fake_download_text),
                patch("high_velocity_lit.literature_catalog.download_to_path", fake_download_to_path),
                patch("high_velocity_lit.literature_catalog.extract_pdf_text", fake_extract_pdf_text),
                patch("high_velocity_lit.literature_catalog.safe_extract_tar", fake_safe_extract_tar),
            ):
                record = verify_paper_catalog(
                    arxiv_id="2603.00001",
                    output_root=output_root,
                    deepxiv_client=FakeDeepXivClient(),
                    arxiv_client=FakeArxivClient(),
                    force=True,
                    max_sections=3,
                )

            self.assertEqual(record["verification"]["overall_verdict"], "confirmed")
            self.assertEqual(record["catalog"]["location"], "mixed")
            self.assertTrue(record["source"]["data_files"])
            self.assertTrue(record["source"]["tables"])
            self.assertTrue((output_root / "2603.00001" / "record.json").exists())
            self.assertTrue((output_root / "2603.00001" / "summary.md").exists())


if __name__ == "__main__":
    unittest.main()
