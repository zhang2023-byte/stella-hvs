"""Deterministic candidate identity matching for benchmark scoring.

Matches paper-level HVS candidate records across two extractions of the same
paper (for example expert gold vs an AI run) in three strictly ordered tiers:

1. Gaia source id: same data release and same numeric id.
2. Name alias: any normalized paper-visible identifier shared by both sides.
3. Coordinates: angular separation within a configurable tolerance.

Conflicting Gaia ids in the same data release veto a match outright, even if
names or coordinates agree. The default coordinate tolerance is a placeholder
pending expert confirmation (proper-motion over epoch differences can exceed
it for nearby fast stars).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

DEFAULT_COORD_TOLERANCE_ARCSEC = 1.0

GAIA_ID_RE = re.compile(r"^\s*Gaia\s+(E?DR[0-9])\s+([0-9]+)\s*$", re.IGNORECASE)
NAME_NORMALIZE_RE = re.compile(r"[\s\-_]+")


def parse_gaia_id(text: Any) -> tuple[str, str] | None:
    """Parse a strict ``Gaia DR3 123...`` identifier into (release, id)."""

    if not isinstance(text, str):
        return None
    match = GAIA_ID_RE.match(text)
    if not match:
        return None
    return match.group(1).upper(), match.group(2)


def normalize_name(text: Any) -> str:
    """Normalize a paper-visible identifier for alias comparison."""

    if not isinstance(text, str):
        return ""
    return NAME_NORMALIZE_RE.sub("", text.strip().upper())


def _coordinate_to_degrees(record: Any, *, is_ra: bool) -> float | None:
    if not isinstance(record, dict):
        return None
    value = record.get("value")
    if not isinstance(value, str) or not value.strip() or value.strip().lower() == "unknown":
        return None
    coordinate_format = str(record.get("coordinate_format") or "")
    unit = str(record.get("unit") or "").strip().lower()
    text = value.strip()
    try:
        if coordinate_format == "decimal_degrees" or (coordinate_format == "" and _is_plain_number(text)):
            degrees = float(text)
            if unit in {"hourangle", "hour", "h"}:
                degrees *= 15.0
            return degrees
        parts = [float(part) for part in re.split(r"[:\shdms°'\"]+", text) if part not in ("", "+", "-")]
        sign = -1.0 if text.lstrip().startswith("-") else 1.0
        magnitude = abs(parts[0]) + (parts[1] if len(parts) > 1 else 0.0) / 60.0 + (parts[2] if len(parts) > 2 else 0.0) / 3600.0
        if coordinate_format == "sexagesimal_hms" or (is_ra and unit in {"hourangle", "hour", "h"}):
            return sign * magnitude * 15.0
        if coordinate_format in {"sexagesimal_dms", "sexagesimal_colon"}:
            if is_ra and unit in {"hourangle", "hour", "h"}:
                return sign * magnitude * 15.0
            return sign * magnitude
        return None
    except (ValueError, IndexError):
        return None


def _is_plain_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def angular_separation_arcsec(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Great-circle separation in arcseconds (haversine, numerically stable)."""

    ra1_r, dec1_r, ra2_r, dec2_r = map(math.radians, (ra1, dec1, ra2, dec2))
    sin_ddec = math.sin((dec2_r - dec1_r) / 2.0)
    sin_dra = math.sin((ra2_r - ra1_r) / 2.0)
    h = sin_ddec**2 + math.cos(dec1_r) * math.cos(dec2_r) * sin_dra**2
    return math.degrees(2.0 * math.asin(min(1.0, math.sqrt(h)))) * 3600.0


@dataclass
class CandidateIdentity:
    """Identity facets extracted from one v0.1 candidate record."""

    record_id: str = ""
    gaia: tuple[str, str] | None = None
    names: set[str] = field(default_factory=set)
    ra_deg: float | None = None
    dec_deg: float | None = None


