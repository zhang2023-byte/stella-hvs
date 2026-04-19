"""LLM-assisted assessment of observational catalog content in note records."""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from .filters import clean_text


@dataclass(frozen=True)
class CatalogAssessment:
    has_observational_catalog: bool
    confidence: float
    catalog_role: str
    object_scope: str
    evidence: str
    data_products: list[str]


class CatalogAssessor(Protocol):
    def assess_batch(self, papers: list[dict[str, Any]]) -> dict[str, CatalogAssessment]:
        """Assess a batch of paper records keyed by arXiv ID."""


def _extract_json_array(text: str) -> list[Any]:
    text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1 or end <= start:
            raise
        data = json.loads(text[start : end + 1])
    if not isinstance(data, list):
        raise ValueError("LLM catalog assessor did not return a JSON array")
    return data


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _paper_payload(paper: dict[str, Any]) -> dict[str, Any]:
    abstract = paper.get("abstract") or {}
    brief = paper.get("brief") or {}
    triage = paper.get("triage") or {}
    return {
        "arxiv_id": paper.get("arxiv_id"),
        "title": clean_text(paper.get("title")),
        "categories": paper.get("categories") or [],
        "triage": {
            "level": triage.get("level"),
            "label": triage.get("label"),
            "reason": triage.get("reason"),
        },
        "abstract": clean_text(abstract.get("text")),
        "brief_tldr": clean_text(brief.get("tldr")),
        "brief_keywords": brief.get("keywords") or [],
    }


class LLMCatalogAssessor:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float = 0.0,
        timeout: int = 90,
        max_retries: int = 3,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries

    def assess_batch(self, papers: list[dict[str, Any]]) -> dict[str, CatalogAssessment]:
        items = [_paper_payload(paper) for paper in papers]
        prompt = (
            "Assess whether each high-velocity-star literature record likely contains real observational "
            "stellar data or a catalog/sample/list of high-velocity, hypervelocity, runaway, unbound, "
            "escaping, or ejected star objects. Use only the provided title, abstract, brief TLDR, "
            "brief keywords, categories, and triage metadata.\n\n"
            "Return has_observational_catalog=true when the paper appears to present, compile, use, or "
            "analyze object-level observational data for actual stellar objects, such as source IDs, "
            "coordinates, proper motions, parallaxes, radial velocities, spectra, abundances, candidate "
            "lists, follow-up observations, or survey/catalog tables. This includes single-object discovery "
            "papers and multi-object candidate catalogs.\n\n"
            "Return false for purely theoretical papers, simulations without object-level observed stars, "
            "dynamical mechanism studies, generic survey/data-release papers, software/method papers, or "
            "papers that only mention high-velocity stars as motivation without an apparent object-level "
            "observational sample.\n\n"
            "catalog_role must be one of: new_catalog, compiled_catalog, followup_observations, "
            "uses_existing_catalog, not_catalog, unclear. object_scope must be one of: single_object, "
            "multiple_objects, none, unclear. data_products should be short strings such as source_ids, "
            "coordinates, astrometry, radial_velocities, spectra, abundances, orbit_integrations, "
            "candidate_table.\n\n"
            "Return only a JSON array with objects: "
            '{"arxiv_id": "...", "has_observational_catalog": true/false, "confidence": 0-1, '
            '"catalog_role": "...", "object_scope": "...", "evidence": "short evidence", '
            '"data_products": ["..."]}.'
        )
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": "You classify astrophysics papers for observational catalog content."},
                {"role": "user", "content": prompt + "\n\nItems:\n" + json.dumps(items, ensure_ascii=False)},
            ],
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        for attempt in range(1, self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read().decode("utf-8")
                break
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"LLM catalog assessor HTTP {exc.code}: {body}") from exc
            except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
                if attempt >= self.max_retries:
                    raise RuntimeError(f"LLM catalog assessor request failed after {self.max_retries} attempts: {exc}") from exc
                time.sleep(2 ** (attempt - 1))

        result = json.loads(raw)
        content = result["choices"][0]["message"]["content"]
        decisions = _extract_json_array(content)
        by_id: dict[str, CatalogAssessment] = {}
        for decision in decisions:
            if not isinstance(decision, dict):
                continue
            arxiv_id = str(decision.get("arxiv_id") or "").strip()
            if not arxiv_id:
                continue
            by_id[arxiv_id] = CatalogAssessment(
                has_observational_catalog=bool(decision.get("has_observational_catalog")),
                confidence=float(decision.get("confidence") or 0),
                catalog_role=str(decision.get("catalog_role") or "unclear").strip() or "unclear",
                object_scope=str(decision.get("object_scope") or "unclear").strip() or "unclear",
                evidence=str(decision.get("evidence") or "").strip(),
                data_products=_as_list(decision.get("data_products")),
            )
        return by_id


def papers_needing_assessment(record: dict[str, Any], *, force: bool = False) -> list[dict[str, Any]]:
    papers = record.get("papers") or []
    return [
        paper
        for paper in papers
        if isinstance(paper, dict) and (force or not paper.get("catalog_assessment"))
    ]


def batches(items: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
    size = max(1, batch_size)
    return [items[index : index + size] for index in range(0, len(items), size)]


def assessment_record(
    assessment: CatalogAssessment,
    *,
    method: str,
    model: str,
    assessed_at: datetime,
) -> dict[str, Any]:
    return {
        "has_observational_catalog": assessment.has_observational_catalog,
        "confidence": assessment.confidence,
        "catalog_role": assessment.catalog_role,
        "object_scope": assessment.object_scope,
        "evidence": assessment.evidence,
        "data_products": assessment.data_products,
        "method": method,
        "model": model,
        "assessed_at": assessed_at.isoformat(timespec="seconds"),
    }


def annotate_record(
    record: dict[str, Any],
    assessor: CatalogAssessor,
    *,
    batch_size: int,
    method: str,
    model: str,
    force: bool = False,
    assessed_at: datetime | None = None,
) -> dict[str, int]:
    pending = papers_needing_assessment(record, force=force)
    by_id = {str(paper.get("arxiv_id") or ""): paper for paper in pending}
    assessed_at = assessed_at or datetime.now()
    assessed = 0
    missing = 0

    for batch in batches(pending, batch_size):
        decisions = assessor.assess_batch(batch)
        for paper in batch:
            arxiv_id = str(paper.get("arxiv_id") or "")
            decision = decisions.get(arxiv_id)
            if decision is None:
                missing += 1
                continue
            by_id[arxiv_id]["catalog_assessment"] = assessment_record(
                decision,
                method=method,
                model=model,
                assessed_at=assessed_at,
            )
            assessed += 1

    papers = record.get("papers") or []
    catalog_count = sum(
        1
        for paper in papers
        if isinstance(paper, dict)
        and (paper.get("catalog_assessment") or {}).get("has_observational_catalog") is True
    )
    record["catalog_assessment_summary"] = {
        "assessed_count": sum(1 for paper in papers if isinstance(paper, dict) and paper.get("catalog_assessment")),
        "catalog_count": catalog_count,
        "method": method,
        "model": model,
        "updated_at": assessed_at.isoformat(timespec="seconds"),
    }
    return {
        "pending": len(pending),
        "assessed": assessed,
        "missing": missing,
        "catalog_count": catalog_count,
    }
