from __future__ import annotations

import copy
import unittest

from stella.benchmark.run_contract import (
    build_method_fingerprint,
    canonical_sha256,
    require_v6_run_manifest,
)
from stella.schema_registry import schema_ref


def manifest() -> dict:
    empty_usage = {
        "prompt_tokens": 0,
        "cached_input_tokens": 0,
        "uncached_input_tokens": 0,
        "completion_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
        "api_calls": 0,
        "telemetry_status": "not_applicable",
        "warnings": [],
    }
    return {
        "schema": schema_ref("benchmark.run_manifest"),
        "run_id": "run-1",
        "papers": ["p1", "p2", "p3"],
        "l1_roster_delivery": {
            "complete": ["p1", "p2"],
            "failed": ["p3"],
            "missing": [],
        },
        "l2_core_field_delivery": {
            "complete": ["p1"],
            "partial": ["p2"],
            "failed": ["p3"],
            "missing": [],
            "candidate_counts": {
                "total": 3,
                "fields_complete": 2,
                "field_extraction_failed": 1,
            },
        },
        "l0": {
            "format_validation": {
                "observed_units": 3,
                "valid_first_pass": 1,
                "valid_after_correction": 1,
                "invalid": 1,
                "not_observed": 1,
                "first_pass_rate": 0.333333,
                "final_valid_rate": 0.666667,
            }
        },
        "usage": {
            "by_role": {
                "roster": dict(empty_usage),
                "core_fields": dict(empty_usage),
            },
            "total": dict(empty_usage),
        },
        "artifacts": {"p1": {}, "p2": {}, "p3": {}},
    }


class BenchmarkRunContractTest(unittest.TestCase):
    def test_accepts_ordered_layered_delivery(self) -> None:
        l1, l2 = require_v6_run_manifest(manifest())
        self.assertEqual(l1["complete"], ["p1", "p2"])
        self.assertEqual(l2["partial"], ["p2"])

    def test_each_layer_must_exactly_cover_configured_papers(self) -> None:
        broken = manifest()
        broken["l1_roster_delivery"]["failed"] = []
        with self.assertRaisesRegex(ValueError, "exactly cover"):
            require_v6_run_manifest(broken)

    def test_outcomes_preserve_config_order(self) -> None:
        broken = manifest()
        broken["l1_roster_delivery"]["complete"] = ["p2", "p1"]
        with self.assertRaisesRegex(ValueError, "preserve paper order"):
            require_v6_run_manifest(broken)

    def test_candidate_counts_must_add_up(self) -> None:
        broken = manifest()
        broken["l2_core_field_delivery"]["candidate_counts"]["total"] = 4
        with self.assertRaisesRegex(ValueError, "do not add up"):
            require_v6_run_manifest(broken)

    def test_format_counts_must_add_up(self) -> None:
        broken = manifest()
        broken["l0"]["format_validation"]["observed_units"] = 4
        with self.assertRaisesRegex(ValueError, "observed count"):
            require_v6_run_manifest(broken)

    def test_usage_input_counts_must_add_up(self) -> None:
        broken = manifest()
        broken["usage"]["by_role"]["roster"]["prompt_tokens"] = 1
        with self.assertRaisesRegex(ValueError, "input token counts"):
            require_v6_run_manifest(broken)

    def test_total_usage_must_equal_role_aggregates(self) -> None:
        broken = manifest()
        broken["usage"]["total"]["api_calls"] = 1
        with self.assertRaisesRegex(ValueError, "does not match role usage"):
            require_v6_run_manifest(broken)

    def test_artifacts_cannot_name_an_undeclared_paper(self) -> None:
        broken = manifest()
        broken["artifacts"]["escape"] = {}
        with self.assertRaisesRegex(ValueError, "undeclared"):
            require_v6_run_manifest(broken)

    def test_schema_must_be_current(self) -> None:
        broken = manifest()
        broken["schema"]["version"] = 4
        with self.assertRaisesRegex(ValueError, "not current"):
            require_v6_run_manifest(broken)

    def test_method_fingerprint_is_canonical_and_sensitive(self) -> None:
        first = {"models": {"roster": "r", "core_fields": "f"}, "limit": 3}
        reordered = {"limit": 3, "models": {"core_fields": "f", "roster": "r"}}
        self.assertEqual(
            build_method_fingerprint(first), build_method_fingerprint(reordered)
        )
        changed = copy.deepcopy(first)
        changed["models"]["roster"] = "other"
        self.assertNotEqual(
            build_method_fingerprint(first), build_method_fingerprint(changed)
        )
        self.assertEqual(len(canonical_sha256(first)), 64)


if __name__ == "__main__":
    unittest.main()
