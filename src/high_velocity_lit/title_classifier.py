"""Title-only paper relevance classifiers."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .filters import clean_text


TITLE_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("hypervelocity stars", re.compile(r"\bhyper[-\s]?velocity\s+stars?\b|\bHVSs?\b", re.I)),
    ("high-velocity stars", re.compile(r"\bhigh[-\s]?velocity\s+stars?\b", re.I)),
    ("runaway stars", re.compile(r"\b(?:OB\s+)?runaway\s+stars?\b", re.I)),
    ("unbound or escaping stars", re.compile(r"\b(?:unbound|escaping|ejected)\s+stars?\b", re.I)),
    ("stellar escapers", re.compile(r"\bstellar\s+escapers?\b|\bwalkaway\s+stars?\b", re.I)),
]


@dataclass(frozen=True)
class TitleDecision:
    include: bool
    confidence: float
    reason: str
    label: str = "unknown"


def heuristic_title_decision(title: str) -> TitleDecision:
    text = clean_text(title)
    matches = [label for label, pattern in TITLE_RULES if pattern.search(text)]
    if matches:
        return TitleDecision(True, 0.75, "Title matched: " + ", ".join(matches), "heuristic")
    return TitleDecision(False, 0.55, "Title does not explicitly indicate high-velocity/runaway stars.", "heuristic")


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
        raise ValueError("LLM classifier did not return a JSON array")
    return data


class LLMTitleClassifier:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float = 0.0,
        timeout: int = 60,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout

    def classify_batch(self, papers: list[dict[str, Any]]) -> dict[str, TitleDecision]:
        items = [
            {
                "arxiv_id": paper.get("arxiv_id") or paper.get("id"),
                "title": clean_text(paper.get("title")),
                "categories": paper.get("categories") or [],
            }
            for paper in papers
        ]
        prompt = (
            "Classify arXiv paper titles for a literature search on high-velocity stars. "
            "Include papers whose title likely concerns hypervelocity stars, high-velocity stars, runaway stars, "
            "OB runaway stars, unbound/escaping/ejected stars, stellar escapers, walkaway stars, or direct mechanisms, "
            "observations, catalogues, origins, or kinematics of those stellar populations. "
            "Be inclusive when the title strongly suggests the topic, because the next step will fetch a brief. "
            "Exclude titles about compact/neutron/dark/radiating stars, impacts/cratering, generic binary stars, "
            "galaxies/AGN simulations, or ordinary stellar populations unless they clearly involve high-velocity/runaway stars. "
            "Use only the title and categories. Return only a JSON array with objects: "
            '{"arxiv_id": "...", "include": true/false, "confidence": 0-1, "reason": "short reason", "label": "short label"}.'
        )
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": "You are a precise astrophysics literature triage classifier."},
                {"role": "user", "content": prompt + "\n\nItems:\n" + json.dumps(items, ensure_ascii=False)},
            ],
        }
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM classifier HTTP {exc.code}: {body}") from exc

        result = json.loads(raw)
        content = result["choices"][0]["message"]["content"]
        decisions = _extract_json_array(content)
        by_id: dict[str, TitleDecision] = {}
        for decision in decisions:
            if not isinstance(decision, dict):
                continue
            arxiv_id = str(decision.get("arxiv_id") or "").strip()
            if not arxiv_id:
                continue
            by_id[arxiv_id] = TitleDecision(
                include=bool(decision.get("include")),
                confidence=float(decision.get("confidence") or 0),
                reason=str(decision.get("reason") or "").strip(),
                label=str(decision.get("label") or "").strip() or "llm",
            )
        return by_id


def load_llm_api_key(explicit_key: str | None = None) -> str | None:
    if explicit_key:
        return explicit_key
    for key in ("LLM_API_KEY", "OPENAI_API_KEY", "DEEPXIV_AGENT_API_KEY"):
        value = os.environ.get(key)
        if value:
            return value
    return None
