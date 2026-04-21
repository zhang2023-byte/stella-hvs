"""Multi-source catalog verification for individual literature papers."""

from __future__ import annotations

import csv
import hashlib
import html
import json
import random
import re
import tarfile
import time
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from .arxiv_client import ArxivClient
from .deepxiv_client import DeepXivClient


USER_AGENT = "stella-high-velocity-lit/0.1"
SCHEMA_VERSION = "stella.literature.catalog.v1"
RELEVANT_SECTION_TERMS = {
    "catalog": 8,
    "data availability": 8,
    "appendix": 6,
    "tables": 6,
    "sample": 5,
    "observations": 5,
    "results": 4,
    "data": 4,
    "method": 2,
}
CATALOG_TERMS = [
    "catalog",
    "machine-readable",
    "machine readable",
    "supplementary material",
    "supplementary data",
    "electronic table",
    "full table",
    "complete table",
    "table",
    "appendix",
    "candidate list",
    "candidate stars",
    "source id",
    "gaia source",
]
DATA_TERMS = [
    "radial velocity",
    "proper motion",
    "parallax",
    "distance",
    "abundance",
    "metallicity",
    "spectrum",
    "photometry",
    "orbit",
    "astrometry",
    "coordinates",
]
EXTERNAL_HINTS = [
    "cds",
    "vizier",
    "zenodo",
    "figshare",
    "dataverse",
    "online material",
    "online-only",
    "available online",
    "available electronically",
    "machine-readable version",
]
EXTERNAL_HOST_HINTS = [
    "cdsarc",
    "cds.u-strasbg.fr",
    "vizier",
    "zenodo.org",
    "figshare.com",
    "dataverse",
    "archive.stsci.edu",
    "mast.stsci.edu",
]
TEXT_SUFFIXES = {
    ".tex",
    ".txt",
    ".md",
    ".rst",
    ".csv",
    ".tsv",
    ".dat",
    ".ecsv",
    ".xml",
    ".json",
    ".yaml",
    ".yml",
    ".readme",
}
DATA_SUFFIXES = {
    ".csv",
    ".tsv",
    ".dat",
    ".ecsv",
    ".fits",
    ".fit",
    ".vot",
    ".votable",
    ".xml",
    ".json",
    ".parquet",
}
TRUSTED_PDF_EXTRACTORS = {"pypdf", "arxiv_html_fallback"}
INDEX_MD_ENTRY_RE = re.compile(
    r"^- \[(?P<title>.+?)\]\((?P<path>[^)]+)\)(?: \((?P<month>\d{4}-\d{2})\))?(?:\s+-.*)?$"
)
MONTH_SLUG_RE = re.compile(r"^\d{4}-\d{2}$")
URL_RE = re.compile(r"https?://[^\s<>\]\"')]+", re.IGNORECASE)
DESCRIPTOR_RE = re.compile(
    r'<span class="descriptor">(?P<label>[^<:]+):</span>\s*(?P<value>.*?)</(?:td|div)>',
    re.IGNORECASE | re.DOTALL,
)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalize_space(text: str | None) -> str:
    return " ".join((text or "").split())


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative_to(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def month_slug_from_note_path(note_rel: str) -> str:
    stem = Path(note_rel).stem
    return stem if MONTH_SLUG_RE.fullmatch(stem) else ""


def download_to_path(url: str, destination: Path, *, retries: int = 3, timeout: int = 60) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    last_error: str | None = None
    for attempt in range(1, retries + 1):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=timeout) as response, destination.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
            return {
                "ok": True,
                "url": url,
                "path": str(destination),
                "size_bytes": destination.stat().st_size,
                "sha256": sha256_path(destination),
            }
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(min(2 ** (attempt - 1), 4))
    return {
        "ok": False,
        "url": url,
        "path": str(destination),
        "error": last_error or "download failed",
    }


def download_text(url: str, *, timeout: int = 45) -> str:
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8", errors="replace")
        except Exception as exc:
            last_error = exc
            if attempt >= 3:
                raise
            time.sleep(min(2 ** (attempt - 1), 4))
    if last_error is not None:
        raise last_error
    raise RuntimeError("text download failed without an exception")


