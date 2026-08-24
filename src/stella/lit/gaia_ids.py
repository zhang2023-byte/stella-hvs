"""Gaia source identifier parsing shared by lit extraction and dynamics."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

GAIA_SOURCE_ID_RE = re.compile(r"^Gaia\s+((?:E)?DR\d+)\s+(\d+)$", re.IGNORECASE)


@dataclass(frozen=True)
class GaiaSourceId:
    release: str
    source_id: str
    raw: str

    @property
    def release_family(self) -> str:
        return "DR3" if self.release in {"DR3", "EDR3"} else self.release

    @property
    def canonical_value(self) -> str:
        return f"Gaia {self.release_family} {self.source_id}"


def parse_gaia_source_id(value: Any) -> GaiaSourceId | None:
    text = " ".join(str(value or "").strip().split())
    match = GAIA_SOURCE_ID_RE.match(text)
    if not match:
        return None
    return GaiaSourceId(release=match.group(1).upper(), source_id=match.group(2), raw=text)
