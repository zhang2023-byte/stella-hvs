from __future__ import annotations

import unittest

from stella.legacy_versions import normalize_legacy_schema
from stella.schema_registry import LEGACY_ALIASES, REGISTRY, require_schema, schema_ref


class SchemaRegistryTests(unittest.TestCase):
    def test_registry_is_unique_and_current_versions_are_readable(self):
        self.assertEqual(len(REGISTRY), len(set(REGISTRY)))
        for entry in REGISTRY.values():
            self.assertGreater(entry.current_version, 0)
            self.assertIn(entry.current_version, entry.readable_versions)

    def test_schema_ref_and_require_schema(self):
        payload = {"schema": schema_ref("literature_hvs_candidates", 1)}
        self.assertEqual(require_schema(payload, "literature_hvs_candidates"), ("literature_hvs_candidates", 1))
        with self.assertRaisesRegex(ValueError, "not current"):
            require_schema(payload, "literature_hvs_candidates", require_current=True)

    def test_normal_reader_rejects_legacy_wire_shape(self):
        payload = {"schema_version": "stella.literature_hvs_candidates.v0.1"}
        with self.assertRaisesRegex(ValueError, "structured schema"):
            require_schema(payload, "literature_hvs_candidates")

    def test_legacy_adapter_is_explicit_and_non_mutating(self):
        payload = {"schema_version": "stella.literature_hvs_candidates.v0.1", "x": 1}
        normalized = normalize_legacy_schema(payload)
        self.assertEqual(normalized["schema"], {"name": "literature_hvs_candidates", "version": 1})
        self.assertNotIn("schema", payload)
        self.assertIn("stella.literature_hvs_candidates.v0.1", LEGACY_ALIASES)


if __name__ == "__main__":
    unittest.main()
