"""Deterministic compressed-range expansion.

The model submits a qualifying range group as a verbatim manuscript string
(e.g. "HVS1,4-10,12-24 and others"); this module expands that string into
individual identifiers as a pure, auditable function. Anything outside the
deterministic grammar is an error, never a guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_RANGE_SPAN = 50

_OTHERS_RE = re.compile(r"^(?:and\s+)?others$", re.IGNORECASE)
_TRAILING_OTHERS_RE = re.compile(r"[,]?\s*(?:and\s+)?others$", re.IGNORECASE)
_BARE_NUM_RE = re.compile(r"^\d+$")
_BARE_RANGE_RE = re.compile(r"^(?P<start>\d+)\s*[-–—]\s*(?P<end>\d+)$")
_PREFIXED_RANGE_RE = re.compile(
    r"^(?P<prefix>\D+?)(?P<start>\d+)\s*[-–—]\s*(?P<end>\d+)$"
)
_FULL_RE = re.compile(r"^(?P<prefix>\D+?)(?P<num>\d+)$")


@dataclass
class RangeExpansion:
    identifiers: list[str]
    remainder: str | None
    error: str | None


def expand_range_notation(text: str, *, max_span: int = MAX_RANGE_SPAN) -> RangeExpansion:
    """Expand one compressed range notation into individual identifiers.

    A trailing "and others" (with or without a comma) is recorded as the
    unidentifiable remainder before comma-splitting. Remaining segments: a
    full form ("HVS1") sets or replaces the shared prefix, a bare number
    ("4") appends to the current prefix, and a range ("4-10" or
    "LAMOST-HVS1-3") expands inclusively.
    """

    remainder: str | None = None
    tail = _TRAILING_OTHERS_RE.search(text)
    if tail:
        remainder = tail.group(0).lstrip(", ").strip() or "others"
        text = text[: tail.start()]

    identifiers: list[str] = []
    prefix = ""
    for raw_segment in text.split(","):
        segment = raw_segment.strip()
        if not segment:
            return RangeExpansion([], None, "empty segment")
        match = _PREFIXED_RANGE_RE.match(segment) or _BARE_RANGE_RE.match(segment)
        if match:
            new_prefix = match.groupdict().get("prefix")
            if new_prefix:
                prefix = new_prefix.strip()
            if not prefix:
                return RangeExpansion([], None, f"range segment {segment!r} has no prefix")
            start, end = int(match.group("start")), int(match.group("end"))
            if end < start:
                return RangeExpansion([], None, f"descending range {segment!r}")
            if end - start + 1 > max_span:
                return RangeExpansion(
                    [], None, f"range span of {segment!r} exceeds {max_span}"
                )
            identifiers.extend(f"{prefix}{number}" for number in range(start, end + 1))
            continue
        if _BARE_NUM_RE.match(segment):
            if not prefix:
                return RangeExpansion([], None, f"bare segment {segment!r} has no prefix")
            identifiers.append(f"{prefix}{segment}")
            continue
        full = _FULL_RE.match(segment)
        if full:
            prefix = full.group("prefix").strip()
            identifiers.append(f"{prefix}{full.group('num')}")
            continue
        return RangeExpansion([], None, f"unparseable segment {segment!r}")
    if not identifiers:
        return RangeExpansion([], remainder, "no expandable identifiers")
    return RangeExpansion(identifiers, remainder, None)
