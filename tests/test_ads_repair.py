from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from high_velocity_lit.ads_repair import repair_ads_metadata  # noqa: E402

SCRIPT = ROOT / "scripts" / "repair_ads_metadata.py"
SPEC = importlib.util.spec_from_file_location("repair_ads_metadata_cli", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
repair_ads_cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repair_ads_cli)


class FakeResponse:
    def __init__(
        self,
        *,
        url: str,
        status_code: int = 200,
        content: bytes = b"",
        headers: dict[str, str] | None = None,
        json_payload: dict[str, object] | None = None,
    ) -> None:
        self.url = url
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.json_payload = json_payload

    def iter_content(self, chunk_size: int = 1024 * 1024) -> object:
        for index in range(0, len(self.content), chunk_size):
            yield self.content[index : index + chunk_size]

    def close(self) -> None:
        return None

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            response = requests.Response()
            response.status_code = self.status_code
            response.url = self.url
            response.headers.update(self.headers)
            raise requests.HTTPError(f"{self.status_code} error", response=response)

    def json(self) -> dict[str, object]:
        if self.json_payload is not None:
            return self.json_payload
        return json.loads(self.content.decode("utf-8"))


class FakeSession:
    def __init__(self, responses: dict[str, FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[str] = []
        self.headers: dict[str, str] = {}

    def get(
        self,
        url: str,
        timeout: int,
        allow_redirects: bool = True,
        headers: dict[str, str] | None = None,
        stream: bool = False,
        params: dict[str, str] | None = None,
    ) -> FakeResponse:
        del timeout, allow_redirects, headers, stream, params
        self.calls.append(url)
        if url not in self.responses:
            raise requests.RequestException(f"missing fake response for {url}")
        return self.responses[url]


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ads_html(bibcode: str = "2026MNRAS.123..456H") -> str:
    return f"""
    <html>
      <head><meta name="citation_title" content="Repair target" /></head>
      <body>
        <dt>Bibcode:</dt><dd>{bibcode}</dd>
        <a href="/abs/{bibcode}/exportcitation">Export Citation</a>
      </body>
    </html>
    """


def ads_api_response(bibcode: str = "2026MNRAS.123..456H") -> FakeResponse:
    return FakeResponse(
        url="https://api.adsabs.harvard.edu/v1/search/query",
        headers={"content-type": "application/json"},
        json_payload={
            "response": {
                "docs": [
                    {
                        "bibcode": bibcode,
                        "title": ["API title"],
                        "identifier": ["arXiv:2603.00001"],
                        "author": ["Author, A."],
                        "year": "2026",
                    }
                ]
            }
        },
    )


class AdsRepairTest(unittest.TestCase):
    def test_repairs_ads_metadata_from_api_and_only_paper_level_hvs_bibcode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            literature_dir = Path(tmp) / "literature"
            paper_dir = literature_dir / "2603.00001"
            write_json(
                paper_dir / "audit.json",
                {
                    "arxiv_id": "2603.00001",
                    "title": "Repair target",
                    "ads_metadata": {},
                    "ads_abstract": {"success": False, "error": "skipped"},
                },
            )
            write_json(
                paper_dir / "literature_hvs_candidates.json",
                {
                    "paper": {"arxiv_id": "2603.00001", "bibcode": None},
                    "candidates": [
                        {
                            "candidate_origin": {
                                "citation": {"bibcode": "1999ApJ...111..222R"},
                            }
                        }
                    ],
                },
            )
            session = FakeSession(
                {
                    "https://api.adsabs.harvard.edu/v1/search/query": ads_api_response()
                }
            )

            payload = repair_ads_metadata(literature_dir=literature_dir, session=session, ads_token="secret")

            self.assertEqual(payload["summary"]["fixed_count"], 1)
            audit = json.loads((paper_dir / "audit.json").read_text(encoding="utf-8"))
            self.assertTrue(audit["ads_api"]["success"])
            self.assertEqual(audit["ads_api"]["local_path"], "literature/2603.00001/ads_metadata.json")
            self.assertEqual(audit["ads_metadata"]["ads_bibcode"], "2026MNRAS.123..456H")
            self.assertEqual(audit["ads_metadata"]["ads_bibcode_source"], "ads_api")
            self.assertTrue((paper_dir / "ads_metadata.json").exists())
            hvs = json.loads((paper_dir / "literature_hvs_candidates.json").read_text(encoding="utf-8"))
            self.assertEqual(hvs["paper"]["bibcode"], "2026MNRAS.123..456H")
            self.assertEqual(hvs["candidates"][0]["candidate_origin"]["citation"]["bibcode"], "1999ApJ...111..222R")

    def test_existing_ads_html_is_not_refetched_when_using_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            literature_dir = Path(tmp) / "literature"
            paper_dir = literature_dir / "2603.00002"
            paper_dir.mkdir(parents=True)
            (paper_dir / "ads_abstract.html").write_text("<html>old page without bibcode</html>", encoding="utf-8")
            write_json(
                paper_dir / "audit.json",
                {
                    "arxiv_id": "2603.00002",
                    "ads_metadata": {},
                    "ads_abstract": {
                        "url": "https://ui.adsabs.harvard.edu/abs/arXiv:2603.00002/abstract",
                        "success": True,
                        "local_path": "ads_abstract.html",
                    },
                },
            )
            session = FakeSession(
                {
                    "https://api.adsabs.harvard.edu/v1/search/query": ads_api_response("2026ApJ...999..001F")
                }
            )

            payload = repair_ads_metadata(literature_dir=literature_dir, session=session, ads_token="secret")

            self.assertEqual(session.calls, ["https://api.adsabs.harvard.edu/v1/search/query"])
            self.assertEqual(payload["summary"]["fixed_count"], 1)
            self.assertNotIn("2026ApJ...999..001F", (paper_dir / "ads_abstract.html").read_text(encoding="utf-8"))

    def test_dry_run_reports_without_writing_or_fetching(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            literature_dir = Path(tmp) / "literature"
            paper_dir = literature_dir / "2603.00003"
            ads_url = "https://ui.adsabs.harvard.edu/abs/arXiv:2603.00003/abstract"
            audit_payload = {
                "arxiv_id": "2603.00003",
                "ads_metadata": {},
                "ads_abstract": {"url": ads_url, "success": False, "error": "old failure"},
            }
            write_json(paper_dir / "audit.json", audit_payload)
            session = FakeSession({})

            payload = repair_ads_metadata(literature_dir=literature_dir, session=session, dry_run=True)

            self.assertEqual(payload["summary"]["would_change_count"], 1)
            self.assertEqual(session.calls, [])
            self.assertEqual(json.loads((paper_dir / "audit.json").read_text(encoding="utf-8")), audit_payload)

    def test_api_failure_is_reported_without_clearing_existing_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            literature_dir = Path(tmp) / "literature"
            paper_dir = literature_dir / "2603.00005"
            write_json(
                paper_dir / "audit.json",
                {
                    "arxiv_id": "2603.00005",
                    "ads_metadata": {"citation_title": "Existing title"},
                    "ads_abstract": {"success": False, "error": "old failure"},
                },
            )
            session = FakeSession({})

            payload = repair_ads_metadata(literature_dir=literature_dir, session=session, ads_token="secret")

            self.assertEqual(payload["summary"]["failed_count"], 1)
            audit = json.loads((paper_dir / "audit.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["ads_metadata"]["citation_title"], "Existing title")
            self.assertFalse(audit["ads_api"]["success"])
            self.assertIn("missing fake response", audit["ads_api"]["error"])

    def test_missing_ads_token_leaves_bibcodes_blank_and_reports_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir = workspace / "literature"
            paper_dir = literature_dir / "2603.00006"
            write_json(
                workspace / "notes" / "2026" / "2026-03" / "2026-03.json",
                {
                    "papers": [
                        {
                            "arxiv_id": "2603.00006",
                            "published_at": "2026-03-15T00:00:00Z",
                            "authors": [{"name": "N. Azatyan"}],
                        }
                    ]
                },
            )
            write_json(
                paper_dir / "audit.json",
                {
                    "arxiv_id": "2603.00006",
                    "month": "2026-03",
                    "source_note_json": "notes/2026/2026-03/2026-03.json",
                    "ads_metadata": {},
                    "ads_abstract": {"success": False},
                },
            )
            write_json(paper_dir / "literature_hvs_candidates.json", {"paper": {"bibcode": None}})
            session = FakeSession({})

            payload = repair_ads_metadata(literature_dir=literature_dir, session=session)

            self.assertEqual(payload["summary"]["failed_count"], 1)
            audit = json.loads((paper_dir / "audit.json").read_text(encoding="utf-8"))
            self.assertFalse(audit["ads_api"]["success"])
            self.assertNotIn("ads_bibcode", audit["ads_metadata"])
            hvs = json.loads((paper_dir / "literature_hvs_candidates.json").read_text(encoding="utf-8"))
            self.assertIsNone(hvs["paper"]["bibcode"])

    def test_force_refreshes_existing_ads_metadata_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            literature_dir = Path(tmp) / "literature"
            paper_dir = literature_dir / "2603.00008"
            write_json(
                paper_dir / "audit.json",
                {
                    "arxiv_id": "2603.00008",
                    "ads_api": {
                        "success": True,
                        "local_path": "literature/2603.00008/ads_metadata.json",
                    },
                    "ads_metadata": {
                        "ads_bibcode": "2026OLD......001A",
                        "ads_bibcode_source": "ads_api",
                    },
                },
            )
            write_json(paper_dir / "ads_metadata.json", {"response": {"docs": [{"bibcode": "2026OLD......001A"}]}})
            session = FakeSession(
                {
                    "https://api.adsabs.harvard.edu/v1/search/query": ads_api_response("2026NEW......002A")
                }
            )

            payload = repair_ads_metadata(
                literature_dir=literature_dir,
                session=session,
                ads_token="secret",
                force=True,
            )

            self.assertEqual(payload["summary"]["fixed_count"], 1)
            self.assertEqual(payload["summary"]["ads_retry_needed_count"], 1)
            audit = json.loads((paper_dir / "audit.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["ads_metadata"]["ads_bibcode"], "2026NEW......002A")
            metadata_payload = json.loads((paper_dir / "ads_metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata_payload["response"]["docs"][0]["bibcode"], "2026NEW......002A")

    def test_ads_api_fills_bibcode_without_page_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            literature_dir = Path(tmp) / "literature"
            paper_dir = literature_dir / "2603.00007"
            api_url = "https://api.adsabs.harvard.edu/v1/search/query"
            write_json(
                paper_dir / "audit.json",
                {
                    "arxiv_id": "2603.00007",
                    "ads_metadata": {},
                    "ads_abstract": {"success": False},
                },
            )
            write_json(paper_dir / "literature_hvs_candidates.json", {"paper": {"bibcode": None}})
            session = FakeSession(
                {
                    api_url: FakeResponse(
                        url=api_url,
                        headers={"content-type": "application/json"},
                        json_payload={
                            "response": {
                                "docs": [
                                    {
                                        "bibcode": "2026MNRAS.123..456A",
                                        "title": ["API title"],
                                        "identifier": ["arXiv:2603.00007"],
                                        "author": ["Author, A."],
                                        "year": "2026",
                                    }
                                ]
                            }
                        },
                    ),
                }
            )

            payload = repair_ads_metadata(literature_dir=literature_dir, session=session, ads_token="secret")

            self.assertEqual(payload["summary"]["fixed_count"], 1)
            self.assertEqual(payload["summary"]["ads_api_success_count"], 1)
            audit = json.loads((paper_dir / "audit.json").read_text(encoding="utf-8"))
            self.assertTrue(audit["ads_api"]["success"])
            self.assertEqual(audit["ads_metadata"]["ads_bibcode"], "2026MNRAS.123..456A")
            self.assertEqual(audit["ads_metadata"]["ads_bibcode_source"], "ads_api")
            hvs = json.loads((paper_dir / "literature_hvs_candidates.json").read_text(encoding="utf-8"))
            self.assertEqual(hvs["paper"]["bibcode"], "2026MNRAS.123..456A")

    def test_cli_dry_run_reports_selected_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            literature_dir = Path(tmp) / "literature"
            write_json(
                literature_dir / "2603.00004" / "audit.json",
                {
                    "arxiv_id": "2603.00004",
                    "ads_metadata": {},
                    "ads_abstract": {"success": False},
                },
            )

            with patch.object(
                sys,
                "argv",
                [
                    "repair_ads_metadata.py",
                    "--literature-dir",
                    str(literature_dir),
                    "--dry-run",
                    "True",
                ],
            ):
                with patch("builtins.print") as fake_print:
                    exit_code = repair_ads_cli.main()

            self.assertEqual(exit_code, 0)
            payload = json.loads(fake_print.call_args.args[0])
            self.assertEqual(payload["summary"]["selected_count"], 1)
            self.assertEqual(payload["summary"]["would_change_count"], 1)


if __name__ == "__main__":
    unittest.main()
