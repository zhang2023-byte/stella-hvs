"""Tests for shared environment-file loading."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from stella.lit.env import load_env_files


class EnvironmentFileTest(unittest.TestCase):
    def test_no_override_keeps_explicit_process_value(self) -> None:
        key = "STELLA_TEST_EXPLICIT_ENV_PRECEDENCE"
        old = os.environ.get(key)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                workspace = Path(tmp)
                (workspace / ".env").write_text(
                    f"{key}=from-repository\n",
                    encoding="utf-8",
                )
                os.environ[key] = "from-process"

                load_env_files(workspace, override=False)

                self.assertEqual(os.environ[key], "from-process")
        finally:
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old

    def test_no_override_loads_repository_value_when_process_is_unset(self) -> None:
        key = "STELLA_TEST_REPOSITORY_ENV_LOAD"
        old = os.environ.pop(key, None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                workspace = Path(tmp)
                (workspace / ".env").write_text(
                    f"{key}=from-repository\n",
                    encoding="utf-8",
                )

                load_env_files(workspace, override=False)

                self.assertEqual(os.environ[key], "from-repository")
        finally:
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old


if __name__ == "__main__":
    unittest.main()
