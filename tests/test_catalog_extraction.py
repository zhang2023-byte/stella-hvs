from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from high_velocity_lit.catalog_extraction import (  # noqa: E402
    AGENT_LOCATOR_ALWAYS,
    MAX_EXTERNAL_BYTES,
    UnavailableExternalPageLocator,
    agent_locator_context,
    auto_catalog_jobs,
    extract_all_reviewed_catalog_tables,
    agent_links_from_decision,
    extract_catalog_tables,
    parse_latex_table_excerpt,
)

SCRIPT = ROOT / "scripts" / "extract_catalog_tables.py"
SPEC = importlib.util.spec_from_file_location("extract_catalog_tables", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
extract_cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(extract_cli)


def csv_rows(path: Path) -> list[list[str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.reader(handle))


class FakeResponse:
    def __init__(
        self,
        content: bytes,
        *,
        url: str,
        status_code: int = 200,
        content_type: str = "text/csv",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.content = content
        self.url = url
        self.status_code = status_code
        self.headers = {
            "content-type": content_type,
            "content-length": str(len(content)),
        }
        self.headers.update(headers or {})

    def iter_content(self, chunk_size: int = 1024 * 1024) -> object:
        for index in range(0, len(self.content), chunk_size):
            yield self.content[index : index + chunk_size]

    def close(self) -> None:
        return None


class StreamingFakeResponse(FakeResponse):
    def __init__(
        self,
        chunks: list[bytes],
        *,
        url: str,
        status_code: int = 200,
        content_type: str = "text/csv",
        include_content_length: bool = False,
    ) -> None:
        super().__init__(b"", url=url, status_code=status_code, content_type=content_type)
        self.chunks = chunks
        if not include_content_length:
            self.headers.pop("content-length", None)

    def iter_content(self, chunk_size: int = 1024 * 1024) -> object:
        del chunk_size
        yield from self.chunks


class FakeAgentLocator:
    def __init__(self, selected_ids: list[str]) -> None:
        self.selected_ids = selected_ids
        self.contexts: list[dict[str, object]] = []

    def locate(self, context: dict[str, object]) -> dict[str, object]:
        self.contexts.append(context)
        return {
            "decision": "download",
            "selected_candidate_ids": self.selected_ids,
            "reason": "selected by test agent",
            "stop_reason": "",
        }


class FailingAgentLocator:
    def locate(self, context: dict[str, object]) -> dict[str, object]:
        del context
        raise RuntimeError("connection refused")


class CatalogExtractionParserTest(unittest.TestCase):
    def test_cli_defaults_agent_locator_to_always(self) -> None:
        parser = extract_cli.build_parser()
        args = parser.parse_args(["--arxiv-id", "2603.00001"])

        self.assertEqual(args.agent_locator, AGENT_LOCATOR_ALWAYS)
        self.assertEqual(args.max_external_bytes, MAX_EXTERNAL_BYTES)
        self.assertEqual(args.jobs, 1)

    def test_cli_rejects_removed_fallback_locator(self) -> None:
        with self.assertRaises(Exception):
            extract_cli.parse_agent_locator("Fallback")

    def test_cli_accepts_parallel_jobs_for_all_reviewed(self) -> None:
        parser = extract_cli.build_parser()
        args = parser.parse_args(["--all-reviewed", "--jobs", "4"])

        self.assertEqual(args.jobs, 4)

    def test_cli_accepts_auto_jobs(self) -> None:
        parser = extract_cli.build_parser()
        args = parser.parse_args(["--all-reviewed", "--jobs", "Auto"])

        self.assertEqual(args.jobs, "Auto")

    def test_auto_catalog_jobs_scales_with_paper_count(self) -> None:
        self.assertEqual(auto_catalog_jobs(1), 1)
        self.assertEqual(auto_catalog_jobs(8), 2)
        self.assertEqual(auto_catalog_jobs(30), 4)
        self.assertEqual(auto_catalog_jobs(80), 8)
        self.assertEqual(auto_catalog_jobs(120), 12)

    def test_parse_simple_latex_table_to_generic_columns(self) -> None:
        parsed = parse_latex_table_excerpt(
            r"""
\begin{table}
\caption{Candidate stars}
\begin{tabular}{cc}
\hline
Name & v \\
\hline
HVS1 & 700 \\
HVS2 & 710 \\
\hline
\end{tabular}
\end{table}
"""
        )

        self.assertEqual(parsed["status"], "success")
        self.assertEqual(parsed["column_count"], 2)
        self.assertEqual(parsed["row_count"], 2)
        self.assertEqual([column["name"] for column in parsed["columns"]], ["col_001", "col_002"])
        self.assertEqual(parsed["columns"][0]["original_header"], "Name")
        self.assertEqual(parsed["data_rows"][0], ["HVS1", "700"])

    def test_parse_multi_row_header_and_unit_row(self) -> None:
        parsed = parse_latex_table_excerpt(
            r"""
\begin{tabular}{ccc}
\hline
Name & $v_{\rm tan}$ & $G$ \\
     & [km/s]        & [mag] \\
\hline
Star A & 700 & 15.1 \\
\hline
\end{tabular}
"""
        )

        self.assertEqual(parsed["status"], "success")
        self.assertEqual(parsed["header_rows"][1], ["", "[km/s]", "[mag]"])
        self.assertEqual(parsed["columns"][1]["original_header"], r"v_\rm tan | [km/s]")
        self.assertEqual(parsed["columns"][1]["unit_text"], "[km/s]")
        self.assertEqual(parsed["data_rows"], [["Star A", "700", "15.1"]])

    def test_clean_safe_latex_noise_and_comments(self) -> None:
        parsed = parse_latex_table_excerpt(
            r"""
\begin{tabular}{ccc}
\hline
Name & pm & note \\
\hline
Gaia\_DR3 & $-10.0\pm0.2$ & \dots \\ % trailing comment
\hline
\end{tabular}
"""
        )

        self.assertEqual(parsed["status"], "success")
        self.assertEqual(parsed["data_rows"], [["Gaia_DR3", "-10.0+/-0.2", "..."]])

    def test_clean_aastex_botrule_rows(self) -> None:
        parsed = parse_latex_table_excerpt(
            r"""
\begin{deluxetable*}{ccc}
\tablehead{Parameter & value & unit \\}
\startdata
R.A. & 04:38:12.8 & \\
\botrule
\enddata
\end{deluxetable*}
"""
        )

        self.assertEqual(parsed["status"], "success")
        self.assertEqual(parsed["row_count"], 1)
        self.assertEqual(parsed["data_rows"], [["R.A.", "04:38:12.8", ""]])

    def test_agent_context_uses_nearby_file_context_for_icon_download(self) -> None:
        html = """
<html>
  <div class="row">
    <div class="paperinfo-files-filename">519_HiVels_considering_the_LMC.csv</div>
    <div><a href="/res/file_upload/download?id=46038"><img alt="download"></a></div>
  </div>
  <a href="/res/paperdata/">Back to PaperData Catalogue</a>
</html>
"""
        context = agent_locator_context(
            html=html,
            base_url="https://nadc.china-vo.org/res/r101304/",
            resource={"id": "resource-china-vo"},
        )
        candidates = context["link_candidates"]

        self.assertEqual(candidates[0]["id"], "link-001")
        self.assertEqual(candidates[0]["label"], "519_HiVels_considering_the_LMC.csv")
        self.assertEqual(candidates[0]["url"], "https://nadc.china-vo.org/res/file_upload/download?id=46038")
        self.assertTrue(candidates[0]["machine_readable_hint"])
        self.assertNotIn("accepted_by_rules", candidates[0])

    def test_agent_context_prioritizes_catalog_links_before_candidate_limit(self) -> None:
        nav_links = "\n".join(f'<a href="/nav/{index}">Navigation {index}</a>' for index in range(100))
        html = f"""
<html>
  {nav_links}
  <p>Machine-readable catalog table <a href="/files/hvs_catalog.csv">CSV catalog</a></p>
</html>
"""
        context = agent_locator_context(
            html=html,
            base_url="https://example.test/page",
            resource={"id": "resource-priority", "meaning": "HVS candidate catalog"},
        )
        candidates = context["link_candidates"]

        self.assertEqual(candidates[0]["url"], "https://example.test/files/hvs_catalog.csv")
        self.assertEqual(candidates[0]["id"], "link-001")

    def test_agent_stop_reason_is_canonicalized(self) -> None:
        links, stopped_reason, reason = agent_links_from_decision(
            decision={
                "decision": "stop",
                "selected_candidate_ids": [],
                "reason": "",
                "stop_reason": "No suitable machine-readable catalog link found.",
            },
            context={"link_candidates": []},
            max_files=5,
        )

        self.assertEqual(links, [])
        self.assertEqual(stopped_reason, "agent_no_download_candidates")
        self.assertEqual(reason, "No suitable machine-readable catalog link found.")


class CatalogExtractionIntegrationTest(unittest.TestCase):
    def write_reviewed_paper(
        self,
        workspace: Path,
        *,
        bad_table: bool = False,
        external_resources: list[dict[str, object]] | None = None,
        catalog_candidates: list[dict[str, object]] | None = None,
        ads_html: str = "",
    ) -> tuple[Path, Path]:
        literature_dir = workspace / "literature"
        paper_dir = literature_dir / "2603.00001"
        source_dir = paper_dir / "arxiv_source"
        source_dir.mkdir(parents=True)
        tex = (
            r"""
\documentclass{article}
\begin{document}
\begin{table}
\caption{Candidate hypervelocity stars}
\label{tab:hvs}
\begin{tabular}{cc}
\hline
Name & v \\
\hline
HVS1 & 700 \\
\hline
\end{tabular}
\end{table}
\end{document}
""".strip()
            + "\n"
        )
        if bad_table:
            tex = "No supported table here.\n"
        source_path = source_dir / "main.tex"
        source_path.write_text(tex, encoding="utf-8")
        line_count = len(tex.splitlines())
        if catalog_candidates is None:
            catalog_candidates = [
                {
                    "id": "table-tab-hvs",
                    "kind": "latex_table",
                    "source_refs": [
                        {
                            "path": str(source_path),
                            "start_line": 1,
                            "end_line": line_count,
                            "caption": "Candidate hypervelocity stars",
                            "label": "tab:hvs",
                        }
                    ],
                }
            ]
        if external_resources is None:
            external_resources = [
                {
                    "id": "resource-cds",
                    "kind": "external_catalog_repository",
                    "url": "",
                    "meaning": "CDS table mentioned without a resolved URL.",
                }
            ]
        review = {
            "schema_version": "stella.hvs_catalog.review.v1",
            "paper": {
                "arxiv_id": "2603.00001",
                "title": "A catalog of hypervelocity stars",
                "month": "2026-03",
            },
            "review": {"status": "reviewed"},
            "catalog_candidates": catalog_candidates,
            "external_resources": external_resources,
            "rejected_candidates": [],
        }
        (paper_dir / "catalog_review.json").write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
        if ads_html:
            (paper_dir / "ads_abstract.html").write_text(ads_html, encoding="utf-8")
        return literature_dir, paper_dir

    def test_extract_catalog_tables_writes_manifest_excerpt_and_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir, paper_dir = self.write_reviewed_paper(workspace)

            result = extract_catalog_tables(
                literature_dir=literature_dir,
                arxiv_id="2603.00001",
                workspace=workspace,
                fetch_external=False,
            )

            manifest_path = paper_dir / "catalog_extraction.json"
            excerpt_path = paper_dir / "catalog_sources" / "table-tab-hvs" / "excerpt.tex"
            csv_path = paper_dir / "catalog_tables" / "table-tab-hvs.csv"
            self.assertEqual(result["summary"]["success_count"], 1)
            self.assertTrue(manifest_path.exists())
            self.assertTrue(excerpt_path.exists())
            self.assertTrue(csv_path.exists())
            self.assertEqual(csv_rows(csv_path), [["col_001", "col_002"], ["HVS1", "700"]])

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], "stella.hvs_catalog.extraction.v2")
            self.assertIn(manifest["tables"][0]["extraction_method"], {"latexml", "pandoc", "internal"})
            self.assertTrue(manifest["tables"][0]["conversion_attempts"])
            self.assertEqual(manifest["tables"][0]["columns"][0]["semantic_status"], "needs_agent_review")
            self.assertEqual(manifest["tables"][0]["usage"]["semantic_status"], "needs_agent_review")
            self.assertEqual(manifest["external_resources"][0]["status"], "skipped")
            self.assertEqual(manifest["external_resources"][0]["stopped_reason"], "network_disabled")

    def test_failed_parse_is_recorded_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir, paper_dir = self.write_reviewed_paper(workspace, bad_table=True)

            result = extract_catalog_tables(
                literature_dir=literature_dir,
                arxiv_id="2603.00001",
                fetch_external=False,
                workspace=workspace,
            )

            manifest = json.loads((paper_dir / "catalog_extraction.json").read_text(encoding="utf-8"))
            self.assertEqual(result["summary"]["failed_count"], 1)
            self.assertEqual(manifest["runs"][0]["status"], "failed")
            self.assertEqual(manifest["tables"][0]["status"], "failed")
            self.assertIn("no supported LaTeX table environment", manifest["tables"][0]["error"])
            self.assertTrue((paper_dir / "catalog_sources" / "table-tab-hvs" / "excerpt.tex").exists())

    def test_missing_external_tools_falls_back_to_internal_parser(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir, paper_dir = self.write_reviewed_paper(workspace)

            with patch("high_velocity_lit.catalog_extraction.shutil.which", return_value=None):
                extract_catalog_tables(
                    literature_dir=literature_dir,
                    arxiv_id="2603.00001",
                    fetch_external=False,
                    workspace=workspace,
                )

            manifest = json.loads((paper_dir / "catalog_extraction.json").read_text(encoding="utf-8"))
            table = manifest["tables"][0]
            self.assertEqual(table["extraction_method"], "internal")
            self.assertEqual([attempt["status"] for attempt in table["conversion_attempts"]], ["skipped", "skipped", "success"])
            self.assertEqual(csv_rows(paper_dir / "catalog_tables" / "table-tab-hvs.csv"), [["col_001", "col_002"], ["HVS1", "700"]])

    def test_cli_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir, paper_dir = self.write_reviewed_paper(workspace)

            with patch.object(
                sys,
                "argv",
                [
                    "extract_catalog_tables.py",
                    "--arxiv-id",
                    "2603.00001",
                    "--literature-dir",
                    str(literature_dir),
                    "--fetch-external",
                    "False",
                    "--dry-run",
                    "True",
                ],
            ):
                with patch("builtins.print") as fake_print:
                    exit_code = extract_cli.main()

            self.assertEqual(exit_code, 0)
            payload = json.loads(fake_print.call_args.args[0])
            self.assertTrue(payload["dry_run"])
            self.assertEqual(payload["summary"]["success_count"], 1)
            self.assertFalse((paper_dir / "catalog_extraction.json").exists())
            self.assertFalse((paper_dir / "catalog_sources").exists())
            self.assertFalse((paper_dir / "catalog_tables").exists())

    def test_local_csv_and_tsv_resources_convert_to_generic_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir, paper_dir = self.write_reviewed_paper(
                workspace,
                catalog_candidates=[],
                external_resources=[
                    {
                        "id": "resource-local-csv",
                        "kind": "local_machine_readable_file",
                        "local_path": "literature/2603.00001/arxiv_source/data.csv",
                    },
                    {
                        "id": "resource-local-tsv",
                        "kind": "local_machine_readable_file",
                        "local_path": "literature/2603.00001/arxiv_source/data.tsv",
                    },
                ],
            )
            (paper_dir / "arxiv_source" / "data.csv").write_text("name,vel\nA,700\n", encoding="utf-8")
            (paper_dir / "arxiv_source" / "data.tsv").write_text("name\tvel\nB\t710\n", encoding="utf-8")

            result = extract_catalog_tables(
                literature_dir=literature_dir,
                arxiv_id="2603.00001",
                workspace=workspace,
                fetch_external=False,
            )

            self.assertEqual(result["summary"]["external_success_count"], 2)
            self.assertEqual(csv_rows(paper_dir / "catalog_tables" / "resource-local-csv.csv"), [["col_001", "col_002"], ["A", "700"]])
            self.assertEqual(csv_rows(paper_dir / "catalog_tables" / "resource-local-tsv.csv"), [["col_001", "col_002"], ["B", "710"]])
            manifest = json.loads((paper_dir / "catalog_extraction.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["tables"][0]["columns"][0]["original_name"], "name")

    def test_local_cds_mrt_resource_converts_to_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir, paper_dir = self.write_reviewed_paper(
                workspace,
                catalog_candidates=[],
                external_resources=[
                    {
                        "id": "resource-local-mrt",
                        "kind": "local_machine_readable_file",
                        "local_path": "literature/2603.00001/arxiv_source/table.mrt",
                    }
                ],
            )
            (paper_dir / "arxiv_source" / "table.mrt").write_text(
                """Title: Test MRT
Authors: A.
Table: Tiny table
================================================================================
Byte-by-byte Description of file: table.dat
--------------------------------------------------------------------------------
 Bytes Format Units Label Explanations
--------------------------------------------------------------------------------
 1- 3 I3     ---   ID    Identifier
 5- 8 F4.1   km/s  Vel   Velocity
--------------------------------------------------------------------------------
001 12.3
002 45.6
""",
                encoding="utf-8",
            )

            extract_catalog_tables(
                literature_dir=literature_dir,
                arxiv_id="2603.00001",
                workspace=workspace,
                fetch_external=False,
            )

            self.assertEqual(csv_rows(paper_dir / "catalog_tables" / "resource-local-mrt.csv"), [["col_001", "col_002"], ["1", "12.3"], ["2", "45.6"]])
            manifest = json.loads((paper_dir / "catalog_extraction.json").read_text(encoding="utf-8"))
            table = manifest["tables"][0]
            self.assertEqual(table["columns"][1]["unit_text"], "km / s")
            self.assertEqual(table["columns"][1]["description"], "Velocity")

    def test_local_fits_resource_converts_to_csv(self) -> None:
        from astropy.table import Table

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir, paper_dir = self.write_reviewed_paper(
                workspace,
                catalog_candidates=[],
                external_resources=[
                    {
                        "id": "resource-local-fits",
                        "kind": "local_machine_readable_file",
                        "local_path": "literature/2603.00001/arxiv_source/catalog.fits",
                    }
                ],
            )
            fits_path = paper_dir / "arxiv_source" / "catalog.fits"
            Table({"Gaia_id": [123, 456], "RV": [10.5, -20.0]}).write(fits_path)

            extract_catalog_tables(
                literature_dir=literature_dir,
                arxiv_id="2603.00001",
                workspace=workspace,
                fetch_external=False,
            )

            self.assertEqual(csv_rows(paper_dir / "catalog_tables" / "resource-local-fits.csv"), [["col_001", "col_002"], ["123", "10.5"], ["456", "-20.0"]])
            manifest = json.loads((paper_dir / "catalog_extraction.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["tables"][0]["columns"][0]["original_name"], "Gaia_id")

    def test_direct_url_download_converts_to_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir, paper_dir = self.write_reviewed_paper(
                workspace,
                catalog_candidates=[],
                external_resources=[
                    {
                        "id": "resource-url-csv",
                        "kind": "external_catalog_repository",
                        "url": "https://example.test/catalog.csv",
                    }
                ],
            )

            with patch("high_velocity_lit.catalog_extraction.requests.get", return_value=FakeResponse(b"name,vel\nA,700\n", url="https://example.test/catalog.csv")) as fake_get:
                extract_catalog_tables(
                    literature_dir=literature_dir,
                    arxiv_id="2603.00001",
                    workspace=workspace,
                    fetch_external=True,
                )

            fake_get.assert_called_once()
            self.assertEqual(csv_rows(paper_dir / "catalog_tables" / "resource-url-csv.csv"), [["col_001", "col_002"], ["A", "700"]])
            self.assertTrue((paper_dir / "catalog_sources" / "resource-url-csv" / "download-001.csv").exists())
            manifest = json.loads((paper_dir / "catalog_extraction.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["external_resources"][0]["download_attempts"][0]["status"], "success")

    def test_private_url_is_blocked_before_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir, paper_dir = self.write_reviewed_paper(
                workspace,
                catalog_candidates=[],
                external_resources=[
                    {
                        "id": "resource-private-url",
                        "kind": "external_catalog_repository",
                        "url": "http://127.0.0.1/catalog.csv",
                    }
                ],
            )

            with patch("high_velocity_lit.catalog_extraction.requests.get") as fake_get:
                extract_catalog_tables(
                    literature_dir=literature_dir,
                    arxiv_id="2603.00001",
                    workspace=workspace,
                    fetch_external=True,
                )

            fake_get.assert_not_called()
            manifest = json.loads((paper_dir / "catalog_extraction.json").read_text(encoding="utf-8"))
            resource = manifest["external_resources"][0]
            self.assertEqual(resource["status"], "failed")
            self.assertEqual(resource["stopped_reason"], "blocked_url")

    def test_streamed_download_without_content_length_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir, paper_dir = self.write_reviewed_paper(
                workspace,
                catalog_candidates=[],
                external_resources=[
                    {
                        "id": "resource-too-large",
                        "kind": "external_catalog_repository",
                        "url": "https://example.test/catalog.csv",
                    }
                ],
            )

            with patch(
                "high_velocity_lit.catalog_extraction.requests.get",
                return_value=StreamingFakeResponse([b"name,vel\n", b"A,700\n"], url="https://example.test/catalog.csv"),
            ):
                extract_catalog_tables(
                    literature_dir=literature_dir,
                    arxiv_id="2603.00001",
                    workspace=workspace,
                    fetch_external=True,
                    max_external_bytes=8,
                )

            manifest = json.loads((paper_dir / "catalog_extraction.json").read_text(encoding="utf-8"))
            resource = manifest["external_resources"][0]
            self.assertEqual(resource["status"], "failed")
            self.assertEqual(resource["stopped_reason"], "download_too_large")
            self.assertFalse((paper_dir / "catalog_tables" / "resource-too-large.csv").exists())

    def test_redirect_to_private_url_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir, paper_dir = self.write_reviewed_paper(
                workspace,
                catalog_candidates=[],
                external_resources=[
                    {
                        "id": "resource-redirect",
                        "kind": "external_catalog_repository",
                        "url": "https://example.test/catalog.csv",
                    }
                ],
            )

            with patch(
                "high_velocity_lit.catalog_extraction.requests.get",
                return_value=FakeResponse(
                    b"",
                    url="https://example.test/catalog.csv",
                    status_code=302,
                    headers={"location": "http://127.0.0.1/catalog.csv"},
                ),
            ) as fake_get:
                extract_catalog_tables(
                    literature_dir=literature_dir,
                    arxiv_id="2603.00001",
                    workspace=workspace,
                    fetch_external=True,
                )

            fake_get.assert_called_once()
            manifest = json.loads((paper_dir / "catalog_extraction.json").read_text(encoding="utf-8"))
            resource = manifest["external_resources"][0]
            self.assertEqual(resource["status"], "failed")
            self.assertEqual(resource["stopped_reason"], "blocked_url")
            self.assertIn("blocked redirect URL", resource["error"])

    def test_html_landing_does_not_use_rules_when_agent_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir, paper_dir = self.write_reviewed_paper(
                workspace,
                catalog_candidates=[],
                external_resources=[
                    {
                        "id": "resource-landing",
                        "kind": "external_catalog_repository",
                        "url": "https://example.test/page",
                    }
                ],
            )

            def fake_get(url: str, **_: object) -> FakeResponse:
                if url.endswith("/page"):
                    return FakeResponse(b'<html><a href="catalog.csv">machine-readable catalog</a></html>', url=url, content_type="text/html")
                return FakeResponse(b"name,vel\nA,700\n", url=url, content_type="text/csv")

            with patch("high_velocity_lit.catalog_extraction.requests.get", side_effect=fake_get) as fake_request:
                extract_catalog_tables(
                    literature_dir=literature_dir,
                    arxiv_id="2603.00001",
                    workspace=workspace,
                    fetch_external=True,
                )

            self.assertEqual(fake_request.call_count, 1)
            manifest = json.loads((paper_dir / "catalog_extraction.json").read_text(encoding="utf-8"))
            resource = manifest["external_resources"][0]
            self.assertEqual(resource["status"], "failed")
            self.assertEqual(resource["stopped_reason"], "agent_locator_disabled")
            self.assertEqual(resource["locator_attempts"][0]["method"], "agent_landing_page_locator")
            self.assertEqual(resource["locator_attempts"][0]["status"], "skipped")
            self.assertFalse((paper_dir / "catalog_tables" / "resource-landing.csv").exists())

    def test_agent_locator_always_chooses_even_when_rules_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir, paper_dir = self.write_reviewed_paper(
                workspace,
                catalog_candidates=[],
                external_resources=[
                    {
                        "id": "resource-agent-always",
                        "kind": "external_catalog_repository",
                        "url": "https://example.test/page",
                    }
                ],
            )

            def fake_get(url: str, **_: object) -> FakeResponse:
                if url.endswith("/page"):
                    return FakeResponse(b'<html><a href="catalog.csv">machine-readable catalog</a></html>', url=url, content_type="text/html")
                return FakeResponse(b"name,vel\nA,700\n", url=url, content_type="text/csv")

            locator = FakeAgentLocator(["link-001"])
            with patch("high_velocity_lit.catalog_extraction.requests.get", side_effect=fake_get) as fake_request:
                extract_catalog_tables(
                    literature_dir=literature_dir,
                    arxiv_id="2603.00001",
                    workspace=workspace,
                    fetch_external=True,
                    agent_locator_mode=AGENT_LOCATOR_ALWAYS,
                    agent_locator=locator,
                )

            self.assertEqual(fake_request.call_count, 2)
            self.assertEqual(csv_rows(paper_dir / "catalog_tables" / "resource-agent-always.csv"), [["col_001", "col_002"], ["A", "700"]])
            manifest = json.loads((paper_dir / "catalog_extraction.json").read_text(encoding="utf-8"))
            locator_attempts = manifest["external_resources"][0]["locator_attempts"]
            self.assertEqual([attempt["method"] for attempt in locator_attempts], ["agent_landing_page_locator"])
            self.assertEqual(locator_attempts[0]["candidate_count"], 1)

    def test_agent_locator_selects_opaque_landing_link(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir, paper_dir = self.write_reviewed_paper(
                workspace,
                catalog_candidates=[],
                external_resources=[
                    {
                        "id": "resource-agent",
                        "kind": "external_catalog_repository",
                        "url": "https://example.test/page",
                        "meaning": "Machine-readable HVS table.",
                    }
                ],
            )

            def fake_get(url: str, **_: object) -> FakeResponse:
                if url.endswith("/page"):
                    return FakeResponse(b'<html><a href="/download?id=1">Download</a></html>', url=url, content_type="text/html")
                return FakeResponse(b"name,vel\nA,700\n", url=url, content_type="text/csv")

            locator = FakeAgentLocator(["link-001"])
            with patch("high_velocity_lit.catalog_extraction.requests.get", side_effect=fake_get) as fake_request:
                extract_catalog_tables(
                    literature_dir=literature_dir,
                    arxiv_id="2603.00001",
                    workspace=workspace,
                    fetch_external=True,
                    agent_locator_mode=AGENT_LOCATOR_ALWAYS,
                    agent_locator=locator,
                )

            self.assertEqual(fake_request.call_count, 2)
            self.assertEqual(csv_rows(paper_dir / "catalog_tables" / "resource-agent.csv"), [["col_001", "col_002"], ["A", "700"]])
            manifest = json.loads((paper_dir / "catalog_extraction.json").read_text(encoding="utf-8"))
            locator_attempts = manifest["external_resources"][0]["locator_attempts"]
            self.assertEqual([attempt["method"] for attempt in locator_attempts], ["agent_landing_page_locator"])
            self.assertEqual(locator_attempts[0]["candidate_count"], 1)
            self.assertEqual(locator_attempts[0]["selected_count"], 1)
            self.assertTrue((paper_dir / "catalog_sources" / "resource-agent" / "agent_locator_context.json").exists())
            self.assertEqual(locator.contexts[0]["resource"]["meaning"], "Machine-readable HVS table.")  # type: ignore[index]

    def test_agent_locator_cannot_download_invented_candidate_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir, paper_dir = self.write_reviewed_paper(
                workspace,
                catalog_candidates=[],
                external_resources=[
                    {
                        "id": "resource-agent-invalid",
                        "kind": "external_catalog_repository",
                        "url": "https://example.test/page",
                    }
                ],
            )

            with patch(
                "high_velocity_lit.catalog_extraction.requests.get",
                return_value=FakeResponse(b'<html><a href="/download?id=1">Download</a></html>', url="https://example.test/page", content_type="text/html"),
            ) as fake_request:
                extract_catalog_tables(
                    literature_dir=literature_dir,
                    arxiv_id="2603.00001",
                    workspace=workspace,
                    fetch_external=True,
                    agent_locator_mode=AGENT_LOCATOR_ALWAYS,
                    agent_locator=FakeAgentLocator(["link-999"]),
                )

            self.assertEqual(fake_request.call_count, 1)
            manifest = json.loads((paper_dir / "catalog_extraction.json").read_text(encoding="utf-8"))
            resource = manifest["external_resources"][0]
            self.assertEqual(resource["status"], "failed")
            self.assertEqual(resource["stopped_reason"], "agent_invalid_candidate")
            self.assertFalse((paper_dir / "catalog_tables" / "resource-agent-invalid.csv").exists())

    def test_unavailable_agent_first_locator_logs_missing_key_without_rule_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir, paper_dir = self.write_reviewed_paper(
                workspace,
                catalog_candidates=[],
                external_resources=[
                    {
                        "id": "resource-agent-missing-key",
                        "kind": "external_catalog_repository",
                        "url": "https://example.test/page",
                    }
                ],
            )

            locator = UnavailableExternalPageLocator(
                stopped_reason="missing_api_key",
                error="agent locator enabled but no LLM API key is configured",
            )
            with patch(
                "high_velocity_lit.catalog_extraction.requests.get",
                return_value=FakeResponse(b'<html><a href="catalog.csv">machine-readable catalog</a></html>', url="https://example.test/page", content_type="text/html"),
            ) as fake_request:
                extract_catalog_tables(
                    literature_dir=literature_dir,
                    arxiv_id="2603.00001",
                    workspace=workspace,
                    fetch_external=True,
                    agent_locator_mode=AGENT_LOCATOR_ALWAYS,
                    agent_locator=locator,
                )

            self.assertEqual(fake_request.call_count, 1)
            manifest = json.loads((paper_dir / "catalog_extraction.json").read_text(encoding="utf-8"))
            resource = manifest["external_resources"][0]
            self.assertEqual(resource["status"], "failed")
            self.assertEqual(resource["stopped_reason"], "missing_api_key")
            self.assertIn("no LLM API key", resource["error"])
            self.assertEqual([attempt["method"] for attempt in resource["locator_attempts"]], ["agent_landing_page_locator"])
            self.assertEqual(resource["locator_attempts"][0]["stopped_reason"], "missing_api_key")
            self.assertIn("no LLM API key", resource["locator_attempts"][0]["error"])
            self.assertTrue((paper_dir / "catalog_sources" / "resource-agent-missing-key" / "agent_locator_response.json").exists())

    def test_agent_locator_connection_error_is_logged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir, paper_dir = self.write_reviewed_paper(
                workspace,
                catalog_candidates=[],
                external_resources=[
                    {
                        "id": "resource-agent-error",
                        "kind": "external_catalog_repository",
                        "url": "https://example.test/page",
                    }
                ],
            )

            with patch(
                "high_velocity_lit.catalog_extraction.requests.get",
                return_value=FakeResponse(b'<html><a href="/download?id=1">Download</a></html>', url="https://example.test/page", content_type="text/html"),
            ):
                extract_catalog_tables(
                    literature_dir=literature_dir,
                    arxiv_id="2603.00001",
                    workspace=workspace,
                    fetch_external=True,
                    agent_locator_mode=AGENT_LOCATOR_ALWAYS,
                    agent_locator=FailingAgentLocator(),
                )

            manifest = json.loads((paper_dir / "catalog_extraction.json").read_text(encoding="utf-8"))
            resource = manifest["external_resources"][0]
            self.assertEqual(resource["status"], "failed")
            self.assertEqual(resource["stopped_reason"], "agent_error")
            self.assertIn("connection refused", resource["error"])
            self.assertEqual(resource["locator_attempts"][0]["stopped_reason"], "agent_error")

    def test_ads_cached_page_agent_downloads_catalog_link(self) -> None:
        ads_html = """
<div class="resources__data__list">
  <div class="resources__header__title">data products</div>
  <div class="resources__content">
    <a href="https://example.test/catalog.csv">Catalog CSV</a>
    <a href="/link_gateway/test/SIMBAD">SIMBAD (2)</a>
  </div>
</div>
"""
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir, paper_dir = self.write_reviewed_paper(
                workspace,
                catalog_candidates=[],
                ads_html=ads_html,
                external_resources=[
                    {
                        "id": "resource-ads",
                        "kind": "external_catalog_repository",
                        "url": "",
                    }
                ],
            )

            locator = FakeAgentLocator(["link-001"])
            with patch("high_velocity_lit.catalog_extraction.requests.get", return_value=FakeResponse(b"name,vel\nA,700\n", url="https://example.test/catalog.csv")):
                extract_catalog_tables(
                    literature_dir=literature_dir,
                    arxiv_id="2603.00001",
                    workspace=workspace,
                    fetch_external=True,
                    agent_locator_mode=AGENT_LOCATOR_ALWAYS,
                    agent_locator=locator,
                )

            self.assertEqual(csv_rows(paper_dir / "catalog_tables" / "resource-ads.csv"), [["col_001", "col_002"], ["A", "700"]])
            manifest = json.loads((paper_dir / "catalog_extraction.json").read_text(encoding="utf-8"))
            locator_attempts = manifest["external_resources"][0]["locator_attempts"]
            self.assertEqual([attempt["method"] for attempt in locator_attempts], ["ads_cached_page", "agent_ads_page_locator"])
            self.assertEqual(locator_attempts[1]["selected_count"], 1)
            self.assertEqual(locator.contexts[0]["link_candidates"][0]["url"], "https://example.test/catalog.csv")

    def test_ads_page_stops_without_agent_when_locator_disabled(self) -> None:
        ads_html = """
<div class="resources__data__list">
  <div class="resources__header__title">data products</div>
  <div class="resources__content">
    <a href="/link_gateway/test/SIMBAD">SIMBAD (2)</a>
    <a href="/link_gateway/test/ESO">ESO (1)</a>
  </div>
</div>
"""
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir, paper_dir = self.write_reviewed_paper(
                workspace,
                catalog_candidates=[],
                ads_html=ads_html,
                external_resources=[{"id": "resource-ads-empty", "kind": "external_catalog_repository"}],
            )

            with patch("high_velocity_lit.catalog_extraction.requests.get") as fake_get:
                extract_catalog_tables(
                    literature_dir=literature_dir,
                    arxiv_id="2603.00001",
                    workspace=workspace,
                    fetch_external=True,
                )

            fake_get.assert_not_called()
            manifest = json.loads((paper_dir / "catalog_extraction.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["external_resources"][0]["status"], "failed")
            self.assertEqual(manifest["external_resources"][0]["stopped_reason"], "agent_locator_disabled")
            self.assertEqual(manifest["external_resources"][0]["locator_attempts"][1]["method"], "agent_ads_page_locator")
            self.assertFalse((paper_dir / "catalog_tables" / "resource-ads-empty.csv").exists())

    def test_missing_external_locator_records_bounded_stop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir, paper_dir = self.write_reviewed_paper(
                workspace,
                catalog_candidates=[],
                external_resources=[{"id": "resource-missing", "kind": "external_catalog_repository"}],
            )

            extract_catalog_tables(
                literature_dir=literature_dir,
                arxiv_id="2603.00001",
                workspace=workspace,
                fetch_external=False,
            )

            manifest = json.loads((paper_dir / "catalog_extraction.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["external_resources"][0]["status"], "skipped")
            self.assertEqual(manifest["external_resources"][0]["stopped_reason"], "network_disabled")

    def test_all_reviewed_parallel_jobs_preserve_result_order(self) -> None:
        def fake_summary() -> dict[str, int]:
            return {
                "candidate_count": 1,
                "resource_count": 0,
                "work_count": 1,
                "table_count": 1,
                "success_count": 1,
                "failed_count": 0,
                "deferred_count": 0,
                "external_success_count": 0,
                "external_failed_count": 0,
                "external_skipped_count": 0,
                "external_deferred_count": 0,
            }

        def fake_extract(**kwargs: object) -> dict[str, object]:
            arxiv_id = str(kwargs["arxiv_id"])
            if arxiv_id == "2603.00001":
                time.sleep(0.02)
            return {"dry_run": False, "arxiv_id": arxiv_id, "summary": fake_summary()}

        with tempfile.TemporaryDirectory() as tmp:
            literature_dir = Path(tmp) / "literature"
            literature_dir.mkdir()
            with (
                patch("high_velocity_lit.catalog_extraction.reviewed_papers_with_catalogs", return_value=["2603.00001", "2603.00002"]),
                patch("high_velocity_lit.catalog_extraction.extract_catalog_tables", side_effect=fake_extract),
            ):
                payload = extract_all_reviewed_catalog_tables(
                    literature_dir=literature_dir,
                    workspace=Path(tmp),
                    jobs="Auto",
                )

        self.assertEqual(payload["jobs"], 2)
        self.assertEqual(payload["jobs_requested"], "Auto")
        self.assertEqual([result["arxiv_id"] for result in payload["results"]], ["2603.00001", "2603.00002"])
        self.assertEqual(payload["summary"]["success_count"], 2)

    def test_cli_all_reviewed_auto_does_not_fetch_external_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir, paper_dir = self.write_reviewed_paper(
                workspace,
                catalog_candidates=[],
                external_resources=[
                    {
                        "id": "resource-url-csv",
                        "kind": "external_catalog_repository",
                        "url": "https://example.test/catalog.csv",
                    }
                ],
            )

            with patch.object(
                sys,
                "argv",
                [
                    "extract_catalog_tables.py",
                    "--all-reviewed",
                    "--literature-dir",
                    str(literature_dir),
                    "--dry-run",
                    "True",
                ],
            ):
                with patch("high_velocity_lit.catalog_extraction.requests.get") as fake_get:
                    with patch("builtins.print") as fake_print:
                        exit_code = extract_cli.main()

            self.assertEqual(exit_code, 0)
            fake_get.assert_not_called()
            payload = json.loads(fake_print.call_args.args[0])
            self.assertTrue(payload["dry_run"])
            self.assertEqual(payload["summary"]["external_skipped_count"], 1)
            self.assertFalse((paper_dir / "catalog_extraction.json").exists())

    def test_rerun_preserves_reviewed_usage_and_column_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir, paper_dir = self.write_reviewed_paper(
                workspace,
                catalog_candidates=[],
                external_resources=[
                    {
                        "id": "resource-local-csv",
                        "kind": "local_machine_readable_file",
                        "local_path": "literature/2603.00001/arxiv_source/data.csv",
                    }
                ],
            )
            (paper_dir / "arxiv_source" / "data.csv").write_text("name,vel\nA,700\n", encoding="utf-8")
            extract_catalog_tables(
                literature_dir=literature_dir,
                arxiv_id="2603.00001",
                workspace=workspace,
                fetch_external=False,
            )
            manifest_path = paper_dir / "catalog_extraction.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["tables"][0]["usage"]["semantic_status"] = "reviewed"
            manifest["tables"][0]["usage"]["row_entity"] = "candidate star"
            manifest["tables"][0]["columns"][1]["semantic_status"] = "reviewed"
            manifest["tables"][0]["columns"][1]["physical_quantity"] = "velocity"
            manifest["tables"][0]["columns"][1]["meaning"] = "Candidate velocity."
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

            extract_catalog_tables(
                literature_dir=literature_dir,
                arxiv_id="2603.00001",
                workspace=workspace,
                fetch_external=False,
                overwrite=True,
            )

            updated = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(updated["tables"][0]["usage"]["row_entity"], "candidate star")
            self.assertEqual(updated["tables"][0]["columns"][1]["physical_quantity"], "velocity")
            self.assertEqual(updated["tables"][0]["columns"][1]["meaning"], "Candidate velocity.")

    def test_rerun_does_not_preserve_semantics_when_header_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir, paper_dir = self.write_reviewed_paper(
                workspace,
                catalog_candidates=[],
                external_resources=[
                    {
                        "id": "resource-local-csv",
                        "kind": "local_machine_readable_file",
                        "local_path": "literature/2603.00001/arxiv_source/data.csv",
                    }
                ],
            )
            data_path = paper_dir / "arxiv_source" / "data.csv"
            data_path.write_text("name,vel\nA,700\n", encoding="utf-8")
            extract_catalog_tables(
                literature_dir=literature_dir,
                arxiv_id="2603.00001",
                workspace=workspace,
                fetch_external=False,
            )
            manifest_path = paper_dir / "catalog_extraction.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["tables"][0]["usage"]["semantic_status"] = "reviewed"
            manifest["tables"][0]["usage"]["row_entity"] = "candidate star"
            manifest["tables"][0]["columns"][1]["semantic_status"] = "reviewed"
            manifest["tables"][0]["columns"][1]["physical_quantity"] = "velocity"
            manifest["tables"][0]["columns"][1]["meaning"] = "Candidate velocity."
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

            data_path.write_text("name,speed\nA,700\n", encoding="utf-8")
            extract_catalog_tables(
                literature_dir=literature_dir,
                arxiv_id="2603.00001",
                workspace=workspace,
                fetch_external=False,
                overwrite=True,
            )

            updated = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(updated["tables"][0]["columns"][1]["original_name"], "speed")
            self.assertEqual(updated["tables"][0]["columns"][1]["semantic_status"], "needs_agent_review")
            self.assertEqual(updated["tables"][0]["columns"][1]["physical_quantity"], "")
            self.assertEqual(updated["tables"][0]["usage"]["semantic_status"], "needs_agent_review")


if __name__ == "__main__":
    unittest.main()
