"""Minimal arXiv Atom API client for monthly candidate retrieval."""

from __future__ import annotations

import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any


ATOM_NS = "http://www.w3.org/2005/Atom"
ARXIV_NS = "http://arxiv.org/schemas/atom"
OPENSEARCH_NS = "http://a9.com/-/spec/opensearch/1.1/"
BASE_URL = "https://export.arxiv.org/api/query"
USER_AGENT = "stella-high-velocity-lit/0.1"


def atom_name(name: str) -> str:
    return f"{{{ATOM_NS}}}{name}"


def arxiv_name(name: str) -> str:
    return f"{{{ARXIV_NS}}}{name}"


def opensearch_name(name: str) -> str:
    return f"{{{OPENSEARCH_NS}}}{name}"


def compact_date(value: str, suffix: str) -> str:
    return value.replace("-", "") + suffix


def normalize_space(text: str | None) -> str:
    return " ".join((text or "").split())


def strip_version(arxiv_id: str) -> str:
    return re.sub(r"v\d+$", "", arxiv_id)


class ArxivClient:
    def _fetch(self, params: dict[str, Any]) -> bytes:
        url = f"{BASE_URL}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                with urllib.request.urlopen(request, timeout=45) as response:
                    return response.read()
            except Exception as exc:
                last_error = exc
                if attempt >= 3:
                    raise
                time.sleep(min(2 ** (attempt - 1), 4))
        if last_error is not None:
            raise last_error
        raise RuntimeError("arXiv request failed without an exception")

    def search(self, query: str, *, size: int, date_from: str, date_to: str) -> dict[str, Any]:
        phrase = query.replace('"', "").strip()
        submitted_from = compact_date(date_from, "0000")
        submitted_to = compact_date(date_to, "2359")
        search_query = f'all:"{phrase}" AND submittedDate:[{submitted_from} TO {submitted_to}]'
        params = {
            "search_query": search_query,
            "start": 0,
            "max_results": size,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        payload = self._fetch(params)
        root = ET.fromstring(payload)
        total = int(root.findtext(opensearch_name("totalResults")) or 0)
        entries = [self._entry_to_paper(entry) for entry in root.findall(atom_name("entry"))]
        return {"total": total, "results": entries}

    def metadata(self, arxiv_id: str) -> dict[str, Any]:
        params = {
            "id_list": arxiv_id,
            "start": 0,
            "max_results": 1,
        }
        payload = self._fetch(params)
        root = ET.fromstring(payload)
        entry = root.find(atom_name("entry"))
        if entry is None:
            return {"arxiv_id": strip_version(arxiv_id)}
        return self._entry_to_metadata(entry)

    def _entry_to_paper(self, entry: ET.Element) -> dict[str, Any]:
        raw_id = (entry.findtext(atom_name("id")) or "").rsplit("/", 1)[-1]
        arxiv_id = strip_version(raw_id)
        authors = [
            normalize_space(author.findtext(atom_name("name")))
            for author in entry.findall(atom_name("author"))
            if normalize_space(author.findtext(atom_name("name")))
        ]
        categories = [
            category.attrib.get("term", "")
            for category in entry.findall(atom_name("category"))
            if category.attrib.get("term")
        ]
        primary = entry.find(arxiv_name("primary_category"))
        if primary is not None and primary.attrib.get("term") and primary.attrib["term"] not in categories:
            categories.insert(0, primary.attrib["term"])

        return {
            "id": arxiv_id,
            "arxiv_id": arxiv_id,
            "title": normalize_space(entry.findtext(atom_name("title"))),
            "abstract": normalize_space(entry.findtext(atom_name("summary"))),
            "author_names": ", ".join(authors),
            "authors": authors,
            "categories": categories,
            "publish_at": normalize_space(entry.findtext(atom_name("published"))),
            "updated_at": normalize_space(entry.findtext(atom_name("updated"))),
            "score": 0,
            "source": "arxiv",
        }

    def _entry_to_metadata(self, entry: ET.Element) -> dict[str, Any]:
        paper = self._entry_to_paper(entry)
        links: dict[str, str] = {}
        for link in entry.findall(atom_name("link")):
            href = normalize_space(link.attrib.get("href"))
            title = normalize_space(link.attrib.get("title"))
            rel = normalize_space(link.attrib.get("rel"))
            link_type = normalize_space(link.attrib.get("type"))
            if title == "pdf" and href:
                links["pdf"] = href
            elif rel == "alternate" and href:
                links["abs"] = href
            elif title == "doi" and href:
                links["doi"] = href
            elif link_type == "application/atom+xml" and href:
                links["api"] = href

        comments = normalize_space(entry.findtext(arxiv_name("comment")))
        journal_ref = normalize_space(entry.findtext(arxiv_name("journal_ref")))
        doi = normalize_space(entry.findtext(arxiv_name("doi")))
        affiliations = [
            normalize_space(author.findtext(arxiv_name("affiliation")))
            for author in entry.findall(atom_name("author"))
            if normalize_space(author.findtext(arxiv_name("affiliation")))
        ]
        primary = entry.find(arxiv_name("primary_category"))

        return {
            **paper,
            "links": links,
            "comment": comments,
            "journal_ref": journal_ref,
            "doi": doi,
            "author_affiliations": affiliations,
            "primary_category": primary.attrib.get("term", "") if primary is not None else "",
        }
