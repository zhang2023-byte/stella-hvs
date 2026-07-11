from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from scripts.migrate_schema_registry_v2 import migrate, migrate_payload


class SchemaMigrationTests(unittest.TestCase):
    def test_candidate_migration_preserves_domain_payload_and_normalizes_provenance(self):
        source = {
            "schema": {"name": "literature_hvs_candidates", "version": 1},
            "extraction": {
                "extractor": "agent",
                "tooling": {
                    "agent_runtime": "legacy-agent",
                    "model_id": "unknown_legacy",
                    "prompt_version": "unknown_legacy",
                    "request_parameters": {"x": 1},
                },
            },
            "candidates": [{"id": "science"}],
        }
        original = copy.deepcopy(source)
        migrated = migrate_payload(source)
        self.assertEqual(migrated["schema"], {"name": "literature_hvs_candidates", "version": 1})
        self.assertEqual(migrated["candidates"], original["candidates"])
        self.assertNotIn("tooling", migrated["extraction"])
        self.assertEqual(migrated["extraction"]["provenance"]["parameters"], {"x": 1})
        self.assertEqual(source, original)

    def test_dry_run_and_write_are_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "notes" / "2026" / "2026-01" / "2026-01.json"
            path.parent.mkdir(parents=True)
            path.write_text('{"schema_version":"stella.literature.month.v0.1"}\n', encoding="utf-8")
            before = path.read_bytes()
            self.assertEqual(migrate(root, write=False)["changed"], 1)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(migrate(root, write=True)["changed"], 1)
            self.assertEqual(migrate(root, write=True)["unchanged"], 1)


if __name__ == "__main__":
    unittest.main()