def identity_from_candidate(candidate: dict[str, Any]) -> CandidateIdentity:
    identifiers = candidate.get("identifiers") if isinstance(candidate.get("identifiers"), dict) else {}
    names: set[str] = set()
    for entry in identifiers.get("all") or []:
        if isinstance(entry, dict):
            normalized = normalize_name(entry.get("value"))
            if normalized and parse_gaia_id(entry.get("value")) is None:
                names.add(normalized)
    paper_candidate_id = normalize_name(identifiers.get("paper_candidate_id"))
    if paper_candidate_id and parse_gaia_id(identifiers.get("paper_candidate_id")) is None:
        names.add(paper_candidate_id)
    core = candidate.get("core") if isinstance(candidate.get("core"), dict) else {}
    phase_space = core.get("observed_phase_space") if isinstance(core.get("observed_phase_space"), dict) else {}
    return CandidateIdentity(
        record_id=str(identifiers.get("record_id") or ""),
        gaia=parse_gaia_id(identifiers.get("gaia_source_id")),
        names=names,
        ra_deg=_coordinate_to_degrees(phase_space.get("ra"), is_ra=True),
        dec_deg=_coordinate_to_degrees(phase_space.get("dec"), is_ra=False),
    )


@dataclass
class MatchResult:
    matched: bool
    method: str = ""
    detail: str = ""


def match_identities(
    left: CandidateIdentity,
    right: CandidateIdentity,
    *,
    coord_tolerance_arcsec: float = DEFAULT_COORD_TOLERANCE_ARCSEC,
) -> MatchResult:
    if left.gaia and right.gaia and left.gaia[0] == right.gaia[0]:
        if left.gaia[1] == right.gaia[1]:
            return MatchResult(True, "gaia_id", f"Gaia {left.gaia[0]} {left.gaia[1]}")
        return MatchResult(False, "gaia_conflict", f"{left.gaia} vs {right.gaia}")
    shared = left.names & right.names
    if shared:
        return MatchResult(True, "alias", sorted(shared)[0])
    if None not in (left.ra_deg, left.dec_deg, right.ra_deg, right.dec_deg):
        separation = angular_separation_arcsec(left.ra_deg, left.dec_deg, right.ra_deg, right.dec_deg)
        if separation <= coord_tolerance_arcsec:
            return MatchResult(True, "coordinates", f"{separation:.3f} arcsec")
        return MatchResult(False, "coordinates_too_far", f"{separation:.3f} arcsec")
    return MatchResult(False, "no_evidence", "no shared Gaia id, alias, or usable coordinates")


def match_candidate_sets(
    left_candidates: list[dict[str, Any]],
    right_candidates: list[dict[str, Any]],
    *,
    coord_tolerance_arcsec: float = DEFAULT_COORD_TOLERANCE_ARCSEC,
) -> dict[str, Any]:
    """Greedy one-to-one matching of two candidate lists, tier by tier.

    All Gaia-id matches are made first, then alias matches, then the closest
    coordinate pairs within tolerance. Returns matched pairs (with method and
    detail) plus unmatched record ids on each side.
    """

    left_ids = [identity_from_candidate(candidate) for candidate in left_candidates]
    right_ids = [identity_from_candidate(candidate) for candidate in right_candidates]
    unmatched_left = set(range(len(left_ids)))
    unmatched_right = set(range(len(right_ids)))
    pairs: list[dict[str, Any]] = []

    def take(left_index: int, right_index: int, result: MatchResult) -> None:
        unmatched_left.discard(left_index)
        unmatched_right.discard(right_index)
        pairs.append(
            {
                "left_record_id": left_ids[left_index].record_id,
                "right_record_id": right_ids[right_index].record_id,
                "method": result.method,
                "detail": result.detail,
            }
        )

    for tier in ("gaia_id", "alias"):
        for i in sorted(unmatched_left):
            for j in sorted(unmatched_right):
                result = match_identities(left_ids[i], right_ids[j], coord_tolerance_arcsec=coord_tolerance_arcsec)
                if result.matched and result.method == tier:
                    take(i, j, result)
                    break

    coordinate_candidates: list[tuple[float, int, int, MatchResult]] = []
    for i in sorted(unmatched_left):
        for j in sorted(unmatched_right):
            result = match_identities(left_ids[i], right_ids[j], coord_tolerance_arcsec=coord_tolerance_arcsec)
            if result.matched and result.method == "coordinates":
                coordinate_candidates.append((float(result.detail.split()[0]), i, j, result))
    for _, i, j, result in sorted(coordinate_candidates):
        if i in unmatched_left and j in unmatched_right:
            take(i, j, result)

    return {
        "pairs": pairs,
        "unmatched_left": [left_ids[i].record_id for i in sorted(unmatched_left)],
        "unmatched_right": [right_ids[j].record_id for j in sorted(unmatched_right)],
        "coord_tolerance_arcsec": coord_tolerance_arcsec,
    }
