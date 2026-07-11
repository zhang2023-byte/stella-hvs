from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("migrate_private_gold_schema", ROOT / "scripts" / "migrate_private_gold_schema.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PrivateGoldMigrationTest(unittest.TestCase):
    def test_draft_envelopes_are_migrated_without_validating_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "draft_x.json"
            path.write_text(json.dumps({
                "draft_schema": "stella.benchmark_gold_form_draft.v0.1",
                "saved_at": "2026-01-01T00:00:00Z",
                "payload": {"schema_version": "stella.benchmark_gold_annotation.v0.1", "notes": "keep"},
            }))
            result = json.loads(MODULE.migrate_draft(path))
            self.assertEqual(result["schema"], {"name": "benchmark.gold_form_draft", "version": 1})
            self.assertEqual(result["payload"]["schema"], {"name": "benchmark.gold_annotation", "version": 1})
            self.assertEqual(result["payload"]["notes"], "keep")
            self.assertNotIn("draft_schema", result)


if __name__ == "__main__":
    unittest.main()
