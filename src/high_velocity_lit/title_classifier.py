"""Title-only paper relevance classifiers."""

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

WEAK_TITLE_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "stellar ejection mechanisms",
        re.compile(
            r"\bstellar\s+ejection\b|\bejection\s+velocities\b|\bstars?\s+ejected\s+from\b|"
            r"\bdynamically[-\s]?ejected\b|\bbinary\s+supernova\s+scenario\b|"
            r"\bcompact\s+object\s+binaries\b.{0,80}\b(?:ejection|detectability)\b|"
            r"\bejection\s+and\s+capture\s+dynamics\b",
            re.I,
        ),
    ),
    (
        "stellar escaper candidates",
        re.compile(
            r"\bpotential\s+escapers?\b|\bcluster\s+escapers?\b|\bstellar\s+escapers?\b|"
            r"\bglobular\s+cluster\s+(?:escapees?|escaped\s+stars?)\b|"
            r"\bstellar\s+escape\s+from\s+globular\s+clusters?\b|"
            r"\bescaped\s+stars?\b",
            re.I,
        ),
    ),
    (
        "runaway-related mechanisms",
        re.compile(
            r"\brunaway\b|\bwalkaway\b|\bbow[-\s]?shocks?\b|\bbowshock(?:s| nebulae)?\b|"
            r"\bsub[-\s]?cluster\s+mergers\b|\bfossils?\s+of\s+sub[-\s]?cluster\s+mergers\b",
            re.I,
        ),
    ),
    (
        "galactic-center dynamical origins",
        re.compile(
            r"\bS-star\s+cluster\b|"
            r"\b(?:galactic\s+cent(?:er|re)|Sgr\s*A\*?)\b.{0,120}\b(?:eject|origin|track\s*back|constraint|environment)\b|"
            r"\b(?:eject|origin|track\s*back|constraint|environment)\b.{0,120}\b(?:galactic\s+cent(?:er|re)|Sgr\s*A\*?)\b",
            re.I | re.S,
        ),
    ),
    (
        "stellar interactions in dense systems",
        re.compile(
            r"\bstellar\s+(?:collisions?|disruptions?)\b|"
            r"\bdisruptions?\s+of\s+stars\b|"
            r"\b(?:star|stellar|globular)\s+clusters?\b.{0,100}\b(?:ejections?|compact\s+object\s+encounters?|"
            r"intermediate[-\s]?mass\s+black\s+holes?|massive\s+black\s+hole\s+binary|sub[-\s]?cluster\s+mergers)\b|"
            r"\bintermediate[-\s]?mass\s+black\s+holes?\b.{0,80}\b(?:star|stellar|globular)\s+clusters?\b",
            re.I | re.S,
        ),
    ),
    (
        "high proper-motion or unusual kinematics",
        re.compile(
            r"\bhigh\s+proper[-\s]?motion\s+stars?\b|"
            r"\bproper\s+motions?\s+and\s+parallax(?:es)?\b.{0,80}\b(?:hyper[-\s]?velocity|high[-\s]?velocity)\b|"
            r"\bunusual\s+kinematics\b|"
            r"\bretrograde\s+stars?\b|"
            r"\bkinematically\s+(?:hot|outlying|perturbed)\b|"
            r"\bgalactic\s+space\s+velocities\b.{0,100}\b(?:high[-\s]?velocity|hyper[-\s]?velocity|runaway)\b",
            re.I | re.S,
        ),
    ),
    (
        "Hills mechanism and tidal binary disruption",
        re.compile(
            r"\bHills\s+mechanism\b|"
            r"\btidal\s+(?:separation|disruption)\s+of\s+binary\s+stars?\b|"
            r"\bbinary\s+disruption\s+by\s+massive\s+black\s+holes?\b|"
            r"\bbinaries\s+disrupted\s+by\s+a\s+massive\s+galactic\s+black\s+hole\b|"
            r"\bmassive\s+black\s+holes?\s+and\s+binaries\b|"
            r"\brestricted\s+(?:parabolic\s+)?(?:3|three)[-\s]?body\s+problem\b|"
            r"\brestricted\s+(?:3|three)[-\s]?body\s+encounters\b",
            re.I,
        ),
    ),
    (
        "external-galaxy or perturber origin clues",
        re.compile(
            r"\bstellar\s+migration\s+from\s+Andromeda\s+to\s+the\s+Milky\s+Way\b|"
            r"\b(?:Andromeda|M31|Sagittarius\s+Dwarf)\b"
            r".{0,120}\b(?:origin|eject|candidate|high[-\s]?velocity|hyper[-\s]?velocity)\b|"
            r"\b(?:Large\s+Magellanic\s+Cloud|LMC|galactic\s+bar)\b"
            r".{0,120}\b(?:hyper[-\s]?velocity|high[-\s]?velocity|runaway|unbound|ejected|fastest?)\b|"
            r"\b(?:trajectory|trajectories|origin|deflection|impact|eject|candidate)\b"
            r".{0,120}\b(?:Andromeda|M31|Sagittarius\s+Dwarf)\b",
            re.I | re.S,
        ),
    ),
    (
        "using high-velocity stars as probes",
        re.compile(
            r"\b(?:dark\s+matter\s+halo|galactic\s+halo|velocity\s+distribution)\b"
            r".{0,120}\b(?:hyper[-\s]?velocity|high[-\s]?velocity|extreme[-\s]?velocity)\s+stars?\b",
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
        return TitleDecision(True, 0.95, "Direct title match: " + ", ".join(direct_matches), "rule-direct")
    weak_matches = [label for label, pattern in WEAK_TITLE_RULES if pattern.search(text)]
    if weak_matches:
        return TitleDecision(True, 0.65, "Weak title match: " + ", ".join(weak_matches), "rule-weak")
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
        max_retries: int = 3,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries

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
