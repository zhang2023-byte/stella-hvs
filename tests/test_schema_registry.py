from __future__ import annotations

import unittest

from stella.legacy_versions import normalize_legacy_schema
from stella.schema_registry import (
    ACTIVE_BENCHMARK_CAMPAIGN,
    BENCHMARK_CAMPAIGNS,
    LEGACY_ALIASES,
    REGISTRY,
    require_campaign_writable,
    require_schema,
    schema_ref,
)


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

    def test_v4_is_only_writable_campaign(self):
        self.assertEqual(ACTIVE_BENCHMARK_CAMPAIGN, "hvs-extraction-v4")
        self.assertEqual(
            {campaign_id: entry.lifecycle for campaign_id, entry in BENCHMARK_CAMPAIGNS.items()},
            {
                "hvs-extraction-v1": "read_only",
                "hvs-extraction-v2": "read_only",
                "hvs-extraction-v3": "read_only",
                "hvs-extraction-scratch-legacy": "read_only",
                "hvs-extraction-v4": "active",
            },
        )
        self.assertEqual(require_campaign_writable("hvs-extraction-v4"), "hvs-extraction-v4")
        for campaign_id in (
            "hvs-extraction-v1",
            "hvs-extraction-v2",
            "hvs-extraction-v3",
            "hvs-extraction-scratch-legacy",
            "unknown",
        ):
            with self.subTest(campaign_id=campaign_id):
                with self.assertRaisesRegex(ValueError, "not writable"):
                    require_campaign_writable(campaign_id)

    def test_current_persisted_contract_versions_are_current_and_old_versions_readable(self):
        expected = {
            "benchmark.run_config": (3, (2, 3)),
            "benchmark.run_manifest": (4, (1, 2, 3, 4)),
            "benchmark.roster_bundle": (3, (1, 2, 3)),
            "benchmark.scorecard": (4, (2, 3, 4)),
            "literature_hvs_candidates": (2, (1, 2)),
        }
        for name, (current, readable) in expected.items():
            with self.subTest(name=name):
                self.assertEqual(REGISTRY[name].current_version, current)
                self.assertEqual(REGISTRY[name].readable_versions, readable)
                self.assertEqual(schema_ref(name), {"name": name, "version": current})
                if readable[0] != current:
                    self.assertEqual(require_schema({"schema": schema_ref(name, readable[0])}, name), (name, readable[0]))
                    with self.assertRaisesRegex(ValueError, "not current"):
                        require_schema({"schema": schema_ref(name, readable[0])}, name, require_current=True)


if __name__ == "__main__":
    unittest.main()
