from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from stella.benchmark.roster_bundle import (
    canonical_sha256,
    frozen_roster_errors,
    get_or_create_roster_bundle,
    roster_identifier_contract,
    roster_shared_key,
    roster_stubs,
    roster_structure_errors,
)


def roster_payload() -> dict:
    return {
        "method": "B",
        "arxiv_id": "1804.10179",
        "producer": {"model": "model-a"},
        "extraction": {"status": "candidates_found", "summary": "One candidate."},
        "candidates": [
            {
                "identifiers": {
                    "record_id": "1804.10179:cand-001",
                    "paper_candidate_id": "US708",
                    "gaia_source_id": "",
                    "all": [
                        {
                            "value": "US708",
                            "source_refs": [
                                {
                                    "kind": "text",
                                    "path": "literature/1804.10179/paper.tex",
                                    "start_line": 1,
                                    "end_line": 1,
                                    "context": "US708",
                                }
                            ],
                        }
                    ],
                },
                "inclusion_anchor": {
                    "summary": "P_bound < 0.5.",
                    "source_refs": [
                        {
                            "kind": "text",
                            "path": "literature/1804.10179/paper.tex",
                            "start_line": 1,
                            "end_line": 1,
                            "context": "P_bound < 0.5.",
                        }
                    ],
                },
            }
        ],
        "candidate_groups_considered": [],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


class RosterBundleTest(unittest.TestCase):
    def test_same_method_surface_neutral_key_shares_but_methods_do_not(self) -> None:
        common = {
            "arxiv_id": "1804.10179",
            "model": "model-a",
            "provider": {"provider": {"order": ["p"]}},
            "prompt_sha256": "prompt",
            "rule_sha256": "rule",
            "context_sha256": "context",
            "code_version": "commit",
        }
        b_full, _ = roster_shared_key(method="B", **common)
        b_core, _ = roster_shared_key(method="B", **common)
        c_full, _ = roster_shared_key(method="C", **common)
        c_core, _ = roster_shared_key(method="C", **common)

        self.assertEqual(b_full, b_core)
        self.assertEqual(c_full, c_core)
        self.assertNotEqual(b_full, c_full)

    def test_cache_produces_once_and_copies_bundle_and_attempts_to_each_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            first = root / "run-full" / "1804.10179"
            second = root / "run-core" / "1804.10179"
            (first / "attempts").mkdir(parents=True)
            (first / "attempts" / "roster-call-01.response.json").write_text("{}")
            calls = 0

            def produce() -> dict:
                nonlocal calls
                calls += 1
                return roster_payload()

            key_components = {
                "method": "B",
                "arxiv_id": "1804.10179",
                "model": "model-a",
                "provider": {},
                "prompt_sha256": "prompt",
                "rule_sha256": "rule",
                "context_sha256": "context",
                "code_version": "commit",
            }

            bundle_a, hit_a = get_or_create_roster_bundle(
                cache_root=cache,
                shared_key="a" * 64,
                key_components=key_components,
                paper_dir=first,
                producer=produce,
            )
            bundle_b, hit_b = get_or_create_roster_bundle(
                cache_root=cache,
                shared_key="a" * 64,
                key_components=key_components,
                paper_dir=second,
                producer=produce,
            )

            self.assertEqual(calls, 1)
            self.assertFalse(hit_a)
            self.assertTrue(hit_b)
            self.assertEqual(bundle_a["bundle_id"], bundle_b["bundle_id"])
            self.assertTrue((first / "roster_bundle.json").is_file())
            self.assertTrue((second / "roster_bundle.json").is_file())
            self.assertTrue((second / "attempts" / "roster-call-01.response.json").is_file())
            copied = json.loads((second / "roster_bundle.json").read_text())
            self.assertEqual(
                copied["schema"], {"name": "benchmark.roster_bundle", "version": 2}
            )
            self.assertEqual(
                copied["review"],
                {"status": "not_requested", "contract": None, "provenance": None},
            )
            self.assertEqual(len(copied["final_roster_sha256"]), 64)

            copied["schema"]["version"] = 1
            (cache / ("a" * 64) / "roster_bundle.json").write_text(json.dumps(copied))
            with self.assertRaisesRegex(ValueError, "not current"):
                get_or_create_roster_bundle(
                    cache_root=cache,
                    shared_key="a" * 64,
                    key_components=key_components,
                    paper_dir=second,
                    producer=produce,
                )

    def test_cache_rejects_a_tampered_bundle_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            paper = root / "run" / "1804.10179"
            components = {
                "method": "B",
                "arxiv_id": "1804.10179",
                "model": "model-a",
                "provider": {},
                "prompt_sha256": "prompt",
                "rule_sha256": "rule",
                "context_sha256": "context",
                "code_version": "commit",
            }
            get_or_create_roster_bundle(
                cache_root=cache,
                shared_key="b" * 64,
                key_components=components,
                paper_dir=paper,
                producer=roster_payload,
            )
            bundle_path = cache / ("b" * 64) / "roster_bundle.json"
            bundle = json.loads(bundle_path.read_text())
            bundle["candidates"][0]["identifiers"]["paper_candidate_id"] = "tampered"
            bundle_path.write_text(json.dumps(bundle))

            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                get_or_create_roster_bundle(
                    cache_root=cache,
                    shared_key="b" * 64,
                    key_components=components,
                    paper_dir=paper,
                    producer=roster_payload,
                )

    def test_cache_rejects_a_rehashed_bundle_with_a_stale_final_roster_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            paper = root / "run" / "1804.10179"
            components = {
                "method": "B",
                "arxiv_id": "1804.10179",
                "model": "model-a",
                "provider": {},
                "prompt_sha256": "prompt",
                "rule_sha256": "rule",
                "context_sha256": "context",
                "code_version": "commit",
            }
            bundle, _ = get_or_create_roster_bundle(
                cache_root=cache,
                shared_key="c" * 64,
                key_components=components,
                paper_dir=paper,
                producer=roster_payload,
            )
            bundle_path = cache / ("c" * 64) / "roster_bundle.json"
            bundle["candidates"][0]["identifiers"]["paper_candidate_id"] = "changed"
            bundle["bundle_id"] = canonical_sha256(
                {key: value for key, value in bundle.items() if key != "bundle_id"}
            )
            bundle_path.write_text(json.dumps(bundle))

            with self.assertRaisesRegex(ValueError, "final roster hash mismatch"):
                get_or_create_roster_bundle(
                    cache_root=cache,
                    shared_key="c" * 64,
                    key_components=components,
                    paper_dir=paper,
                    producer=roster_payload,
                )

    def test_downstream_cannot_change_frozen_roster(self) -> None:
        bundle = {"candidates": roster_payload()["candidates"]}
        frozen = roster_stubs(bundle)
        self.assertEqual(
            frozen_roster_errors({"candidates": frozen}, frozen), []
        )
        changed = list(reversed(frozen)) + [
            {"identifiers": {"record_id": "1804.10179:cand-002"}}
        ]
        self.assertTrue(frozen_roster_errors({"candidates": changed}, frozen))

    def test_roster_schema_requires_minimum_inclusion_anchor(self) -> None:
        payload = roster_payload()
        self.assertEqual(roster_structure_errors(payload, "1804.10179"), [])
        del payload["candidates"][0]["inclusion_anchor"]
        self.assertTrue(
            any(
                "inclusion_anchor" in error
                for error in roster_structure_errors(payload, "1804.10179")
            )
        )

    def test_roster_rejects_method_b_legacy_identifier_shape_before_caching(self) -> None:
        payload = roster_payload()
        payload["candidates"][0]["identifiers"] = {
            "record_id": "1804.10179:cand-001",
            "paper_candidate_id": "US708",
            "gaia_source_id": None,
            "all": [{"catalog": "LP", "id": "LP 40-365"}],
        }

        errors = roster_structure_errors(payload, "1804.10179")

        self.assertTrue(any("gaia_source_id" in error for error in errors))
        self.assertTrue(any("all.0.value" in error for error in errors))
        self.assertTrue(any("all.0.catalog" in error for error in errors))

    def test_roster_rejects_method_c_ad_hoc_identifier_shape(self) -> None:
        payload = roster_payload()
        payload["candidates"][0]["identifiers"] = {
            "record_id": "1804.10179:cand-001",
            "hv_survey_name": "HVS1",
        }

        errors = roster_structure_errors(payload, "1804.10179")

        self.assertTrue(any("paper_candidate_id" in error for error in errors))
        self.assertTrue(any("all" in error for error in errors))
        self.assertTrue(any("hv_survey_name" in error for error in errors))

    def test_roster_rejects_identifier_mirror_and_duplicate_failures(self) -> None:
        payload = roster_payload()
        payload["candidates"].append(json.loads(json.dumps(payload["candidates"][0])))
        payload["candidates"][1]["identifiers"]["record_id"] = "1804.10179:cand-002"
        payload["candidates"][1]["identifiers"]["all"][0]["value"] = "alias-only"

        errors = roster_structure_errors(payload, "1804.10179")

        self.assertTrue(any("must also appear in identifiers.all" in error for error in errors))
        self.assertTrue(any("duplicate paper_candidate_id" in error for error in errors))

    def test_roster_identifier_contract_is_exact_and_surface_neutral(self) -> None:
        contract = roster_identifier_contract("1804.10179")

        self.assertIn('"record_id": "1804.10179:cand-001"', contract)
        self.assertIn('"paper_candidate_id"', contract)
        self.assertIn('"gaia_source_id": ""', contract)
        self.assertIn('"value"', contract)
        self.assertIn('"source_refs"', contract)
        self.assertIn("Never use null", contract)


if __name__ == "__main__":
    unittest.main()