def extract_urls(text: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for match in URL_RE.findall(text):
        url = match.rstrip(".,;:")
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def is_external_catalog_url(url: str) -> bool:
    lowered = url.lower()
    return any(host in lowered for host in EXTERNAL_HOST_HINTS)


def extract_keyword_evidence(text: str, *, limit: int = 12) -> list[str]:
    chunks = re.split(r"(?<=[\.\?!])\s+|\n+", text)
    evidence: list[str] = []
    seen: set[str] = set()
    keywords = CATALOG_TERMS + DATA_TERMS + EXTERNAL_HINTS
    for chunk in chunks:
        normalized = normalize_space(html.unescape(chunk))
        lowered = normalized.lower()
        if len(normalized) < 25:
            continue
        if not any(term in lowered for term in keywords):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        evidence.append(normalized)
        if len(evidence) >= limit:
            break
    return evidence


def analyze_catalog_text(text: str, *, source: str) -> dict[str, Any]:
    lowered = text.lower()
    catalog_hits = sorted({term for term in CATALOG_TERMS if term in lowered})
    data_hits = sorted({term for term in DATA_TERMS if term in lowered})
    evidence = extract_keyword_evidence(text)
    external_hits = sorted(
        {
            term
            for line in evidence
            for term in EXTERNAL_HINTS
            if term in line.lower() and any(marker in line.lower() for marker in CATALOG_TERMS)
        }
    )
    evidence_urls = sorted({url for line in evidence for url in extract_urls(line)})
    external_urls = [url for url in evidence_urls if is_external_catalog_url(url)]

    score = 0
    score += len(catalog_hits) * 2
    score += min(len(data_hits), 3)
    if re.search(r"\btable\s+[a-z]?\d+\b", lowered):
        score += 2
    if any(phrase in lowered for phrase in ("we present", "we list", "we provide", "candidate stars", "sample of")):
        score += 1
    if external_hits or external_urls:
        score += 3

    if score >= 7:
        verdict = "present"
    elif score >= 4:
        verdict = "possible"
    else:
        verdict = "absent"

    if (external_hits or external_urls) and (catalog_hits or data_hits):
        location = "mixed"
    elif external_hits or external_urls:
        location = "external"
    elif verdict != "absent":
        location = "internal"
    else:
        location = "unknown"

    return {
        "source": source,
        "verdict": verdict,
        "score": score,
        "catalog_hits": catalog_hits,
        "data_hits": data_hits,
        "external_hits": external_hits,
        "evidence": evidence,
        "evidence_urls": evidence_urls,
        "external_urls": external_urls,
        "location_hint": location,
    }


def select_relevant_sections(head_payload: dict[str, Any], *, max_sections: int = 4) -> list[str]:
    ranked: list[tuple[int, str]] = []
    for entry in head_payload.get("sections") or []:
        if not isinstance(entry, dict):
            continue
        name = normalize_space(str(entry.get("name") or ""))
        lowered = name.lower()
        score = 0
        for term, value in RELEVANT_SECTION_TERMS.items():
            if term in lowered:
                score += value
        if "introduction" in lowered:
            score += 1
        if score > 0:
            ranked.append((score, name))
    ranked.sort(key=lambda item: (-item[0], item[1]))

    seen: set[str] = set()
    selected: list[str] = []
    for _, name in ranked:
        if name in seen:
            continue
        seen.add(name)
        selected.append(name)
        if len(selected) >= max_sections:
            break

    if not selected:
        for entry in (head_payload.get("sections") or [])[:max_sections]:
            name = normalize_space(str((entry or {}).get("name") or ""))
            if name:
                selected.append(name)
    return selected


class AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[dict[str, str]] = []
        self._current_href: str | None = None
        self._current_attrs: dict[str, str] = {}
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        values = {key: (value or "") for key, value in attrs}
        self._current_href = values.get("href")
        self._current_attrs = values
        self._parts = []

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._current_href is None:
            return
        self.links.append(
            {
                "href": self._current_href,
                "text": normalize_space("".join(self._parts)),
                "class": self._current_attrs.get("class", ""),
                "id": self._current_attrs.get("id", ""),
            }
        )
        self._current_href = None
        self._current_attrs = {}
        self._parts = []


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = normalize_space(data)
        if text:
            self.parts.append(text)

    def text(self) -> str:
        return "\n".join(self.parts)


def strip_html_tags(fragment: str) -> str:
    parser = TextExtractor()
    parser.feed(fragment)
    return normalize_space(html.unescape(parser.text()))


def parse_abs_page(html_text: str) -> dict[str, Any]:
    parser = AnchorParser()
    parser.feed(html_text)
    links = parser.links

    pdf_url = ""
    html_url = ""
    source_url = ""
    external_links: list[dict[str, str]] = []
    for link in links:
        href = urljoin("https://arxiv.org", link.get("href") or "")
        lowered_class = (link.get("class") or "").lower()
        link_id = (link.get("id") or "").lower()
        if "download-pdf" in lowered_class:
            pdf_url = href
        elif "download-eprint" in lowered_class:
            source_url = href
        elif link_id == "latexml-download-link":
            html_url = href
        elif "arxiv.org" not in href and not href.lower().startswith("javascript:"):
            external_links.append({"url": href, "text": link.get("text") or ""})

    descriptors: dict[str, str] = {}
    for match in DESCRIPTOR_RE.finditer(html_text):
        label = normalize_space(match.group("label")).lower().replace(" ", "_")
        value = strip_html_tags(match.group("value"))
        if value:
            descriptors[label] = value

    return {
        "pdf_url": pdf_url,
        "source_url": source_url,
        "html_url": html_url,
        "external_links": external_links,
        "descriptors": descriptors,
    }


def extract_pdf_text(pdf_path: Path) -> dict[str, Any]:
    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]

        reader = PdfReader(str(pdf_path))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        return {
            "text": text,
            "page_count": len(reader.pages),
            "extractor": "pypdf",
        }
    except Exception:
        raw = pdf_path.read_bytes()
        chunks = re.findall(rb"[ -~]{20,}", raw)
        text = "\n".join(chunk.decode("latin-1", errors="replace") for chunk in chunks[:5000])
        return {
            "text": text,
            "page_count": None,
            "extractor": "raw_strings",
        }


