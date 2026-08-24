"""Shared coordinate-unit spellings used by validation, identity, and scoring."""

from __future__ import annotations

import re

UNICODE_SIGN_TRANSLATION = str.maketrans({"−": "-", "﹣": "-", "－": "-", "＋": "+"})



DEGREE_UNIT_ALIASES = frozenset(
    {
        "deg",
        "degree",
        "degrees",
        "angular degree",
        "angular degrees",
        "d",
        "dms",
        "°",
    }
)

HOURANGLE_UNIT_ALIASES = frozenset(
    {
        "hourangle",
        "hour angle",
        "hour",
        "hours",
        "h",
        "hms",
    }
)


# Unit alias sets used by coordinate parsing.
HOURANGLE_UNITS = HOURANGLE_UNIT_ALIASES
DEGREE_UNITS = DEGREE_UNIT_ALIASES


def _coordinate_value_degrees(field: str, value: str, unit: str) -> float | None:
    plain = _parse_plain_number(value)
    unit_normalized = unit.strip().lower()
    if plain is not None:
        if field == "observed_phase_space.ra" and unit_normalized in HOURANGLE_UNITS:
            return plain * 15.0
        return plain
    sexagesimal = _parse_sexagesimal_components(value)
    if sexagesimal is None:
        return None
    if field == "observed_phase_space.ra" and unit_normalized not in DEGREE_UNITS:
        return sexagesimal * 15.0
    return sexagesimal


def _parse_plain_number(text: str) -> float | None:
    try:
        return float(_normalize_number_text(text))
    except ValueError:
        return None


def _normalize_number_text(text: str) -> str:
    return text.translate(UNICODE_SIGN_TRANSLATION).strip()


def _parse_sexagesimal_components(text: str) -> float | None:
    normalized = _normalize_number_text(text)
    if not normalized:
        return None
    sign = -1.0 if normalized.startswith("-") else 1.0
    if normalized[0] in "+-":
        normalized = normalized[1:]
    for marker in ("h", "H", "d", "D", "m", "M", "°", "'"):
        normalized = normalized.replace(marker, ":")
    normalized = normalized.replace('"', "").replace("s", "").replace("S", "")
    normalized = re.sub(r"\s+", ":", normalized)
    normalized = re.sub(r":+", ":", normalized).strip(":")
    parts_text = normalized.split(":")
    if len(parts_text) not in (2, 3):
        return None
    if not all(
        re.fullmatch(r"(?:\d+(?:\.\d*)?|\.\d+)", part)
        for part in parts_text
    ):
        return None
    parts = [float(part) for part in parts_text]
    if parts[1] >= 60.0 or (len(parts) == 3 and parts[2] >= 60.0):
        return None
    magnitude = parts[0] + parts[1] / 60.0
    if len(parts) == 3:
        magnitude += parts[2] / 3600.0
    return sign * magnitude
