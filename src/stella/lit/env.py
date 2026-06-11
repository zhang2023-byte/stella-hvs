"""Shared environment loading helpers for Stella CLI scripts."""

from __future__ import annotations

import os
from pathlib import Path


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value:
            values[key] = value
    return values


def load_env_files(workspace: Path) -> None:
    paths = (Path.home() / ".env", workspace / ".env", Path.cwd() / ".env")
    try:
        from dotenv import load_dotenv
    except ImportError:
        for path in paths:
            for key, value in _read_env_file(path).items():
                os.environ[key] = value
        return

    for path in paths:
        if path.exists():
            load_dotenv(path, override=True)


def env_value(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default
