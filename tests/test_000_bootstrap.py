"""Path bootstrap for flat ``unittest discover tests`` runs.

``python -m unittest discover tests`` imports each ``test_*.py`` module
directly (without importing the ``tests`` package), so this module -- the
first in sort order -- must ensure ``import stella`` resolves to this
checkout's ``src/`` tree instead of an editable installation pointing at
another checkout. It contains no tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = str(Path(__file__).resolve().parents[1] / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
