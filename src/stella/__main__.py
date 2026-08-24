"""Entry point for ``python -m stella``."""

from __future__ import annotations

import sys

from stella.cli import main

if __name__ == "__main__":
    sys.exit(main())
