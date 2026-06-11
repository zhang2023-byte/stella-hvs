"""LLM-assisted assessment of observational catalog content in note records."""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, Sequence

from .filters import clean_text
from .llm_options import apply_llm_request_options


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


class DeepXivPaperReader(Protocol):
    def enrich_paper(self, paper: dict[str, Any]) -> dict[str, Any]:
        """Collect DeepXiv context for catalog assessment."""


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


def _first_paragraph(text: Any) -> str:
    cleaned = clean_text(text)
    paragraphs = [part.strip() for part in cleaned.split("\n\n") if part.strip()]
    return paragraphs[0] if paragraphs else ""


def _last_paragraph(text: Any) -> str:
    cleaned = clean_text(text)
    paragraphs = [part.strip() for part in cleaned.split("\n\n") if part.strip()]
    return paragraphs[-1] if paragraphs else ""


def _deepxiv_brief_context(raw: dict[str, Any] | None, *, error: str | None, fetched_at: datetime) -> dict[str, Any]:
    raw = raw or {}
    return {
        "source": "deepxiv",
        "fetched": bool(raw),
        "error": error,
        "tldr": clean_text(raw.get("tldr")),
        "keywords": _as_list(raw.get("keywords")),
        "citations": raw.get("citations"),
        "fetched_at": fetched_at.isoformat(timespec="seconds"),
    }


def _persist_deepxiv_brief(paper: dict[str, Any], brief_context: dict[str, Any]) -> None:
    context = paper.setdefault("catalog_assessment_context", {})
    if not isinstance(context, dict):
        context = {}
        paper["catalog_assessment_context"] = context
    context["deepxiv_brief"] = brief_context


def _assessment_runtime_context(paper: dict[str, Any]) -> dict[str, Any]:
    return (paper.get("_catalog_assessment_runtime") or {}) if isinstance(paper, dict) else {}


class DeepXivCLIReader:
    def __init__(
        self,
        *,
        command: Sequence[str] | None = None,
        timeout: int = 120,
    ) -> None:
        self.command = list(command) if command is not None else self._default_command()
        self.timeout = timeout

    def _default_command(self) -> list[str]:
        executable = Path(sys.executable).resolve().with_name("deepxiv")
        if executable.exists():
            return [str(executable)]
        found = shutil.which("deepxiv")
        return [found] if found else ["deepxiv"]

    def _run_json(self, args: Sequence[str]) -> dict[str, Any]:
        command = [*self.command, *args]
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        return json.loads(completed.stdout)

    def _read_brief(self, arxiv_id: str, *, fetched_at: datetime) -> dict[str, Any]:
        try:
            payload = self._run_json(["paper", arxiv_id, "--brief", "--format", "json"])
            return _deepxiv_brief_context(payload, error=None, fetched_at=fetched_at)
        except Exception as exc:
            return _deepxiv_brief_context(None, error=f"{type(exc).__name__}: {exc}", fetched_at=fetched_at)

    def _section_names(self, arxiv_id: str) -> list[str]:
        try:
            payload = self._run_json(["paper", arxiv_id, "--head", "--format", "json"])
        except Exception:
            return []
        sections = payload.get("sections") or []
        names: list[str] = []
        for section in sections:
            if not isinstance(section, dict):
                continue
            name = str(section.get("name") or "").strip()
            if name:
                names.append(name)
        return names

    def _section_content(self, arxiv_id: str, section_name: str) -> str:
        payload = self._run_json(["paper", arxiv_id, "--section", section_name, "--format", "json"])
        return str(payload.get("content") or "")

    def enrich_paper(self, paper: dict[str, Any]) -> dict[str, Any]:
        arxiv_id = str(paper.get("arxiv_id") or "").strip()
        fetched_at = datetime.now()
        if not arxiv_id:
            return {
                "deepxiv_brief": _deepxiv_brief_context(
                    None,
                    error="missing arXiv ID",
                    fetched_at=fetched_at,
                ),
                "introduction_last_paragraph": "",
                "sections": [],
            }

        brief_context = self._read_brief(arxiv_id, fetched_at=fetched_at)
        section_names = self._section_names(arxiv_id)
        introduction_last_paragraph = ""
        section_summaries: list[dict[str, str]] = []
        for section_name in section_names:
            try:
                content = self._section_content(arxiv_id, section_name)
            except Exception:
                continue
            first_paragraph = _first_paragraph(content)
            if first_paragraph:
                section_summaries.append(
                    {
                        "title": section_name,
                        "first_paragraph": first_paragraph,
                    }
                )
            if section_name.strip().lower() == "introduction" and not introduction_last_paragraph:
                introduction_last_paragraph = _last_paragraph(content)

        return {
            "deepxiv_brief": brief_context,
            "introduction_last_paragraph": introduction_last_paragraph,
            "sections": section_summaries,
        }


