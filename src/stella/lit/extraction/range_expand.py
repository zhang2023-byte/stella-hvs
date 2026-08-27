"""Strict deterministic expansion for paper-visible identifier ranges."""

from __future__ import annotations

import re
from dataclasses import dataclass

_DASH = r"(?:--|[-\u2013\u2014])"
_FIRST_SEGMENT_RE = re.compile(
    rf"^(?P<prefix>.*?\D)(?P<start>\d+)(?:{_DASH}(?P<end>\d+))?$"
)
_FOLLOWING_SEGMENT_RE = re.compile(
    rf"^(?P<start>\d+)(?:{_DASH}(?P<end>\d+))?$"
)
_TRAILING_REMAINDER_RE = re.compile(r"\s+(?P<remainder>and\s+others)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class RangeExpansion:
    """One all-or-nothing parse of a compressed identifier notation."""

    identifiers: list[str]
    remainder: str | None = None
    error: str | None = None


def _failure(message: str, remainder: str | None = None) -> RangeExpansion:
    return RangeExpansion(identifiers=[], remainder=remainder, error=message)


def expand_range_notation(
    text: str,
    *,
    max_members: int = 50,
) -> RangeExpansion:
    """Expand one stable-prefix integer list/range, or fail without members.

    Accepted examples include ``OBJ1,4-6,09-10`` and ``CAT-X001-003``.
    Only a trailing ``and others`` remainder is recognized, and it is never
    interpreted as an identifier.
    """

    if not isinstance(text, str) or not text.strip():
        return _failure("range notation must be a non-empty string")
    if not isinstance(max_members, int) or isinstance(max_members, bool) or max_members < 1:
        return _failure("max_members must be a positive integer")

    notation = text.strip()
    remainder: str | None = None
    remainder_match = _TRAILING_REMAINDER_RE.search(notation)
    if remainder_match:
        remainder = remainder_match.group("remainder")
        notation = notation[: remainder_match.start()].rstrip()
    if not notation:
        return _failure("range notation has no enumerable members", remainder)

    segments = notation.split(",")
    if any(not segment.strip() for segment in segments):
        return _failure("range notation contains an empty segment", remainder)

    first = _FIRST_SEGMENT_RE.fullmatch(segments[0].strip())
    if first is None:
        return _failure(
            "first segment must contain a stable non-numeric prefix and integer",
            remainder,
        )
    prefix = first.group("prefix")
    if not any(character.isalpha() for character in prefix):
        return _failure(
            "stable identifier prefix must contain a letter",
            remainder,
        )
    if prefix.endswith((".", ";", ":")):
        return _failure("stable identifier prefix has an unsupported suffix", remainder)

    identifiers: list[str] = []
    seen: set[str] = set()

    def append_segment(start_text: str, end_text: str | None) -> str | None:
        start = int(start_text)
        end = int(end_text) if end_text is not None else start
        if end < start:
            return "identifier ranges must be ascending"
        if end_text is None:
            width = len(start_text) if start_text.startswith("0") else 0
        elif start_text.startswith("0"):
            if len(start_text) != len(end_text):
                return "zero-padded range bounds must use the same width"
            width = len(start_text)
        elif end_text.startswith("0"):
            return "zero-padded range bounds must use the same width"
        else:
            width = 0
        for number in range(start, end + 1):
            suffix = str(number).zfill(width) if width else str(number)
            identifier = f"{prefix}{suffix}"
            normalized = identifier.casefold()
            if normalized in seen:
                return f"range notation repeats identifier {identifier!r}"
            if len(identifiers) >= max_members:
                return f"range notation exceeds the {max_members}-member limit"
            seen.add(normalized)
            identifiers.append(identifier)
        return None

    error = append_segment(first.group("start"), first.group("end"))
    if error:
        return _failure(error, remainder)

    for raw_segment in segments[1:]:
        segment = raw_segment.strip()
        match = _FOLLOWING_SEGMENT_RE.fullmatch(segment)
        if match is None:
            return _failure(
                "following segments must be bare integers or integer ranges; prefix resets and suffixes are unsupported",
                remainder,
            )
        error = append_segment(match.group("start"), match.group("end"))
        if error:
            return _failure(error, remainder)

    return RangeExpansion(identifiers=identifiers, remainder=remainder)
