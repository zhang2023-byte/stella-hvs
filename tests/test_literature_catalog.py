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
    apply_external_catalog_urls,
    apply_agent_adjudication,
    analyze_catalog_text,
    build_agent_adjudication,
    build_catalog_verification_summary,
    extract_tables_from_tex,
    load_index_json_candidates,
    load_index_md_candidates,
    parse_abs_page,
    pdf_verification_passed,
    resolve_catalog_location,
    sample_index_json_candidates,
    sync_verification_to_notes,
    take_index_json_candidates,
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

    def test_apply_external_catalog_urls_promotes_internal_location_to_mixed(self) -> None:
        self.assertEqual(
            apply_external_catalog_urls("internal_only", ["https://vizier.cds.unistra.fr/viz-bin/VizieR"]),
            "mixed",
        )
        self.assertEqual(apply_external_catalog_urls("not_found", ["https://zenodo.org/records/1"]), "external_only")

    def test_pdf_verification_requires_trusted_extraction_for_possible_verdicts(self) -> None:
        self.assertFalse(
            pdf_verification_passed(
                {
                    "analysis": {"verdict": "possible"},
                    "extractor": "raw_strings",
                }
            )
        )
        self.assertTrue(
            pdf_verification_passed(
                {
                    "analysis": {"verdict": "possible"},
                    "extractor": "pypdf",
                }
            )
        )

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

    def test_load_index_md_candidates_supports_current_yearly_index_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            notes_dir = root / "notes"
            month_dir = notes_dir / "2026" / "2026-03"
            month_dir.mkdir(parents=True)
            (notes_dir / "index.md").write_text(
                "# Yearly High-Velocity Star Literature Index\n\n"
                "## 2026\n\n"
                "- [A stellar catalog paper](2026/2026-03/2026-03.md)\n"
                "  - 2026-03; 2026-03-12 00:00:00\n",
                encoding="utf-8",
            )
            (month_dir / "2026-03.json").write_text(
                json.dumps({"papers": [{"title": "A stellar catalog paper", "arxiv_id": "2603.00001"}]}),
                encoding="utf-8",
            )

            candidates = load_index_md_candidates(notes_dir / "index.md")

        self.assertEqual(candidates[0]["month"], "2026-03")
        self.assertEqual(candidates[0]["arxiv_id"], "2603.00001")

    def test_load_index_json_candidates_reads_flat_paper_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            notes_dir = root / "notes"
            notes_dir.mkdir(parents=True)
            (notes_dir / "index.json").write_text(
                json.dumps(
                    {
                        "schema_version": "stella.literature.index.v4",
                        "papers": [
                            {
                                "title": "A stellar catalog paper",
                                "arxiv_id": "2603.00001",
                                "month": "2026-03",
                                "navigation_path": "2026/2026-03/2026-03.md",
                                "json_path": "2026/2026-03/2026-03.json",
                            },
                            {
                                "title": "A second paper",
                                "arxiv_id": "2603.00002",
                                "month": "2026-03",
                                "navigation_path": "2026/2026-03/2026-03.md",
                                "json_path": "2026/2026-03/2026-03.json",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            candidates = load_index_json_candidates(notes_dir / "index.json")

        self.assertEqual([item["arxiv_id"] for item in candidates], ["2603.00001", "2603.00002"])

    def test_sample_index_json_candidates_uses_seeded_sampling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            notes_dir = root / "notes"
            notes_dir.mkdir(parents=True)
            (notes_dir / "index.json").write_text(
                json.dumps(
                    {
                        "schema_version": "stella.literature.index.v4",
                        "papers": [
                            {"title": "Paper 1", "arxiv_id": "2603.00001", "month": "2026-03", "navigation_path": "a"},
                            {"title": "Paper 2", "arxiv_id": "2603.00002", "month": "2026-03", "navigation_path": "b"},
                            {"title": "Paper 3", "arxiv_id": "2603.00003", "month": "2026-03", "navigation_path": "c"},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            sampled = sample_index_json_candidates(notes_dir / "index.json", count=2, seed=7)

        self.assertEqual(len(sampled), 2)
        self.assertEqual([item["arxiv_id"] for item in sampled], ["2603.00002", "2603.00001"])

    def test_take_index_json_candidates_can_skip_verified_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            notes_dir = root / "notes"
            notes_dir.mkdir(parents=True)
            (notes_dir / "index.json").write_text(
                json.dumps(
                    {
                        "schema_version": "stella.literature.index.v4",
                        "papers": [
                            {
                                "title": "Verified paper",
                                "arxiv_id": "2603.00001",
                                "month": "2026-03",
                                "navigation_path": "a",
                                "catalog_verification": {"verified": True, "has_catalog": True},
                            },
                            {"title": "Pending paper 1", "arxiv_id": "2603.00002", "month": "2026-03", "navigation_path": "b"},
                            {"title": "Pending paper 2", "arxiv_id": "2603.00003", "month": "2026-03", "navigation_path": "c"},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            taken = take_index_json_candidates(notes_dir / "index.json", count=2, only_unverified=True)

        self.assertEqual([item["arxiv_id"] for item in taken], ["2603.00002", "2603.00003"])

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

    def test_verify_paper_catalog_keeps_abs_page_external_catalog_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp) / "literature"

            def fake_download_text(url: str, timeout: int = 45) -> str:
                if url.endswith("/abs/2603.00001"):
                    return """
                    <div class="full-text">
                      <li><a href="/pdf/2603.00001" class="abs-button download-pdf">View PDF</a></li>
                      <li><a href="https://arxiv.org/html/2603.00001v1" id="latexml-download-link">HTML</a></li>
                      <li><a href="/src/2603.00001" class="abs-button download-eprint">TeX Source</a></li>
                      <li><a href="https://vizier.cds.unistra.fr/viz-bin/VizieR">CDS</a></li>
                    </div>
                    <td class="tablecell comments"><span class="descriptor">Comments:</span> Machine-readable catalog at CDS.</td>
                    """
                return "<html><body>Table 1 lists 42 stars with radial velocity and parallax.</body></html>"

            def fake_download_to_path(url: str, destination: Path, retries: int = 3, timeout: int = 60) -> dict[str, object]:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"placeholder")
                return {"ok": True, "url": url, "path": str(destination), "size_bytes": 11, "sha256": "abc"}

            def fake_extract_pdf_text(pdf_path: Path) -> dict[str, object]:
                return {
                    "text": "Table 1 lists 42 stars with radial velocity and parallax.",
                    "page_count": 12,
                    "extractor": "pypdf",
                }

            def fake_safe_extract_tar(archive_path: Path, destination: Path) -> list[str]:
                destination.mkdir(parents=True, exist_ok=True)
                (destination / "paper.tex").write_text(
                    r"""
                    \begin{deluxetable}{cc}
                    \tablehead{\colhead{Name} & \colhead{RV}}
                    \startdata
                    HVS1 & 720 \\
                    \enddata
                    \end{deluxetable}
                    """,
                    encoding="utf-8",
                )
                return ["paper.tex"]

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

        self.assertIn("https://vizier.cds.unistra.fr/viz-bin/VizieR", record["catalog"]["external_urls"])
        self.assertEqual(record["catalog"]["location"], "mixed")

    def test_verify_paper_catalog_uses_source_fallback_when_pdf_is_only_raw_strings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp) / "literature"

            def fake_download_text(url: str, timeout: int = 45) -> str:
                if url.endswith("/abs/2603.00001"):
                    return """
                    <div class="full-text">
                      <li><a href="/pdf/2603.00001" class="abs-button download-pdf">View PDF</a></li>
                      <li><a href="/src/2603.00001" class="abs-button download-eprint">TeX Source</a></li>
                    </div>
                    """
                return ""

            def fake_download_to_path(url: str, destination: Path, retries: int = 3, timeout: int = 60) -> dict[str, object]:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"placeholder")
                return {"ok": True, "url": url, "path": str(destination), "size_bytes": 11, "sha256": "abc"}

            def fake_extract_pdf_text(pdf_path: Path) -> dict[str, object]:
                return {
                    "text": "<< /Type /Annot /Subtype /Link /A << /D (table.1) /S /GoTo >>",
                    "page_count": None,
                    "extractor": "raw_strings",
                }

            def fake_safe_extract_tar(archive_path: Path, destination: Path) -> list[str]:
                destination.mkdir(parents=True, exist_ok=True)
                (destination / "paper.tex").write_text(
                    r"""
                    We present a catalog of 42 stars.
                    \begin{deluxetable}{cc}
                    \tablehead{\colhead{Name} & \colhead{RV}}
                    \startdata
                    HVS1 & 720 \\
                    \enddata
                    \end{deluxetable}
                    """,
                    encoding="utf-8",
                )
                return ["paper.tex"]

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

        self.assertFalse(record["verification"]["pdf_verified"])
        self.assertEqual(record["verification"]["overall_verdict"], "confirmed_with_source_fallback")

    def test_build_catalog_verification_summary_prefers_agent_adjudication(self) -> None:
        record = {
            "generated_at": "2026-04-21T12:34:56",
            "catalog": {"location": "internal_only"},
            "verification": {"overall_verdict": "confirmed_with_source_fallback"},
            "agent_adjudication": {
                "schema_version": "stella.literature.catalog.agent_adjudication.v1",
                "reviewed_at": "2026-04-21T13:00:00",
                "reviewed_by": "agent",
                "skill_path": "skills/literature-catalog-verifier/SKILL.md",
                "skill_version": "0.2.0",
                "has_catalog_data": True,
                "catalog_scope": "sample_level",
                "internal_delivery": "format_only",
                "external_delivery": "full",
                "location_class": "mixed",
                "primary_host": "china-vo",
                "confidence": "high",
                "overall_verdict": "agent_confirmed",
                "reasoning_notes": "The full machine-readable catalog is externally hosted.",
            },
        }

        summary = build_catalog_verification_summary(
            record,
            paper_dir=Path("/tmp/literature/2401.02017"),
            workspace_root=Path("/tmp"),
        )

        self.assertEqual(summary["decision_source"], "agent")
        self.assertEqual(summary["catalog_location"], "mixed")
        self.assertEqual(summary["overall_verdict"], "agent_confirmed")
        self.assertEqual(summary["primary_host"], "china-vo")
        self.assertEqual(summary["internal_delivery"], "format_only")
        self.assertEqual(summary["external_delivery"], "full")
        self.assertEqual(summary["confidence"], "high")

    def test_verify_paper_catalog_preserves_existing_agent_adjudication_on_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp) / "literature"
            paper_dir = output_root / "2603.00001"
            paper_dir.mkdir(parents=True)
            existing_record = {
                "schema_version": "stella.literature.catalog.v2",
                "generated_at": "2026-04-21T11:00:00",
                "arxiv_id": "2603.00001",
                "title": "Existing paper",
                "catalog": {"location": "internal_only"},
                "verification": {"overall_verdict": "confirmed_with_source_fallback"},
                "agent_adjudication": {
                    "schema_version": "stella.literature.catalog.agent_adjudication.v1",
                    "reviewed_at": "2026-04-21T12:00:00",
                    "reviewed_by": "agent",
                    "skill_path": "skills/literature-catalog-verifier/SKILL.md",
                    "skill_version": "0.2.0",
                    "has_catalog_data": True,
                    "catalog_scope": "sample_level",
                    "internal_delivery": "format_only",
                    "external_delivery": "full",
                    "location_class": "mixed",
                    "primary_host": "china-vo",
                    "confidence": "high",
                    "overall_verdict": "agent_confirmed",
                    "reasoning_notes": "Preserve me.",
                },
            }
            (paper_dir / "record.json").write_text(json.dumps(existing_record, ensure_ascii=False, indent=2), encoding="utf-8")

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
                return ["paper.tex"]

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

            self.assertEqual(record["agent_adjudication"]["primary_host"], "china-vo")
            self.assertEqual(record["agent_adjudication"]["skill_path"], "skills/literature-catalog-verifier/SKILL.md")
            self.assertEqual(record["agent_adjudication"]["skill_version"], "0.2.0")
            summary_text = (paper_dir / "summary.md").read_text(encoding="utf-8")
            self.assertIn("## Agent Adjudication", summary_text)
            self.assertIn("primary_host: `china-vo`", summary_text)
            self.assertIn("skill_version: `0.2.0`", summary_text)

    def test_sync_verification_to_notes_updates_month_json_and_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            notes_dir = root / "notes"
            month_dir = notes_dir / "2026" / "2026-03"
            month_dir.mkdir(parents=True)
            month_json = month_dir / "2026-03.json"
            month_json.write_text(
                json.dumps(
                    {
                        "schema_version": "stella.literature.month.v2",
                        "month": "2026-03",
                        "date_from": "2026-03-01",
                        "date_to": "2026-03-31",
                        "run": {"run_id": "run-1", "started_at": "2026-04-21T10:00:00"},
                        "config": {"source": "deepxiv", "classifier": "rules", "queries": [], "max_results": 20},
                        "stats": {"relevant_count": 1, "raw_unique": 1},
                        "search_log": [],
                        "papers": [
                            {
                                "title": "A stellar catalog paper",
                                "arxiv_id": "2603.00001",
                                "published_at": "2026-03-12",
                                "links": {
                                    "abs": "https://arxiv.org/abs/2603.00001",
                                    "pdf": "https://arxiv.org/pdf/2603.00001",
                                },
                                "triage": {"level": "direct", "label": "rule-direct"},
                                "abstract": {"source": "deepxiv", "text": "We present a catalog of high-velocity stars."},
                                "brief": {"fetched": False, "skipped_reason": None},
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            literature_root = root / "literature"
            paper_dir = literature_root / "2603.00001"
            paper_dir.mkdir(parents=True)
            (paper_dir / "record.json").write_text("{}", encoding="utf-8")
            (paper_dir / "summary.md").write_text("# Summary\n", encoding="utf-8")

            result = sync_verification_to_notes(
                notes_dir=notes_dir,
                arxiv_id="2603.00001",
                verification_record={
                    "generated_at": "2026-04-21T12:34:56",
                    "catalog": {"location": "mixed"},
                    "verification": {"overall_verdict": "confirmed"},
                },
                literature_root=literature_root,
                workspace_root=root,
            )

            updated_record = json.loads(month_json.read_text(encoding="utf-8"))
            updated_paper = updated_record["papers"][0]
            index_record = json.loads((notes_dir / "index.json").read_text(encoding="utf-8"))
            markdown = (month_dir / "2026-03.md").read_text(encoding="utf-8")
            index_markdown = (notes_dir / "index.md").read_text(encoding="utf-8")

        self.assertEqual(result["matched_months"], ["2026-03"])
        self.assertEqual(result["updated_paper_count"], 1)
        self.assertEqual(
            updated_paper["catalog_verification"],
            {
                "verified": True,
                "verified_at": "2026-04-21T12:34:56",
                "has_catalog": True,
                "overall_verdict": "confirmed",
                "catalog_location": "mixed",
                "record_path": "literature/2603.00001/record.json",
                "summary_path": "literature/2603.00001/summary.md",
                "decision_source": "automated",
            },
        )
        self.assertEqual(index_record["schema_version"], "stella.literature.index.v4")
        self.assertEqual(index_record["summary"]["verified_count"], 1)
        self.assertEqual(index_record["summary"]["verified_catalog_count"], 1)
        self.assertTrue(index_record["papers"][0]["catalog_verification"]["has_catalog"])
        self.assertIn("Paper-level catalog verification", markdown)
        self.assertIn("Paper-level verification: 1 paper checked; 1 paper with catalog confirmed", index_markdown)

    def test_sync_verification_to_notes_prefers_agent_adjudication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            notes_dir = root / "notes"
            month_dir = notes_dir / "2024" / "2024-01"
            month_dir.mkdir(parents=True)
            month_json = month_dir / "2024-01.json"
            month_json.write_text(
                json.dumps(
                    {
                        "schema_version": "stella.literature.month.v2",
                        "month": "2024-01",
                        "date_from": "2024-01-01",
                        "date_to": "2024-01-31",
                        "run": {"run_id": "run-1", "started_at": "2026-04-21T10:00:00"},
                        "config": {"source": "deepxiv", "classifier": "rules", "queries": [], "max_results": 20},
                        "stats": {"relevant_count": 1, "raw_unique": 1},
                        "search_log": [],
                        "papers": [
                            {
                                "title": "An adjudicated catalog paper",
                                "arxiv_id": "2401.02017",
                                "published_at": "2024-01-05",
                                "links": {
                                    "abs": "https://arxiv.org/abs/2401.02017",
                                    "pdf": "https://arxiv.org/pdf/2401.02017",
                                },
                                "triage": {"level": "direct", "label": "rule-direct"},
                                "abstract": {"source": "deepxiv", "text": "We present a catalog of high-velocity stars."},
                                "brief": {"fetched": False, "skipped_reason": None},
                            }
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            literature_root = root / "literature"
            paper_dir = literature_root / "2401.02017"
            paper_dir.mkdir(parents=True)
            base_record = {
                "schema_version": "stella.literature.catalog.v2",
                "generated_at": "2026-04-21T12:34:56",
                "arxiv_id": "2401.02017",
                "title": "An adjudicated catalog paper",
                "catalog": {"location": "internal_only"},
                "verification": {"overall_verdict": "confirmed_with_source_fallback"},
            }
            (paper_dir / "record.json").write_text(json.dumps(base_record, ensure_ascii=False, indent=2), encoding="utf-8")
            (paper_dir / "summary.md").write_text("# Summary\n", encoding="utf-8")

            adjudication = build_agent_adjudication(
                record=base_record,
                reviewed_at="2026-04-21T13:00:00",
                reviewed_by="agent",
                skill_path="skills/literature-catalog-verifier/SKILL.md",
                skill_version="0.2.0",
                has_catalog_data=True,
                catalog_scope="sample_level",
                internal_delivery="format_only",
                external_delivery="full",
                location_class="mixed",
                primary_host="china-vo",
                confidence="high",
                evidence=["Catalog available on China-VO."],
                reasoning_notes="The full machine-readable catalog is external.",
                overall_verdict="agent_confirmed",
            )
            updated_record = apply_agent_adjudication(
                record_path=paper_dir / "record.json",
                adjudication=adjudication,
            )

            result = sync_verification_to_notes(
                notes_dir=notes_dir,
                arxiv_id="2401.02017",
                verification_record=updated_record,
                literature_root=literature_root,
                workspace_root=root,
            )

            updated_month_record = json.loads(month_json.read_text(encoding="utf-8"))
            updated_paper = updated_month_record["papers"][0]
            index_record = json.loads((notes_dir / "index.json").read_text(encoding="utf-8"))
            markdown = (month_dir / "2024-01.md").read_text(encoding="utf-8")
            index_markdown = (notes_dir / "index.md").read_text(encoding="utf-8")

        self.assertEqual(result["matched_months"], ["2024-01"])
        self.assertEqual(updated_paper["catalog_verification"]["decision_source"], "agent")
        self.assertEqual(updated_paper["catalog_verification"]["catalog_location"], "mixed")
        self.assertEqual(updated_paper["catalog_verification"]["primary_host"], "china-vo")
        self.assertEqual(updated_paper["catalog_verification"]["internal_delivery"], "format_only")
        self.assertEqual(updated_paper["catalog_verification"]["external_delivery"], "full")
        self.assertEqual(updated_record["agent_adjudication"]["skill_path"], "skills/literature-catalog-verifier/SKILL.md")
        self.assertEqual(updated_record["agent_adjudication"]["skill_version"], "0.2.0")
        self.assertEqual(index_record["papers"][0]["catalog_verification"]["decision_source"], "agent")
        self.assertIn("source=`agent`", markdown)
        self.assertIn("host=`china-vo`", markdown)
        self.assertIn("verified: agent catalog", index_markdown)


if __name__ == "__main__":
    unittest.main()
