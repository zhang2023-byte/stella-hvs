"""Paper relevance classifiers for monthly title triage."""

from __future__ import annotations

import json
import os
import re
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .filters import clean_text
from .llm_options import apply_llm_request_options


DIRECT_TITLE_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("hypervelocity stars", re.compile(r"\bhyper[-\s]?velocity\s+stars?\b|\bHVSs?\b", re.I)),
    (
        "high-velocity or extreme-velocity stars",
        re.compile(
            r"\b(?:high|extreme)[-\s]?velocity\s+(?:[A-Za-z0-9+/-]+\s+){0,4}stars?\b|"
            r"\b(?:fastest|fast)\s+stars?\s+in\s+the\s+galax(?:y|ies)\b",
            re.I,
        ),
    ),
    ("runaway stars", re.compile(r"\b(?:hyper[-\s]?runaway|(?:OB|B[-\s]?type|O[-\s]?type)?\s*runaway)\s+stars?\b", re.I)),
    (
        "unbound, escaping, or ejected stars",
        re.compile(
            r"\b(?:unbound|escaping|ejected)\s+(?:[A-Za-z0-9+/-]+\s+){0,4}stars?\b|"
            r"\bstars?\s+ejected\s+(?:from|by)\b|"
            r"\bgalactic\s+cent(?:er|re)[-\s]?ejected\s+stars?\b|"
            r"\bSgr\s*A\*?.{0,80}\bstars?\s+ejected\b",
            re.I | re.S,
        ),
    ),
    ("stellar escapers", re.compile(r"\bstellar\s+escapers?\b|\bwalkaway\s+stars?\b", re.I)),
    (
        "high-velocity star surveys or candidates",
        re.compile(
            r"\b(?:candidate|candidates|survey|surveys|search|searching|census|catalog(?:ue)?)\b"
            r".{0,80}\b(?:hyper[-\s]?velocity|high[-\s]?velocity|extreme[-\s]?velocity|unbound)\s+"
            r"(?:[A-Za-z0-9+/-]+\s+){0,4}stars?\b",
            re.I | re.S,
        ),
    ),
]


@dataclass(frozen=True)
class TitleDecision:
    include: bool
    confidence: float
    reason: str
    label: str = "unknown"


def heuristic_title_decision(title: str) -> TitleDecision:
    text = clean_text(title)
    direct_matches = [label for label, pattern in DIRECT_TITLE_RULES if pattern.search(text)]
    if direct_matches:
        return TitleDecision(True, 0.95, "Rule-related title match: " + ", ".join(direct_matches), "rule-related")
    return TitleDecision(
        False,
        0.4,
        "Title does not contain a clear high-velocity-star rule match.",
        "no-clear-title-evidence",
    )


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
        thinking: str | None = None,
        reasoning_effort: str | None = None,
        temperature: float = 0.0,
        timeout: int = 60,
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

    def classify_batch(self, papers: list[dict[str, Any]]) -> dict[str, TitleDecision]:
        items = [
            {
                "arxiv_id": paper.get("arxiv_id") or paper.get("id"),
                "title": clean_text(paper.get("title")),
                "abstract": clean_text(paper.get("abstract")),
                "categories": paper.get("categories") or [],
            }
            for paper in papers
        ]
        prompt = (
            "Classify arXiv search results for a literature search on high-velocity stars. "
            "Use the title, abstract, and categories. Include papers that likely concern hypervelocity stars, "
            "high-velocity stars, runaway stars, "
            "OB runaway stars, unbound/escaping/ejected stars, stellar escapers, walkaway stars, or direct mechanisms, "
            "observations, catalogues, origins, or kinematics of those stellar populations. "
            "Be inclusive when the title or abstract strongly suggests the topic. "
            "Exclude titles about compact/neutron/dark/radiating stars, impacts/cratering, generic binary stars, "
            "galaxies/AGN simulations, or ordinary stellar populations unless they clearly involve high-velocity/runaway stars. "
            "Return only a JSON array with objects: "
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
        apply_llm_request_options(
            payload,
            thinking=self.thinking,
            reasoning_effort=self.reasoning_effort,
        )
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
        for attempt in range(1, self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read().decode("utf-8")
                break
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"LLM classifier HTTP {exc.code}: {body}") from exc
            except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
                if attempt >= self.max_retries:
                    raise RuntimeError(f"LLM classifier request failed after {self.max_retries} attempts: {exc}") from exc
                time.sleep(2 ** (attempt - 1))

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
