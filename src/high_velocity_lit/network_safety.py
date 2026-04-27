"""Network safety helpers for bounded external downloads."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse


class BlockedURL(ValueError):
    """Raised when a URL is outside Stella's allowed external-download boundary."""


BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain"}


def validate_public_http_url(url: str) -> tuple[bool, str]:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return False, "URL scheme must be http or https"
    if not parsed.hostname:
        return False, "URL host is missing"

    host = parsed.hostname.strip().strip("[]").rstrip(".").lower()
    if host in BLOCKED_HOSTNAMES or host.endswith(".localhost"):
        return False, "URL host is local"

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True, ""

    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        return False, "URL host resolves to a non-public IP literal"
    return True, ""


def require_public_http_url(url: str) -> None:
    allowed, reason = validate_public_http_url(url)
    if not allowed:
        raise BlockedURL(reason)
