"""Test package bootstrap.

Ensure test runs inside a worktree or checkout import the ``stella`` package
from this repository's ``src/`` tree instead of any editable installation
that may point at a different checkout.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
