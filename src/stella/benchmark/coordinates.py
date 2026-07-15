"""Shared coordinate-unit spellings used by validation, identity, and scoring."""

from __future__ import annotations


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
