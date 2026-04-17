"""Minimal arXiv Atom API client for monthly candidate retrieval."""

from __future__ import annotations

import re
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
        url = f"{BASE_URL}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = response.read()

        root = ET.fromstring(payload)
        total = int(root.findtext(opensearch_name("totalResults")) or 0)
        entries = [self._entry_to_paper(entry) for entry in root.findall(atom_name("entry"))]
        return {"total": total, "results": entries}

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
