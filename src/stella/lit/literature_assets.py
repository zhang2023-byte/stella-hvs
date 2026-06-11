"""Local archival of data-related literature assets."""

from __future__ import annotations

import json
import gzip
import re
import shutil
import tarfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .note_paths import iter_month_json_paths
from .network_safety import BlockedURL, require_public_http_url
from .records import has_observational_catalog, paper_url, pdf_url


ASSET_AUDIT_SCHEMA_VERSION = "stella.literature.assets_audit.v0.1"
ADS_BASE_URL = "https://ui.adsabs.harvard.edu"
ADS_API_SEARCH_URL = "https://api.adsabs.harvard.edu/v1/search/query"
DEFAULT_TIMEOUT = 60
DEFAULT_USER_AGENT = "stella-literature-assets/1.0"
MAX_ASSET_BYTES = 100 * 1024 * 1024
REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
ASSET_FILENAMES = {
    "arxiv_abs": "arxiv_abs.html",
    "arxiv_pdf": "arxiv.pdf",
    "ads_metadata": "ads_metadata.json",
}
ADS_API_FIELDS = (
    "bibcode",
    "title",
    "identifier",
    "doi",
    "author",
    "first_author",
    "aff",
    "pub",
    "pubdate",
    "year",
    "volume",
    "page",
    "doctype",
    "abstract",
    "keyword",
    "arxiv_class",
    "citation_count",
    "data",
    "property",
)


@dataclass(frozen=True)
class SelectedPaper:
    month: str
    note_json_path: Path
    paper: dict[str, Any]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def relative_path(path: Path, *, workspace: Path) -> str:
    try:
        return str(path.relative_to(workspace))
    except ValueError:
        return str(path)


def load_data_related_papers(notes_dir: Path) -> dict[str, SelectedPaper]:
    selected: dict[str, SelectedPaper] = {}
    for json_path in iter_month_json_paths(notes_dir):
        record = read_json(json_path)
        month = str(record.get("month") or json_path.stem)
        for paper in record.get("papers") or []:
            if not isinstance(paper, dict):
                continue
            arxiv_id = str(paper.get("arxiv_id") or "").strip()
            if not arxiv_id or not has_observational_catalog(paper):
                continue
            selected[arxiv_id] = SelectedPaper(month=month, note_json_path=json_path, paper=paper)
    return selected