def _paper_payload(paper: dict[str, Any]) -> dict[str, Any]:
    abstract = paper.get("abstract") or {}
    context = paper.get("catalog_assessment_context") or {}
    brief = (context.get("deepxiv_brief") or {}) if isinstance(context, dict) else {}
    runtime = _assessment_runtime_context(paper)
    return {
        "arxiv_id": paper.get("arxiv_id"),
        "title": clean_text(paper.get("title")),
        "categories": paper.get("categories") or [],
        "abstract": clean_text(abstract.get("text")),
        "deepxiv_brief_tldr": clean_text(brief.get("tldr")),
        "deepxiv_brief_keywords": brief.get("keywords") or [],
        "introduction_last_paragraph": clean_text(runtime.get("introduction_last_paragraph")),
        "sections": runtime.get("sections") or [],
    }


class LLMCatalogAssessor:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        thinking: str | None = None,
        reasoning_effort: str | None = None,
        temperature: float = 0.0,
        timeout: int = 90,
        max_retries: int = 3,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.thinking = thinking
        self.reasoning_effort = reasoning_effort
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries

    def assess_batch(self, papers: list[dict[str, Any]]) -> dict[str, CatalogAssessment]:
        items = [_paper_payload(paper) for paper in papers]
        prompt = (
            "Assess whether each high-velocity-star literature record likely contains real observational "
            "stellar data or a catalog/sample/list of high-velocity, hypervelocity, runaway, unbound, "
            "escaping, or ejected star objects. Use only the provided title, abstract, DeepXiv brief TLDR, "
            "DeepXiv brief keywords, introduction last paragraph, section titles, section first paragraphs, "
            "and categories.\n\n"
            "Return has_observational_catalog=true when the paper appears to present, compile, use, or "
            "analyze object-level observational data for actual stellar objects, such as source IDs, "
            "coordinates, proper motions, parallaxes, radial velocities, spectra, abundances, candidate "
            "lists, follow-up observations, or survey/catalog tables. This includes single-object discovery "
            "papers and multi-object candidate catalogs.\n\n"
            "Be conservative. Default to false unless the provided evidence points to actual observed stellar "
            "objects or an explicit object-level catalog/sample. Mentions of surveys, archives, methods, "
            "simulations, dynamical analyses, or generic data products are not enough on their own.\n\n"
            "Return false for purely theoretical papers, simulations without object-level observed stars, "
            "dynamical mechanism studies, generic survey/data-release papers, software/method papers, or "
            "papers that only mention high-velocity stars as motivation without an apparent object-level "
            "observational sample. Also return false when the paper studies gas clouds, star formation, "
            "or Galactic structure unless it clearly includes object-level high-velocity-star measurements "
            "or a star sample.\n\n"
            "A paper that only proposes candidates indirectly, discusses selection strategy, or analyzes "
            "population-level trends without identifiable observed objects should remain false. If the evidence "
            "is ambiguous, keep has_observational_catalog=false and use lower confidence.\n\n"
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
        apply_llm_request_options(
            payload,
            thinking=self.thinking,
            reasoning_effort=self.reasoning_effort,
        )
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


def papers_needing_assessment(record: dict[str, Any]) -> list[dict[str, Any]]:
    papers = record.get("papers") or []
    return [paper for paper in papers if isinstance(paper, dict)]


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
    paper_reader: DeepXivPaperReader | None = None,
    assessed_at: datetime | None = None,
) -> dict[str, int]:
    pending = papers_needing_assessment(record)
    by_id = {str(paper.get("arxiv_id") or ""): paper for paper in pending}
    assessed_at = assessed_at or datetime.now()
    assessed = 0
    missing = 0
    reader = paper_reader or DeepXivCLIReader()

    for batch in batches(pending, batch_size):
        enriched_batch: list[dict[str, Any]] = []
        for paper in batch:
            enriched = reader.enrich_paper(paper)
            _persist_deepxiv_brief(paper, enriched.get("deepxiv_brief") or {})
            paper_for_assessment = dict(paper)
            paper_for_assessment["_catalog_assessment_runtime"] = {
                "introduction_last_paragraph": enriched.get("introduction_last_paragraph") or "",
                "sections": enriched.get("sections") or [],
            }
            enriched_batch.append(paper_for_assessment)

        decisions = assessor.assess_batch(enriched_batch)
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