def safe_extract_tar(archive_path: Path, destination: Path) -> list[str]:
    destination.mkdir(parents=True, exist_ok=True)
    extracted: list[str] = []
    with tarfile.open(archive_path, mode="r:*") as handle:
        root = destination.resolve()
        for member in handle.getmembers():
            target = (destination / member.name).resolve()
            if root not in target.parents and target != root:
                raise RuntimeError(f"Unsafe path in source archive: {member.name}")
            handle.extract(member, destination)
            extracted.append(member.name)
    return extracted


def iter_text_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix in TEXT_SUFFIXES or path.name.lower() == "readme":
            yield path


def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1", errors="replace")


def clean_latex_text(text: str) -> str:
    cleaned = text
    cleaned = re.sub(r"(?<!\\)%.*", "", cleaned)
    cleaned = cleaned.replace("~", " ")
    cleaned = re.sub(r"\\url\{([^}]*)\}", r"\1", cleaned)
    cleaned = re.sub(r"\\href\{([^}]*)\}\{([^}]*)\}", r"\2 (\1)", cleaned)
    cleaned = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?\{([^{}]*)\}", r"\1", cleaned)
    cleaned = re.sub(r"\\[a-zA-Z]+\*?", " ", cleaned)
    cleaned = cleaned.replace("{", " ").replace("}", " ")
    cleaned = cleaned.replace("$", " ")
    return normalize_space(cleaned)


def looks_like_header(cells: list[str]) -> bool:
    if not cells:
        return False
    if all(any(char.isalpha() for char in cell) for cell in cells):
        return True
    return False


