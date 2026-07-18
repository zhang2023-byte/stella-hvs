from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from stella.benchmark.roster_bundle import (
    RosterReviewVerdict,
    canonical_sha256,
    final_roster_sha256,
    frozen_roster_errors,
    get_or_create_roster_bundle,
    roster_identifier_contract,
    roster_inclusion_anchor_map,
    roster_review_structure_errors,
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


def second_candidate() -> dict:
    candidate = json.loads(json.dumps(roster_payload()["candidates"][0]))
    candidate["identifiers"]["record_id"] = "1804.10179:cand-002"
    candidate["identifiers"]["paper_candidate_id"] = "LP 40-365"
    candidate["identifiers"]["all"] = [
        {
            "value": "LP 40-365",
            "source_refs": [
                {
                    "kind": "text",
                    "path": "literature/1804.10179/paper.tex",
                    "start_line": 9,
                    "end_line": 9,
                    "context": "LP 40-365",
                }
            ],
        }
    ]
    candidate["inclusion_anchor"] = {
        "summary": "Mentioned in passing only.",
        "source_refs": [
            {
                "kind": "text",
                "path": "literature/1804.10179/paper.tex",
                "start_line": 9,
                "end_line": 9,
                "context": "LP 40-365",
            }
        ],
    }
    return candidate


def reviewer_verdict(decision: str, revised_roster: dict | None = None) -> RosterReviewVerdict:
    payload: dict = {
        "decision": decision,
        "challenges": [
            {"record_id": "1804.10179:cand-002", "issue": "cite-in-passing only"}
        ],
        "summary": "roster review complete",
    }
    if revised_roster is not None:
        payload["revised_roster"] = revised_roster
    return RosterReviewVerdict(
        payload=payload,
        provenance={
            "model": "glm-5.2",
            "served_model": "glm-5.2",
            "provider": {"provider": {"order": ["bigmodel"]}},
            "prompt_sha256": "reviewer-prompt",
            "rule_sha256": "reviewer-rule",
        },
        usage={"total_tokens": 7},
    )


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
            "reviewer_model": "reviewer-a",
            "reviewer_provider": {"provider": {"order": ["reviewer-provider"]}},
            "reviewer_prompt_sha256": "reviewer-prompt",
            "reviewer_rule_sha256": "reviewer-rule",
        }
        b_full, _ = roster_shared_key(method="B", **common)
        b_core, _ = roster_shared_key(method="B", **common)
        c_full, _ = roster_shared_key(method="C", **common)
        c_core, _ = roster_shared_key(method="C", **common)

        self.assertEqual(b_full, b_core)
        self.assertEqual(c_full, c_core)
        self.assertNotEqual(b_full, c_full)

    def test_reviewer_contract_is_part_of_the_cache_key(self) -> None:
        common = {
            "method": "B",
            "arxiv_id": "1804.10179",
            "model": "model-a",
            "provider": {},
            "prompt_sha256": "prompt",
            "rule_sha256": "rule",
            "context_sha256": "context",
            "code_version": "commit",
            "reviewer_model": "reviewer-a",
            "reviewer_provider": {"provider": {"order": ["reviewer-provider"]}},
            "reviewer_prompt_sha256": "reviewer-prompt",
            "reviewer_rule_sha256": "reviewer-rule",
        }
        base_key, base_components = roster_shared_key(**common)
        for field, replacement in (
            ("reviewer_model", "reviewer-b"),
            ("reviewer_provider", {"provider": {"order": ["other-provider"]}}),
            ("reviewer_prompt_sha256", "other-prompt"),
            ("reviewer_rule_sha256", "other-rule"),
        ):
            changed = {**common, field: replacement}
            changed_key, changed_components = roster_shared_key(**changed)
            self.assertNotEqual(base_key, changed_key)
            self.assertNotEqual(
                base_components[field], changed_components[field]
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            paper = root / "run" / "1804.10179"
            calls = 0

            def produce() -> dict:
                nonlocal calls
                calls += 1
                return roster_payload()

            _, hit_first = get_or_create_roster_bundle(
                cache_root=cache,
                shared_key=base_key,
                key_components=base_components,
                paper_dir=paper,
                producer=produce,
            )
            # A bundle sealed under a different reviewer contract must not hit.
            changed = {**common, "reviewer_model": "reviewer-b"}
            changed_key, changed_components = roster_shared_key(**changed)
            _, hit_second = get_or_create_roster_bundle(
                cache_root=cache,
                shared_key=changed_key,
                key_components=changed_components,
                paper_dir=paper,
                producer=produce,
            )

            self.assertFalse(hit_first)
            self.assertFalse(hit_second)
            self.assertEqual(calls, 2)
            self.assertTrue((cache / base_key / "roster_bundle.json").is_file())
            self.assertTrue((cache / changed_key / "roster_bundle.json").is_file())

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


class RosterReviewSealTest(unittest.TestCase):
    """The one independent roster review runs before the bundle hash."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.cache = self.root / "cache"
        self.paper = self.root / "run" / "1804.10179"
        _, self.key_components = roster_shared_key(
            method="B",
            arxiv_id="1804.10179",
            model="model-a",
            provider={},
            prompt_sha256="prompt",
            rule_sha256="rule",
            context_sha256="context",
            code_version="commit",
            reviewer_model="glm-5.2",
            reviewer_provider={"provider": {"order": ["bigmodel"]}},
            reviewer_prompt_sha256="reviewer-prompt",
            reviewer_rule_sha256="reviewer-rule",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def seal(self, producer, reviewer) -> tuple[dict, bool]:
        return get_or_create_roster_bundle(
            cache_root=self.cache,
            shared_key="d" * 64,
            key_components=self.key_components,
            paper_dir=self.paper,
            producer=producer,
            reviewer=reviewer,
        )

    def test_reviewer_removes_an_overincluded_member_before_hashing(self) -> None:
        # Plan Step 1: the producer over-includes one roster member and the
        # roster reviewer removes it before the bundle hash is computed.
        overincluded = roster_payload()
        overincluded["candidates"].append(second_candidate())
        revised = roster_payload()
        review_calls = []

        def reviewer(produced: dict) -> RosterReviewVerdict:
            review_calls.append(json.loads(json.dumps(produced)))
            return reviewer_verdict("revise", revised_roster=revised)

        bundle, hit = self.seal(lambda: overincluded, reviewer)

        self.assertFalse(hit)
        self.assertEqual(len(review_calls), 1)
        # The reviewer saw the produced roster (with both members) ...
        self.assertEqual(len(review_calls[0]["candidates"]), 2)
        # ... but the sealed roster is the revised one.
        self.assertEqual(len(bundle["candidates"]), 1)
        self.assertEqual(
            bundle["candidates"][0]["identifiers"]["paper_candidate_id"], "US708"
        )
        self.assertEqual(bundle["review"]["status"], "revised")
        contract = bundle["review"]["contract"]
        self.assertEqual(contract["decision"], "revise")
        self.assertEqual(
            contract["producer_roster_sha256"], final_roster_sha256(overincluded)
        )
        self.assertNotEqual(
            contract["producer_roster_sha256"], bundle["final_roster_sha256"]
        )
        self.assertEqual(
            bundle["final_roster_sha256"], final_roster_sha256(bundle)
        )
        self.assertEqual(
            bundle["review"]["provenance"]["model"], "glm-5.2"
        )
        # Review usage is merged into the sealed roster-stage usage.
        self.assertEqual(bundle["usage"]["total_tokens"], 15 + 7)
        # The sealed bundle round-trips through the cache validation.
        reloaded, hit_again = self.seal(
            lambda: self.fail("producer must not run on a cache hit"), reviewer
        )
        self.assertTrue(hit_again)
        self.assertEqual(reloaded["bundle_id"], bundle["bundle_id"])

    def test_reviewer_accept_seals_the_produced_roster(self) -> None:
        produced = roster_payload()

        bundle, hit = self.seal(
            lambda: produced, lambda _: reviewer_verdict("accept")
        )

        self.assertFalse(hit)
        self.assertEqual(bundle["candidates"], produced["candidates"])
        self.assertEqual(bundle["review"]["status"], "accepted")
        self.assertEqual(bundle["review"]["contract"]["decision"], "accept")
        self.assertEqual(
            bundle["review"]["contract"]["producer_roster_sha256"],
            bundle["final_roster_sha256"],
        )
        copied = json.loads((self.paper / "roster_bundle.json").read_text())
        self.assertEqual(copied["review"]["status"], "accepted")
        self.assertEqual(
            copied["review"]["provenance"]["prompt_sha256"], "reviewer-prompt"
        )
        self.assertEqual(
            copied["review"]["provenance"]["rule_sha256"], "reviewer-rule"
        )
        self.assertEqual(
            copied["review"]["provenance"]["provider"],
            {"provider": {"order": ["bigmodel"]}},
        )

    def test_invalid_revised_roster_fails_closed_without_persisting(self) -> None:
        overincluded = roster_payload()
        overincluded["candidates"].append(second_candidate())
        broken_revision = roster_payload()
        broken_revision["candidates"][0]["identifiers"]["record_id"] = "bogus"

        with self.assertRaisesRegex(ValueError, "roster review payload is invalid"):
            self.seal(
                lambda: overincluded,
                lambda _: reviewer_verdict("revise", revised_roster=broken_revision),
            )

        self.assertFalse(
            (self.cache / ("d" * 64) / "roster_bundle.json").exists()
        )
        self.assertFalse((self.paper / "roster_bundle.json").exists())

    def test_malformed_review_payload_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "roster review payload is invalid"):
            self.seal(
                roster_payload,
                lambda _: reviewer_verdict("revise"),  # no revised_roster
            )
        self.assertFalse(
            (self.cache / ("d" * 64) / "roster_bundle.json").exists()
        )

    def test_review_attempts_are_copied_into_the_bundle_archive(self) -> None:
        attempts = self.paper / "attempts"
        attempts.mkdir(parents=True)
        (attempts / "roster-review-call-01.response.json").write_text("{}")
        (attempts / "roster-call-01.response.json").write_text("{}")

        self.seal(roster_payload, lambda _: reviewer_verdict("accept"))

        archived = self.cache / ("d" * 64) / "attempts"
        self.assertTrue((archived / "roster-call-01.response.json").is_file())
        self.assertTrue((archived / "roster-review-call-01.response.json").is_file())


class RosterReviewContractTest(unittest.TestCase):
    def test_structure_errors_cover_decision_summary_and_challenges(self) -> None:
        self.assertTrue(roster_review_structure_errors("nope", "1804.10179"))
        self.assertTrue(
            roster_review_structure_errors(
                {"decision": "maybe", "challenges": [], "summary": "s"},
                "1804.10179",
            )
        )
        self.assertIn(
            "summary is required",
            roster_review_structure_errors(
                {"decision": "accept", "challenges": []}, "1804.10179"
            ),
        )
        self.assertTrue(
            roster_review_structure_errors(
                {
                    "decision": "accept",
                    "challenges": [{"record_id": "x"}],
                    "summary": "s",
                },
                "1804.10179",
            )
        )
        self.assertEqual(
            roster_review_structure_errors(
                {
                    "decision": "accept",
                    "challenges": [
                        {"record_id": "1804.10179:cand-001", "issue": "borderline"}
                    ],
                    "summary": "sound",
                },
                "1804.10179",
            ),
            [],
        )

    def test_revised_roster_only_allowed_and_validated_on_revise(self) -> None:
        payload = {
            "decision": "accept",
            "challenges": [],
            "summary": "s",
            "revised_roster": roster_payload(),
        }
        self.assertTrue(roster_review_structure_errors(payload, "1804.10179"))

        revise = {
            "decision": "revise",
            "challenges": [],
            "summary": "s",
            "revised_roster": roster_payload(),
        }
        self.assertIn(
            "decision 'revise' requires at least one challenge",
            roster_review_structure_errors(revise, "1804.10179"),
        )
        revise["challenges"] = [
            {"record_id": "1804.10179:cand-001", "issue": "membership error"}
        ]
        self.assertEqual(roster_review_structure_errors(revise, "1804.10179"), [])
        revise["revised_roster"]["candidates"] = []
        errors = roster_review_structure_errors(revise, "1804.10179")
        self.assertTrue(any("revised_roster." in error for error in errors))

    def test_roster_record_ids_must_be_contiguous_and_ordered(self) -> None:
        payload = roster_payload()
        skipped = second_candidate()
        skipped["identifiers"]["record_id"] = "1804.10179:cand-003"
        payload["candidates"].append(skipped)

        errors = roster_structure_errors(payload, "1804.10179")

        self.assertIn(
            "candidates[1].identifiers.record_id must equal '1804.10179:cand-002'",
            errors,
        )

    def test_inclusion_anchor_map_keys_anchors_by_record_id(self) -> None:
        bundle = {"candidates": [roster_payload()["candidates"][0], second_candidate()]}
        anchors = roster_inclusion_anchor_map(bundle)

        self.assertEqual(
            sorted(anchors),
            ["1804.10179:cand-001", "1804.10179:cand-002"],
        )
        self.assertEqual(
            anchors["1804.10179:cand-001"]["summary"], "P_bound < 0.5."
        )
        # The stubs stay identifiers-only, so frozen-roster equality is unaffected.
        self.assertEqual(
            roster_stubs(bundle),
            [{"identifiers": c["identifiers"]} for c in bundle["candidates"]],
        )


if __name__ == "__main__":
    unittest.main()
