"""Load the maintained HVS validator without importing a script as a package."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def load_hvs_validator(workspace: Path):
    """Import the workspace-pinned validator module."""

    script = workspace / "scripts" / "validate_hvs_candidates.py"
    spec = importlib.util.spec_from_file_location("stella_hvs_validator", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load validator from {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