def parse_table_rows(body: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for raw_row in re.split(r"\\\\", body):
        row = clean_latex_text(raw_row)
        if not row:
            continue
        if any(token in row.lower() for token in ("hline", "cline", "tableline", "cutinhead", "sidehead")):
            continue
        cells = [clean_latex_text(cell) for cell in raw_row.split("&")]
        cells = [cell for cell in cells if cell]
        if len(cells) >= 2:
            rows.append(cells)
    return rows


def write_table_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    if not rows:
        return
    width = max(len(header), *(len(row) for row in rows))
    if not header:
        header = [f"col_{index + 1}" for index in range(width)]
    padded_rows = [row + [""] * (width - len(row)) for row in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(padded_rows)


def extract_tables_from_tex(tex_path: Path, output_dir: Path, *, root: Path) -> list[dict[str, Any]]:
    text = read_text_file(tex_path)
    tables: list[dict[str, Any]] = []
    patterns = [
        re.compile(r"\\begin\{deluxetable\*?\}(.*?)\\end\{deluxetable\*?\}", re.DOTALL),
        re.compile(r"\\begin\{longtable\*?\}(.*?)\\end\{longtable\*?\}", re.DOTALL),
        re.compile(r"\\begin\{tabular\*?\}(.*?)\\end\{tabular\*?\}", re.DOTALL),
    ]

    table_index = 0
    for pattern in patterns:
        for match in pattern.finditer(text):
            fragment = match.group(1)
            caption_match = re.search(r"\\(?:table)?caption\{([^}]*)\}", fragment, re.DOTALL)
            caption = clean_latex_text(caption_match.group(1)) if caption_match else ""
            headers = [clean_latex_text(value) for value in re.findall(r"\\colhead\{([^}]*)\}", fragment)]
            body_match = re.search(r"\\startdata(.*?)\\enddata", fragment, re.DOTALL)
            body = body_match.group(1) if body_match else fragment
            rows = parse_table_rows(body)
            if not rows:
                continue
            header = headers
            data_rows = rows
            if not header and looks_like_header(rows[0]):
                header = rows[0]
                data_rows = rows[1:]
            table_index += 1
            csv_path = output_dir / f"{tex_path.stem}_table_{table_index:02d}.csv"
            write_table_csv(csv_path, header, data_rows)
            tables.append(
                {
                    "source_tex": relative_to(tex_path, root),
                    "caption": caption,
                    "header": header,
                    "row_count": len(data_rows),
                    "csv_path": str(csv_path),
                }
            )
    return tables


def inspect_source_tree(source_root: Path, output_dir: Path) -> dict[str, Any]:
    data_files: list[str] = []
    text_bundle: list[str] = []
    urls: list[str] = []
    tables: list[dict[str, Any]] = []

    for path in source_root.rglob("*"):
        if not path.is_file():
            continue
        rel = relative_to(path, source_root)
        if path.suffix.lower() in DATA_SUFFIXES:
            data_files.append(rel)

    for text_path in iter_text_files(source_root):
        text = read_text_file(text_path)
        cleaned = clean_latex_text(text)
        text_bundle.append(cleaned)
        urls.extend(extract_urls(text))
        if text_path.suffix.lower() == ".tex":
            tables.extend(extract_tables_from_tex(text_path, output_dir, root=source_root))

    combined_text = "\n".join(text_bundle)
    analysis = analyze_catalog_text(combined_text, source="source")
    unique_urls = sorted(dict.fromkeys(urls))
    analysis["evidence_urls"] = sorted(dict.fromkeys(analysis["evidence_urls"] + unique_urls))
    analysis["external_urls"] = sorted(
        dict.fromkeys(analysis["external_urls"] + [url for url in unique_urls if is_external_catalog_url(url)])
    )
    return {
        "analysis": analysis,
        "data_files": sorted(data_files),
        "tables": tables,
        "url_count": len(unique_urls),
        "urls": unique_urls,
    }


def resolve_catalog_location(*, deepxiv: dict[str, Any], pdf: dict[str, Any], source: dict[str, Any]) -> str:
    external = any(
        item.get("analysis", {}).get("location_hint") in {"external", "mixed"}
        or item.get("analysis", {}).get("external_urls")
        for item in (deepxiv, pdf, source)
    )
    internal = bool(source.get("data_files") or source.get("tables")) or any(
        item.get("analysis", {}).get("location_hint") in {"internal", "mixed"} for item in (deepxiv, pdf, source)
    )
    if internal and external:
        return "mixed"
    if external:
        return "external_only"
    if internal:
        return "internal_only"
    return "not_found"


def apply_external_catalog_urls(location: str, external_urls: list[str]) -> str:
    if not external_urls:
        return location
    if location == "internal_only":
        return "mixed"
    if location == "not_found":
        return "external_only"
    return location


def pdf_verification_passed(pdf_record: dict[str, Any]) -> bool:
    verdict = (pdf_record.get("analysis") or {}).get("verdict")
    extractor = str(pdf_record.get("extractor") or "")
    if verdict == "present":
        return True
    return verdict == "possible" and extractor in TRUSTED_PDF_EXTRACTORS


def render_summary(record: dict[str, Any]) -> str:
    lines = [
        f"# {record.get('title') or record.get('arxiv_id')}",
        "",
        f"- arXiv ID: `{record.get('arxiv_id')}`",
        f"- Generated at: {record.get('generated_at')}",
        f"- Catalog location: `{record.get('catalog', {}).get('location')}`",
        f"- Overall verdict: `{record.get('verification', {}).get('overall_verdict')}`",
        "",
        "## Links",
        "",
    ]
    links = record.get("links") or {}
    for label in ("abs", "pdf", "source", "html", "doi"):
        value = links.get(label)
        if value:
            lines.append(f"- {label}: {value}")
    lines.extend(["", "## Evidence", ""])
    for source_name in ("deepxiv", "pdf", "source"):
        analysis = (record.get(source_name) or {}).get("analysis") or {}
        lines.append(f"### {source_name}")
        lines.append("")
        lines.append(f"- verdict: `{analysis.get('verdict')}`")
        lines.append(f"- score: {analysis.get('score')}")
        for item in analysis.get("evidence") or []:
            lines.append(f"- {item}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def load_index_md_candidates(index_md_path: Path) -> list[dict[str, Any]]:
    notes_dir = index_md_path.parent
    month_cache: dict[Path, dict[str, Any]] = {}
    candidates: list[dict[str, Any]] = []
    for line in index_md_path.read_text(encoding="utf-8").splitlines():
        match = INDEX_MD_ENTRY_RE.match(line.strip())
        if not match:
            continue
        title = match.group("title")
        note_rel = match.group("path")
        month = match.group("month") or month_slug_from_note_path(note_rel)
        if not month:
            continue
        json_path = notes_dir / Path(note_rel).with_suffix(".json")
        if json_path not in month_cache and json_path.exists():
            month_cache[json_path] = read_json(json_path)
        record = month_cache.get(json_path) or {}
        for paper in record.get("papers") or []:
            if normalize_space(str((paper or {}).get("title") or "")) != normalize_space(title):
                continue
            arxiv_id = normalize_space(str((paper or {}).get("arxiv_id") or ""))
            if arxiv_id:
                candidates.append(
                    {
                        "title": title,
                        "arxiv_id": arxiv_id,
                        "month": month,
                        "note_path": note_rel,
                    }
                )
            break
    return candidates


def sample_index_md_candidates(index_md_path: Path, *, count: int, seed: int | None = None) -> list[dict[str, Any]]:
    candidates = load_index_md_candidates(index_md_path)
    if count >= len(candidates):
        return candidates
    rng = random.Random(seed)
    return rng.sample(candidates, count)


def verify_paper_catalog(
    *,
    arxiv_id: str,
    output_root: Path,
    deepxiv_client: DeepXivClient,
    arxiv_client: ArxivClient,
    force: bool = False,
    max_sections: int = 4,
) -> dict[str, Any]:
    paper_dir = output_root / arxiv_id
    record_path = paper_dir / "record.json"
    if record_path.exists() and not force:
        return read_json(record_path)

    paper_dir.mkdir(parents=True, exist_ok=True)
    deepxiv_dir = paper_dir / "deepxiv"
    pdf_dir = paper_dir / "pdf"
    source_dir = paper_dir / "source"

    metadata_error = ""
    try:
        metadata = arxiv_client.metadata(arxiv_id)
    except Exception as exc:
        metadata = {
            "arxiv_id": arxiv_id,
            "title": "",
            "links": {
                "abs": f"https://arxiv.org/abs/{arxiv_id}",
                "pdf": f"https://arxiv.org/pdf/{arxiv_id}",
            },
        }
        metadata_error = f"{type(exc).__name__}: {exc}"
    write_json(paper_dir / "arxiv_metadata.json", metadata)

    abs_url = (metadata.get("links") or {}).get("abs") or f"https://arxiv.org/abs/{arxiv_id}"
    abs_html = download_text(abs_url)
    write_text(paper_dir / "arxiv_abs.html", abs_html)
    abs_page = parse_abs_page(abs_html)
    abs_page_analysis = analyze_catalog_text(
        "\n".join(str(value) for value in (abs_page.get("descriptors") or {}).values()),
        source="arxiv_abs_page",
    )
    abs_external_catalog_urls = sorted(
        dict.fromkeys(
            link.get("url") or ""
            for link in (abs_page.get("external_links") or [])
            if is_external_catalog_url(link.get("url") or "")
        )
    )

    links = {
        "abs": abs_url,
        "pdf": abs_page.get("pdf_url") or (metadata.get("links") or {}).get("pdf") or f"https://arxiv.org/pdf/{arxiv_id}",
        "source": abs_page.get("source_url") or f"https://arxiv.org/src/{arxiv_id}",
        "html": abs_page.get("html_url") or "",
        "doi": (metadata.get("links") or {}).get("doi") or (f"https://doi.org/{metadata.get('doi')}" if metadata.get("doi") else ""),
    }

    deepxiv_head = deepxiv_client.head(arxiv_id)
    write_json(deepxiv_dir / "head.json", deepxiv_head)
    selected_sections = select_relevant_sections(deepxiv_head, max_sections=max_sections)
    section_files: list[str] = []
    section_texts: list[str] = []
    for index, section_name in enumerate(selected_sections, start=1):
        content = deepxiv_client.section(arxiv_id, section_name)
        file_name = f"{index:02d}_{re.sub(r'[^A-Za-z0-9._-]+', '_', section_name).strip('_') or 'section'}.md"
        section_path = deepxiv_dir / "sections" / file_name
        write_text(section_path, content)
        section_files.append(str(section_path))
        section_texts.append(f"# {section_name}\n{content}")

    deepxiv_bundle = "\n\n".join(
        [
            normalize_space(str(deepxiv_head.get("title") or "")),
            normalize_space(str(deepxiv_head.get("abstract") or "")),
            "\n\n".join(section_texts),
        ]
    )
    deepxiv_analysis = analyze_catalog_text(deepxiv_bundle, source="deepxiv_sections")
    raw_path: Path | None = None
    if deepxiv_analysis["verdict"] != "present":
        deepxiv_raw = deepxiv_client.raw(arxiv_id)
        raw_path = deepxiv_dir / "raw.md"
        write_text(raw_path, deepxiv_raw)
        raw_analysis = analyze_catalog_text(deepxiv_raw, source="deepxiv_raw")
        if raw_analysis["score"] > deepxiv_analysis["score"]:
            deepxiv_analysis = raw_analysis

    deepxiv_record = {
        "head_path": str(deepxiv_dir / "head.json"),
        "section_paths": section_files,
        "raw_path": str(raw_path) if raw_path is not None else None,
        "selected_sections": selected_sections,
        "analysis": deepxiv_analysis,
    }

    pdf_record: dict[str, Any] = {
        "download": None,
        "text_path": None,
        "analysis": analyze_catalog_text("", source="pdf"),
        "verification_html_path": None,
    }
    source_record: dict[str, Any] = {
        "download": None,
        "manifest_path": None,
        "analysis": analyze_catalog_text("", source="source"),
        "data_files": [],
        "tables": [],
    }

    should_check_pdf = deepxiv_analysis["verdict"] in {"present", "possible"}
    if should_check_pdf:
        pdf_path = pdf_dir / f"{arxiv_id}.pdf"
        pdf_download = download_to_path(links["pdf"], pdf_path)
        pdf_record["download"] = pdf_download
        if pdf_download.get("ok"):
            extracted = extract_pdf_text(pdf_path)
            text = extracted.get("text") or ""
            text_source = extracted.get("extractor")
            html_path = None
            if len(normalize_space(text)) < 500 and links.get("html"):
                verification_html = download_text(links["html"])
                html_path = pdf_dir / "verification.html"
                write_text(html_path, verification_html)
                stripped = strip_html_tags(verification_html)
                if len(normalize_space(stripped)) > len(normalize_space(text)):
                    text = stripped
                    text_source = "arxiv_html_fallback"
            text_path = pdf_dir / "paper.txt"
            write_text(text_path, text)
            pdf_analysis = analyze_catalog_text(text, source=str(text_source or "pdf"))
            pdf_record.update(
                {
                    "text_path": str(text_path),
                    "page_count": extracted.get("page_count"),
                    "extractor": text_source,
                    "verification_html_path": str(html_path) if html_path else None,
                    "analysis": pdf_analysis,
                }
            )

    should_check_source = False
    if (pdf_record.get("download") or {}).get("ok"):
        if pdf_record["analysis"]["verdict"] in {"present", "possible"}:
            should_check_source = True
        elif deepxiv_analysis["verdict"] == "present" and pdf_record.get("extractor") == "raw_strings":
            should_check_source = True
    if should_check_source:
        source_archive = source_dir / f"{arxiv_id}_source.tar.gz"
        source_download = download_to_path(links["source"], source_archive)
        source_record["download"] = source_download
        if source_download.get("ok"):
            extracted_root = source_dir / "extracted"
            members = safe_extract_tar(source_archive, extracted_root)
            manifest_path = source_dir / "manifest.json"
            write_json(
                manifest_path,
                {
                    "archive": str(source_archive),
                    "members": members,
                    "generated_at": now_iso(),
                },
            )
            inspected = inspect_source_tree(extracted_root, source_dir / "catalog_tables")
            source_record.update(
                {
                    "manifest_path": str(manifest_path),
                    "analysis": inspected["analysis"],
                    "data_files": inspected["data_files"],
                    "tables": inspected["tables"],
                    "urls": inspected["urls"],
                }
            )

    overall_location = resolve_catalog_location(
        deepxiv=deepxiv_record,
        pdf=pdf_record,
        source=source_record,
    )
    catalog_external_urls = sorted(
        dict.fromkeys(
            abs_external_catalog_urls
            + abs_page_analysis["external_urls"]
            + deepxiv_record["analysis"]["external_urls"]
            + pdf_record["analysis"]["external_urls"]
            + source_record["analysis"]["external_urls"]
        )
    )
    overall_location = apply_external_catalog_urls(overall_location, catalog_external_urls)
    pdf_verified = pdf_verification_passed(pdf_record)
    overall_verdict = "not_confirmed"
    if deepxiv_record["analysis"]["verdict"] != "absent" and pdf_verified:
        overall_verdict = "confirmed"
    elif (
        deepxiv_record["analysis"]["verdict"] == "present"
        and (pdf_record.get("download") or {}).get("ok")
        and source_record["analysis"]["verdict"] != "absent"
    ):
        overall_verdict = "confirmed_with_source_fallback"
    if overall_location.startswith("external") and overall_verdict == "confirmed":
        overall_verdict = "confirmed_external"
    elif overall_location.startswith("external") and overall_verdict == "confirmed_with_source_fallback":
        overall_verdict = "confirmed_external_with_source_fallback"

    record = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "arxiv_id": arxiv_id,
        "title": metadata.get("title") or deepxiv_head.get("title") or arxiv_id,
        "links": links,
        "published_version": {
            "doi": metadata.get("doi") or "",
            "journal_ref": metadata.get("journal_ref") or "",
            "comment": metadata.get("comment") or "",
            "author_affiliations": metadata.get("author_affiliations") or [],
        },
        "arxiv": {
            "metadata_path": str(paper_dir / "arxiv_metadata.json"),
            "metadata_error": metadata_error or None,
            "abs_page_path": str(paper_dir / "arxiv_abs.html"),
            "abs_page": abs_page,
            "abs_page_analysis": abs_page_analysis,
        },
        "deepxiv": deepxiv_record,
        "pdf": pdf_record,
        "source": source_record,
        "catalog": {
            "location": overall_location,
            "external_urls": catalog_external_urls,
            "data_files": source_record.get("data_files") or [],
            "tables": source_record.get("tables") or [],
        },
        "verification": {
            "deepxiv_verdict": deepxiv_record["analysis"]["verdict"],
            "pdf_verdict": pdf_record["analysis"]["verdict"],
            "pdf_verified": pdf_verified,
            "source_verdict": source_record["analysis"]["verdict"],
            "overall_verdict": overall_verdict,
        },
    }
    write_json(record_path, record)
    write_text(paper_dir / "summary.md", render_summary(record))
    return record
