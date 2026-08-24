"""Offline network tripwire for end-to-end tests.

Any attempt to open a socket inside a test guarded by ``netguard`` fails
immediately with a clear error instead of silently reaching a provider or
public endpoint.
"""

from __future__ import annotations

import socket
import unittest
import unittest.mock


def guard(test_case: unittest.TestCase) -> None:
    """Block socket creation for the duration of one test."""

    def _blocked(*args, **kwargs):
        raise AssertionError(
            "offline test attempted a real network connection"
        )

    patch = unittest.mock.patch.object(socket, "socket", _blocked)
    patch.start()
    test_case.addCleanup(patch.stop)
