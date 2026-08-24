"""Paper-visible identifier recognition for the contribution roster."""

from __future__ import annotations

import re
from typing import Any

from stella.lit.gaia_ids import parse_gaia_source_id

GAIA_RELEASE_MENTION_RE = re.compile(r"Gaia\s+(E?DR\d+)\b", re.IGNORECASE)
BARE_GAIA_SOURCE_ID_RE = re.compile(r"^\d{19}$")


def manuscript_gaia_release(original_texts: dict[str, str]) -> str | None:
    """the single Gaia release mentioned across the included manuscript.

    Returns the release only when every Gaia mention names the same one;
    multi-release or release-free manuscripts yield no inference.
    """

    releases = {
        match.group(1).upper()
        for text in original_texts.values()
        for match in GAIA_RELEASE_MENTION_RE.finditer(text)
    }
    return releases.pop() if len(releases) == 1 else None


def recognize_identifier(value: str, bare_release: str | None) -> dict[str, Any]:
    """Program-owned identifier typing."""

    gaia = parse_gaia_source_id(value)
    if gaia is not None:
        return {"kind": "gaia", "release": gaia.release, "source_id": gaia.source_id}
    if bare_release and BARE_GAIA_SOURCE_ID_RE.match(value.strip()):
        return {
            "kind": "gaia",
            "release": bare_release,
            "source_id": value.strip(),
            "context_inferred": True,
        }
    return {"kind": "other"}
