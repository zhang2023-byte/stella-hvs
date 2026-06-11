"""arXiv version consistency checks between the archived PDF and TeX source.

Expert annotation treats the PDF as the normative evidence source while the
AI pipeline reads the TeX/ECSV view, so both must come from the same arXiv
version. Both artifacts were fetched in the same run with versionless URLs
("latest at fetch time"), which makes a mismatch unlikely but worth machine
verification instead of trust:

- the PDF carries the ``arXiv:<id>v<N>`` margin watermark on page 1;
- the archived abstract page lists the version history; the highest listed
  version is the one a versionless fetch returned.

Either side can be unextractable (cropped watermark, unusual abs layout);
that yields ``None`` and the manifest records a warning instead of failing.
"""

from __future__ import annotations

import re
from pathlib import Path


def _watermark_re(arxiv_id: str) -> re.Pattern[str]:
    return re.compile(rf"arXiv:{re.escape(arxiv_id)}v([0-9]+)")


def parse_pdf_watermark_version(page_text: str, arxiv_id: str) -> int | None:
    """Extract the version number from page-1 watermark text."""

    match = _watermark_re(arxiv_id).search(page_text)
    if not match:
        return None
    return int(match.group(1))


def parse_abs_latest_version(html: str, arxiv_id: str) -> int | None:
    """Extract the highest version listed on an archived arXiv abs page."""

    versions = [
        int(value)
        for value in re.findall(
            rf"abs/{re.escape(arxiv_id)}v([0-9]+)", html
        )
    ]
    if not versions:
        return None
    return max(versions)


def extract_pdf_version(pdf_path: Path, arxiv_id: str) -> int | None:
    """Read page 1 of the archived PDF and parse the watermark version."""

    import fitz

    if not pdf_path.is_file():
        return None
    with fitz.open(pdf_path) as document:
        if document.page_count == 0:
            return None
        text = document[0].get_text()
    return parse_pdf_watermark_version(text, arxiv_id)


def extract_abs_version(abs_html_path: Path, arxiv_id: str) -> int | None:
    """Parse the archived abs page for the latest listed version."""

    if not abs_html_path.is_file():
        return None
    html = abs_html_path.read_text(encoding="utf-8", errors="replace")
    return parse_abs_latest_version(html, arxiv_id)


def check_paper_versions(paper_dir: Path, arxiv_id: str) -> dict:
    """Compare PDF watermark and abs-page versions for one archived paper.

    Returns a dict with ``pdf_version``, ``abs_version`` (either may be
    None), and ``version_consistent`` (None when undecidable).
    """

    pdf_version = extract_pdf_version(paper_dir / "arxiv.pdf", arxiv_id)
    abs_version = extract_abs_version(paper_dir / "arxiv_abs.html", arxiv_id)
    consistent: bool | None
    if pdf_version is None or abs_version is None:
        consistent = None
    else:
        consistent = pdf_version == abs_version
    return {
        "pdf_version": pdf_version,
        "abs_version": abs_version,
        "version_consistent": consistent,
    }
