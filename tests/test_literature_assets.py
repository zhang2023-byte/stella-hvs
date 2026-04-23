from __future__ import annotations

import importlib.util
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from high_velocity_lit.literature_assets import (  # noqa: E402
    SelectedPaper,
    archive_paper,
    parse_ads_metadata,
    resolve_folder,
)

SCRIPT = ROOT / "scripts" / "pull_literature_assets.py"
SPEC = importlib.util.spec_from_file_location("pull_literature_assets", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
pull_assets_cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pull_assets_cli)


class FakeResponse:
    def __init__(
        self,
        *,
        url: str,
        status_code: int = 200,
        content: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.url = url
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.text = content.decode("utf-8", errors="replace")
        self.ok = status_code < 400

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            response = requests.Response()
            response.status_code = self.status_code
            response.url = self.url
            response.headers.update(self.headers)
            raise requests.HTTPError(f"{self.status_code} error", response=response)


class FakeSession:
    def __init__(self, responses: dict[str, FakeResponse]) -> None:
        self.responses = responses
        self.headers: dict[str, str] = {}

    def get(self, url: str, timeout: int, allow_redirects: bool = True, headers: dict[str, str] | None = None) -> FakeResponse:
        del timeout, allow_redirects, headers
        if url not in self.responses:
            raise requests.RequestException(f"missing fake response for {url}")
        return self.responses[url]


def sample_month_record() -> dict[str, object]:
    return {
        "month": "2026-03",
        "papers": [
            {
                "arxiv_id": "2603.00001",
                "title": "A catalog of hypervelocity star candidates",
                "authors": ["Ana Antoja", "B. Author"],
                "author_names": "Ana Antoja, B. Author",
                "published_at": "2026-03-11T10:09:11Z",
                "links": {
                    "abs": "https://arxiv.org/abs/2603.00001",
                    "pdf": "https://arxiv.org/pdf/2603.00001",
                },
                "catalog_assessment": {"has_observational_catalog": True},
            },
            {
                "arxiv_id": "2603.00002",
                "title": "A theory paper",
                "authors": ["Theo Author"],
                "published_at": "2026-03-12T00:00:00Z",
                "links": {
                    "abs": "https://arxiv.org/abs/2603.00002",
                    "pdf": "https://arxiv.org/pdf/2603.00002",
                },
                "catalog_assessment": {"has_observational_catalog": False},
            },
        ],
    }


def fake_tar_gz_bytes() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        data = b"sample tex content"
        info = tarfile.TarInfo(name="main.tex")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class LiteratureAssetsTest(unittest.TestCase):
    def test_parse_ads_metadata_extracts_expected_fields(self) -> None:
        html = """
        <html>
          <head>
            <meta name="citation_authors" content="Ana Antoja" />
            <meta name="citation_title" content="All-sky proper motion catalog" />
            <meta name="citation_date" content="2020" />
          </head>
          <body>
            <dt>Bibcode:</dt><dd><a href="/abs/2020A%26A...123..456A/abstract">2020A&amp;A...123..456A</a></dd>
            <a href="/abs/2020A%26A...123..456A/exportcitation">Export Citation</a>
            <div class="resources__full__list">
              <div class="resources__header__title">full text sources</div>
              <a href="/link_gateway/2020A%26A...123..456A/PUB_PDF"></a>
            </div>
            <div class="resources__data__list">
              <div class="resources__header__title">data products</div>
              <a href="/link_gateway/2020A%26A...123..456A/SIMBAD">SIMBAD (17)</a>
            </div>
          </body>
        </html>
        """
        metadata = parse_ads_metadata(html)

        self.assertEqual(metadata["citation_authors"], "Ana Antoja")
        self.assertEqual(metadata["ads_bibcode"], "2020A&A...123..456A")
        self.assertTrue(metadata["ads_export_citation_url"].endswith("/exportcitation"))

    def test_resolve_folder_migrates_legacy_citekey_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            literature_dir = Path(tmp) / "literature"
            legacy = literature_dir / "2603.00001+antojaAllSky2020"
            legacy.mkdir(parents=True)
            (legacy / "audit.json").write_text("{}", encoding="utf-8")

            folder = resolve_folder(literature_dir, "2603.00001")

            self.assertEqual(folder, literature_dir / "2603.00001")
            self.assertTrue(folder.exists())
            self.assertFalse(legacy.exists())

    def test_archive_paper_writes_assets_audit_and_extracts_source(self) -> None:
        arxiv_html = """
        <html><body><a href="https://ui.adsabs.harvard.edu/abs/arXiv:2603.00001">NASA ADS</a></body></html>
        """
        ads_html = """
        <html>
          <head>
            <meta name="citation_authors" content="Ana Antoja" />
            <meta name="citation_title" content="All-sky proper motion catalog for runaway stars" />
            <meta name="citation_date" content="2020-01-01" />
          </head>
          <body>
            <dt>Bibcode:</dt><dd><a href="/abs/2020A%26A...123..456A/abstract">2020A&amp;A...123..456A</a></dd>
            <a href="/abs/2020A%26A...123..456A/exportcitation">Export Citation</a>
            <div class="resources__full__list">
              <div class="resources__header__title">full text sources</div>
              <a href="/link_gateway/2020A%26A...123..456A/PUB_PDF"></a>
            </div>
            <div class="resources__data__list">
              <div class="resources__header__title">data products</div>
              <a href="/link_gateway/2020A%26A...123..456A/SIMBAD">SIMBAD (17)</a>
            </div>
          </body>
        </html>
        """
        pdf_bytes = b"%PDF-1.7 fake"
        responses = {
            "https://arxiv.org/abs/2603.00001": FakeResponse(
                url="https://arxiv.org/abs/2603.00001",
                content=arxiv_html.encode("utf-8"),
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            "https://ui.adsabs.harvard.edu/abs/arXiv:2603.00001": FakeResponse(
                url="https://ui.adsabs.harvard.edu/abs/arXiv:2603.00001/abstract",
                content=ads_html.encode("utf-8"),
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            "https://arxiv.org/pdf/2603.00001": FakeResponse(
                url="https://arxiv.org/pdf/2603.00001",
                content=pdf_bytes,
                headers={"content-type": "application/pdf"},
            ),
            "https://arxiv.org/e-print/2603.00001": FakeResponse(
                url="https://arxiv.org/e-print/2603.00001",
                content=fake_tar_gz_bytes(),
                headers={"content-type": "application/gzip"},
            ),
        }
        selected = SelectedPaper(
            month="2026-03",
            note_json_path=Path("/workspace/notes/2026/2026-03/2026-03.json"),
            paper=sample_month_record()["papers"][0],  # type: ignore[index]
        )

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir = workspace / "literature"
            result = archive_paper(
                selected,
                workspace=workspace,
                literature_dir=literature_dir,
                session=FakeSession(responses),
            )

            folder = literature_dir / "2603.00001"
            self.assertTrue((folder / "arxiv_abs.html").exists())
            self.assertTrue((folder / "arxiv.pdf").exists())
            self.assertTrue((folder / "arxiv_source.tar.gz").exists())
            self.assertTrue((folder / "arxiv_source" / "main.tex").exists())
            self.assertTrue((folder / "ads_abstract.html").exists())
            audit = json.loads((folder / "audit.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["folder_name"], "2603.00001")
            self.assertNotIn("cite_key", audit)
            self.assertTrue(audit["arxiv_pdf"]["success"])
            self.assertTrue(audit["arxiv_source"]["success"])
            self.assertTrue(audit["arxiv_source"]["extracted"])
            self.assertFalse(audit["arxiv_source"]["source_unavailable_on_arxiv"])
            self.assertEqual(audit["arxiv_source"]["source_unavailable_reason"], "")
            self.assertEqual(audit["arxiv_source"]["extract_dir"], "arxiv_source")
            self.assertNotIn("ads_resources", audit)
            self.assertTrue(result["arxiv_source_extracted"])

    def test_archive_paper_marks_source_unavailable_when_arxiv_serves_pdf(self) -> None:
        arxiv_html = """
        <html><body><a href="https://ui.adsabs.harvard.edu/abs/arXiv:2401.10635">NASA ADS</a></body></html>
        """
        ads_html = """
        <html>
          <head>
            <meta name="citation_title" content="No source available" />
          </head>
        </html>
        """
        pdf_bytes = b"%PDF-1.7 fake"
        responses = {
            "https://arxiv.org/abs/2401.10635": FakeResponse(
                url="https://arxiv.org/abs/2401.10635",
                content=arxiv_html.encode("utf-8"),
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            "https://ui.adsabs.harvard.edu/abs/arXiv:2401.10635": FakeResponse(
                url="https://ui.adsabs.harvard.edu/abs/arXiv:2401.10635/abstract",
                content=ads_html.encode("utf-8"),
                headers={"content-type": "text/html; charset=utf-8"},
            ),
            "https://arxiv.org/pdf/2401.10635": FakeResponse(
                url="https://arxiv.org/pdf/2401.10635",
                content=pdf_bytes,
                headers={"content-type": "application/pdf"},
            ),
            "https://arxiv.org/e-print/2401.10635": FakeResponse(
                url="https://arxiv.org/e-print/2401.10635",
                content=pdf_bytes,
                headers={"content-type": "application/pdf"},
            ),
            "https://arxiv.org/src/2401.10635": FakeResponse(
                url="https://arxiv.org/src/2401.10635",
                content=pdf_bytes,
                headers={"content-type": "application/pdf"},
            ),
        }
        selected = SelectedPaper(
            month="2024-01",
            note_json_path=Path("/workspace/notes/2024/2024-01/2024-01.json"),
            paper={
                "arxiv_id": "2401.10635",
                "title": "Seventeen 2 Micron All Sky Survey (2MASS) hypervelocity stars (HVS) from Gaia DR3",
                "links": {
                    "abs": "https://arxiv.org/abs/2401.10635",
                    "pdf": "https://arxiv.org/pdf/2401.10635",
                },
                "catalog_assessment": {"has_observational_catalog": True},
            },
        )

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir = workspace / "literature"
            archive_paper(
                selected,
                workspace=workspace,
                literature_dir=literature_dir,
                session=FakeSession(responses),
            )

            audit = json.loads((literature_dir / "2401.10635" / "audit.json").read_text(encoding="utf-8"))
            self.assertFalse(audit["arxiv_source"]["success"])
            self.assertTrue(audit["arxiv_source"]["source_unavailable_on_arxiv"])
            self.assertEqual(
                audit["arxiv_source"]["source_unavailable_reason"],
                "arXiv served PDF content instead of a source archive",
            )
            self.assertFalse((literature_dir / "2401.10635" / "arxiv_source").exists())

    def test_cli_dry_run_selects_only_data_related_papers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            notes_dir = Path(tmp) / "notes"
            month_dir = notes_dir / "2026" / "2026-03"
            month_dir.mkdir(parents=True)
            (month_dir / "2026-03.json").write_text(
                json.dumps(sample_month_record(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            with patch.object(
                sys,
                "argv",
                [
                    "pull_literature_assets.py",
                    "--on",
                    "2026-03",
                    "--notes-dir",
                    str(notes_dir),
                    "--literature-dir",
                    str(Path(tmp) / "literature"),
                    "--dry-run",
                    "True",
                ],
            ):
                with patch("builtins.print") as fake_print:
                    exit_code = pull_assets_cli.main()

            self.assertEqual(exit_code, 0)
            payload = json.loads(fake_print.call_args.args[0])
            self.assertEqual(payload["summary"]["selected_count"], 1)
            self.assertEqual(payload["selected"][0]["arxiv_id"], "2603.00001")

    def test_cli_arxiv_id_marks_non_data_related_as_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            notes_dir = Path(tmp) / "notes"
            month_dir = notes_dir / "2026" / "2026-03"
            month_dir.mkdir(parents=True)
            (month_dir / "2026-03.json").write_text(
                json.dumps(sample_month_record(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            with patch.object(
                sys,
                "argv",
                [
                    "pull_literature_assets.py",
                    "--arxiv-id",
                    "2603.00002",
                    "--notes-dir",
                    str(notes_dir),
                    "--literature-dir",
                    str(Path(tmp) / "literature"),
                    "--dry-run",
                    "True",
                ],
            ):
                with patch("builtins.print") as fake_print:
                    exit_code = pull_assets_cli.main()

            self.assertEqual(exit_code, 0)
            payload = json.loads(fake_print.call_args.args[0])
            self.assertEqual(payload["summary"]["selected_count"], 0)
            self.assertEqual(payload["skipped"][0]["reason"], "not-data-related")


if __name__ == "__main__":
    unittest.main()