def parse_ads_metadata(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    metadata: dict[str, str] = {}
    for meta in soup.select("meta[name^='citation_']"):
        name = str(meta.get("name") or "").strip()
        content = str(meta.get("content") or "").strip()
        if name and content:
            metadata[name] = content
    bibcode_label = soup.find("dt", string=re.compile(r"Bibcode:"))
    if bibcode_label is not None:
        sibling = bibcode_label.find_next_sibling("dd")
        if sibling is not None:
            metadata["ads_bibcode"] = " ".join(sibling.get_text(" ", strip=True).split())
    export_link = soup.select_one("a[href*='/exportcitation']")
    if export_link is not None and export_link.get("href"):
        metadata["ads_export_citation_url"] = urljoin(ADS_BASE_URL, str(export_link["href"]))
    return metadata


def fetch_ads_api_metadata(
    session: requests.Session,
    *,
    arxiv_id: str,
    token: str,
    timeout: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    result = {
        "url": ADS_API_SEARCH_URL,
        "success": False,
        "status_code": None,
        "content_type": "",
        "final_url": "",
        "error": "",
        "query": f"identifier:{arxiv_id}",
        "fields": list(ADS_API_FIELDS),
        "bibcode": "",
        "local_path": None,
        "skipped_missing_token": False,
    }
    if not token:
        result["error"] = "ADS API token not configured"
        result["skipped_missing_token"] = True
        return result, {}, {}
    try:
        response = session.get(
            ADS_API_SEARCH_URL,
            params={
                "q": f"identifier:{arxiv_id}",
                "fl": ",".join(ADS_API_FIELDS),
                "rows": "1",
            },
            timeout=timeout,
            headers={"Authorization": f"Bearer {token}"},
        )
        result["status_code"] = response.status_code
        result["content_type"] = response.headers.get("content-type", "")
        result["final_url"] = str(response.url)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        response = getattr(exc, "response", None)
        if response is not None:
            result["status_code"] = response.status_code
            result["content_type"] = response.headers.get("content-type", "")
            result["final_url"] = str(response.url)
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result, {}, {}
    except ValueError as exc:
        result["error"] = f"invalid JSON response: {exc}"
        return result, {}, {}

    docs = ((payload.get("response") or {}).get("docs") or []) if isinstance(payload, dict) else []
    if not docs or not isinstance(docs[0], dict):
        result["error"] = "ADS API returned no matching document"
        return result, {}, payload if isinstance(payload, dict) else {}
    doc = docs[0]
    bibcode = str(doc.get("bibcode") or "").strip()
    if not bibcode:
        result["error"] = "ADS API document did not include bibcode"
        return result, {}, payload if isinstance(payload, dict) else {}
    result["success"] = True
    result["bibcode"] = bibcode
    metadata: dict[str, Any] = {
        "ads_bibcode": bibcode,
        "ads_bibcode_source": "ads_api",
    }
    for key in ADS_API_FIELDS:
        if key in doc:
            metadata[f"ads_api_{key}"] = doc[key]
    return result, metadata, payload if isinstance(payload, dict) else {}


def write_ads_api_payload(
    output_dir: Path,
    *,
    payload: dict[str, Any],
    workspace: Path,
) -> str:
    path = output_dir / ASSET_FILENAMES["ads_metadata"]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return relative_path(path, workspace=workspace)


def find_arxiv_ads_url(arxiv_html: str, *, arxiv_id: str) -> str:
    soup = BeautifulSoup(arxiv_html, "html.parser")
    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        text = " ".join(anchor.get_text(" ", strip=True).split()).lower()
        if "adsabs.harvard.edu" in href or "nasa ads" in text:
            return href
    return f"{ADS_BASE_URL}/abs/arXiv:{arxiv_id}/abstract"


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def infer_extension(*, content_type: str, final_url: str, content: bytes) -> str:
    lowered_type = content_type.lower()
    if content.startswith(b"%PDF-"):
        return ".pdf"
    if content.startswith(b"\x1f\x8b"):
        return ".tar.gz"
    if content.startswith(b"ustar") or b"ustar" in content[:512]:
        return ".tar"
    if "gzip" in lowered_type:
        return ".tar.gz"
    if "x-tar" in lowered_type or "tar" in lowered_type:
        return ".tar"
    if "zip" in lowered_type:
        return ".zip"
    suffix = Path(urlparse(final_url).path).suffix
    return suffix or ".bin"


def looks_like_source_package(*, content_type: str, content: bytes) -> bool:
    lowered_type = content_type.lower()
    if content.startswith(b"%PDF-"):
        return False
    if content[:1] == b"<" or "text/html" in lowered_type:
        return False
    if content.startswith(b"\x1f\x8b") or content.startswith(b"PK\x03\x04"):
        return True
    if "gzip" in lowered_type or "zip" in lowered_type or "tar" in lowered_type or "octet-stream" in lowered_type:
        return True
    return False


def basic_asset_result(*, url: str) -> dict[str, Any]:
    return {
        "url": url,
        "success": False,
        "status_code": None,
        "content_type": "",
        "final_url": "",
        "local_path": None,
        "error": "",
        "skipped_existing": False,
        "size_bytes": 0,
    }


def source_unavailable_fields(*, unavailable: bool = False, reason: str = "") -> dict[str, Any]:
    return {
        "source_unavailable_on_arxiv": unavailable,
        "source_unavailable_reason": reason,
    }


def fetch_response(
    session: requests.Session,
    *,
    url: str,
    timeout: int,
    headers: dict[str, str] | None = None,
) -> requests.Response:
    current_url = url
    for _ in range(10):
        try:
            require_public_http_url(current_url)
        except BlockedURL as exc:
            raise requests.exceptions.InvalidURL(f"blocked URL: {exc}") from exc
        response = session.get(current_url, timeout=timeout, allow_redirects=False, headers=headers, stream=True)
        if response.status_code in REDIRECT_STATUS_CODES and response.headers.get("location"):
            next_url = urljoin(current_url, str(response.headers["location"]))
            close = getattr(response, "close", None)
            if callable(close):
                close()
            try:
                require_public_http_url(next_url)
            except BlockedURL as exc:
                raise requests.exceptions.InvalidURL(f"blocked redirect URL: {exc}") from exc
            current_url = next_url
            continue
        return response
    raise requests.exceptions.TooManyRedirects(f"too many redirects for {url}")


def response_content_with_limit(response: Any, *, max_bytes: int = MAX_ASSET_BYTES) -> tuple[bytes, bool]:
    content = bytearray()
    iter_content = getattr(response, "iter_content", None)
    if callable(iter_content):
        for chunk in iter_content(chunk_size=1024 * 1024):
            if not chunk:
                continue
            if len(content) + len(chunk) > max_bytes:
                return b"", True
            content.extend(chunk)
        return bytes(content), False
    raw = bytes(getattr(response, "content", b"") or b"")
    if len(raw) > max_bytes:
        return b"", True
    return raw, False


def write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def fetch_text_asset(
    session: requests.Session,
    *,
    url: str,
    output_path: Path,
    timeout: int,
    max_bytes: int = MAX_ASSET_BYTES,
    force: bool = False,
) -> tuple[dict[str, Any], str]:
    result = basic_asset_result(url=url)
    if not force and output_path.exists() and output_path.stat().st_size > 0:
        result["success"] = True
        result["local_path"] = output_path.name
        result["skipped_existing"] = True
        try:
            return result, output_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return result, output_path.read_text(encoding="utf-8", errors="replace")
    try:
        response = fetch_response(session, url=url, timeout=timeout)
        result["status_code"] = response.status_code
        result["content_type"] = response.headers.get("content-type", "")
        result["final_url"] = str(response.url)
        response.raise_for_status()
        content, too_large = response_content_with_limit(response, max_bytes=max_bytes)
        close = getattr(response, "close", None)
        if callable(close):
            close()
        if too_large:
            result["error"] = f"download exceeds {max_bytes} bytes"
            return result, ""
        result["size_bytes"] = len(content)
        if not content:
            result["error"] = "empty response body"
            return result, ""
        text = content.decode("utf-8", errors="replace")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
        result["success"] = True
        result["local_path"] = output_path.name
        return result, text
    except requests.RequestException as exc:
        response = getattr(exc, "response", None)
        if response is not None:
            result["status_code"] = response.status_code
            result["content_type"] = response.headers.get("content-type", "")
            result["final_url"] = str(response.url)
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result, ""


def fetch_binary_asset(
    session: requests.Session,
    *,
    url: str,
    output_path: Path,
    timeout: int,
    max_bytes: int = MAX_ASSET_BYTES,
) -> dict[str, Any]:
    result = basic_asset_result(url=url)
    if output_path.exists() and output_path.stat().st_size > 0:
        result["success"] = True
        result["local_path"] = output_path.name
        result["skipped_existing"] = True
        return result
    try:
        response = fetch_response(session, url=url, timeout=timeout)
        result["status_code"] = response.status_code
        result["content_type"] = response.headers.get("content-type", "")
        result["final_url"] = str(response.url)
        response.raise_for_status()
        content, too_large = response_content_with_limit(response, max_bytes=max_bytes)
        close = getattr(response, "close", None)
        if callable(close):
            close()
        if too_large:
            result["error"] = f"download exceeds {max_bytes} bytes"
            return result
        result["size_bytes"] = len(content)
        write_bytes(output_path, content)
        result["success"] = True
        result["local_path"] = output_path.name
        return result
    except requests.RequestException as exc:
        response = getattr(exc, "response", None)
        if response is not None:
            result["status_code"] = response.status_code
            result["content_type"] = response.headers.get("content-type", "")
            result["final_url"] = str(response.url)
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result


def fetch_arxiv_source(
    session: requests.Session,
    *,
    arxiv_id: str,
    output_dir: Path,
    timeout: int,
    max_bytes: int = MAX_ASSET_BYTES,
) -> dict[str, Any]:
    existing = sorted(output_dir.glob("arxiv_source*"))
    if existing:
        result = basic_asset_result(url=f"https://arxiv.org/e-print/{arxiv_id}")
        result.update(source_unavailable_fields())
        result["success"] = True
        result["local_path"] = existing[0].name
        result["skipped_existing"] = True
        return result
    attempts = [
        f"https://arxiv.org/e-print/{arxiv_id}",
        f"https://arxiv.org/src/{arxiv_id}",
    ]
    result = basic_asset_result(url=attempts[0])
    for url in attempts:
        result = basic_asset_result(url=url)
        result.update(source_unavailable_fields())
        try:
            response = fetch_response(session, url=url, timeout=timeout)
            result["status_code"] = response.status_code
            result["content_type"] = response.headers.get("content-type", "")
            result["final_url"] = str(response.url)
            response.raise_for_status()
            content, too_large = response_content_with_limit(response, max_bytes=max_bytes)
            close = getattr(response, "close", None)
            if callable(close):
                close()
            if too_large:
                result["error"] = f"download exceeds {max_bytes} bytes"
                continue
            result["size_bytes"] = len(content)
            if not looks_like_source_package(content_type=result["content_type"], content=content):
                result["error"] = "response did not look like a TeX/source archive"
                if content.startswith(b"%PDF-") or "application/pdf" in result["content_type"].lower():
                    result.update(
                        source_unavailable_fields(
                            unavailable=True,
                            reason="arXiv served PDF content instead of a source archive",
                        )
                    )
                continue
            extension = infer_extension(
                content_type=result["content_type"],
                final_url=result["final_url"] or url,
                content=content,
            )
            output_path = output_dir / f"arxiv_source{extension}"
            write_bytes(output_path, content)
            result["success"] = True
            result["local_path"] = output_path.name
            return result
        except requests.RequestException as exc:
            response = getattr(exc, "response", None)
            if response is not None:
                result["status_code"] = response.status_code
                result["content_type"] = response.headers.get("content-type", "")
                result["final_url"] = str(response.url)
            result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def validate_archive_member_name(name: str) -> None:
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe archive member path: {name}")


def safe_extract_zip(archive: zipfile.ZipFile, extract_dir: Path) -> None:
    base = extract_dir.resolve()
    for info in archive.infolist():
        validate_archive_member_name(info.filename)
        target = (extract_dir / info.filename).resolve()
        try:
            target.relative_to(base)
        except ValueError as exc:
            raise ValueError(f"archive member escapes extract directory: {info.filename}") from exc
    archive.extractall(extract_dir)


def validate_tar_members(archive: tarfile.TarFile) -> None:
    for member in archive.getmembers():
        validate_archive_member_name(member.name)


def extract_source_archive(archive_path: Path) -> dict[str, Any]:
    extract_dir = archive_path.parent / "arxiv_source"
    result = {
        "extracted": False,
        "extract_dir": extract_dir.name,
        "extract_error": "",
        "extract_skipped_existing": False,
    }
    if not archive_path.exists():
        result["extract_error"] = "archive file does not exist"
        return result
    if extract_dir.exists() and any(extract_dir.iterdir()):
        result["extracted"] = True
        result["extract_skipped_existing"] = True
        return result

    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)
    try:
        if tarfile.is_tarfile(archive_path):
            with tarfile.open(archive_path, "r:*") as archive:
                validate_tar_members(archive)
                archive.extractall(extract_dir, filter="data")
        elif zipfile.is_zipfile(archive_path):
            with zipfile.ZipFile(archive_path) as archive:
                safe_extract_zip(archive, extract_dir)
        elif archive_path.suffix == ".gz":
            output_name = archive_path.stem or "source"
            with gzip.open(archive_path, "rb") as src, (extract_dir / output_name).open("wb") as dst:
                shutil.copyfileobj(src, dst)
        else:
            raise ValueError("unsupported archive format")
        result["extracted"] = True
        return result
    except Exception as exc:
        result["extract_error"] = f"{type(exc).__name__}: {exc}"
        shutil.rmtree(extract_dir, ignore_errors=True)
        return result


def resolve_folder(literature_dir: Path, arxiv_id: str) -> Path:
    target = literature_dir / arxiv_id
    if target.exists():
        return target
    legacy_matches = sorted(literature_dir.glob(f"{arxiv_id}+*"))
    if legacy_matches:
        legacy = legacy_matches[0]
        legacy.rename(target)
        return target
    return target


def archive_paper(
    selected: SelectedPaper,
    *,
    workspace: Path,
    literature_dir: Path,
    session: requests.Session,
    timeout: int = DEFAULT_TIMEOUT,
    ads_token: str = "",
) -> dict[str, Any]:
    paper = selected.paper
    arxiv_id = str(paper.get("arxiv_id") or "").strip()
    title = str(paper.get("title") or "Untitled")
    abs_url = str((paper.get("links") or {}).get("abs") or paper_url(arxiv_id))
    pdf_link = str((paper.get("links") or {}).get("pdf") or pdf_url(arxiv_id))
    run_at = datetime.now().isoformat(timespec="seconds")
    folder = resolve_folder(literature_dir, arxiv_id)
    ensure_directory(folder)

    temp_abs_path = folder / ASSET_FILENAMES["arxiv_abs"]
    arxiv_abs_result, arxiv_html = fetch_text_asset(
        session,
        url=abs_url,
        output_path=temp_abs_path,
        timeout=timeout,
    )
    ads_api_result, ads_metadata, ads_api_payload = fetch_ads_api_metadata(
        session,
        arxiv_id=arxiv_id,
        token=ads_token,
        timeout=timeout,
    )
    ads_metadata_audit: dict[str, Any] = {}
    if ads_api_payload:
        ads_metadata_path = write_ads_api_payload(
            folder,
            payload=ads_api_payload,
            workspace=workspace,
        )
        ads_api_result["local_path"] = ads_metadata_path
        ads_metadata_audit["local_path"] = ads_metadata_path

    arxiv_abs_path = folder / ASSET_FILENAMES["arxiv_abs"]
    if temp_abs_path.exists():
        arxiv_abs_result["local_path"] = arxiv_abs_path.name
        arxiv_abs_result["success"] = bool(arxiv_html) or bool(arxiv_abs_result.get("skipped_existing"))

    arxiv_pdf_result = fetch_binary_asset(
        session,
        url=pdf_link,
        output_path=folder / ASSET_FILENAMES["arxiv_pdf"],
        timeout=timeout,
    )
    arxiv_source_result = fetch_arxiv_source(
        session,
        arxiv_id=arxiv_id,
        output_dir=folder,
        timeout=timeout,
    )
    if arxiv_source_result.get("success") and arxiv_source_result.get("local_path"):
        arxiv_source_result.update(extract_source_archive(folder / str(arxiv_source_result["local_path"])))
    else:
        arxiv_source_result.update(
            source_unavailable_fields(
                unavailable=bool(arxiv_source_result.get("source_unavailable_on_arxiv")),
                reason=str(arxiv_source_result.get("source_unavailable_reason") or ""),
            )
            | {
                "extracted": False,
                "extract_dir": "arxiv_source",
                "extract_error": "archive not available",
                "extract_skipped_existing": False,
            }
        )

    folder_name = folder.name
    audit = {
        "schema_version": ASSET_AUDIT_SCHEMA_VERSION,
        "arxiv_id": arxiv_id,
        "title": title,
        "month": selected.month,
        "source_note_json": relative_path(selected.note_json_path, workspace=workspace),
        "folder_name": folder_name,
        "run_at": run_at,
        "ads_metadata": ads_metadata_audit,
        "ads_api": ads_api_result,
        "arxiv_abs": arxiv_abs_result,
        "arxiv_pdf": arxiv_pdf_result,
        "arxiv_source": arxiv_source_result,
    }
    audit_path = folder / "audit.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "arxiv_id": arxiv_id,
        "folder": relative_path(folder, workspace=workspace),
        "audit_path": relative_path(audit_path, workspace=workspace),
        "arxiv_abs": arxiv_abs_result["success"],
        "arxiv_pdf": arxiv_pdf_result["success"],
        "arxiv_source": arxiv_source_result["success"],
        "arxiv_source_extracted": arxiv_source_result["extracted"],
        "ads_bibcode": bool(ads_metadata.get("ads_bibcode")),
    }
