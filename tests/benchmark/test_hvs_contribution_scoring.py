"""Layered contribution scoring tests (synthetic fixtures only)."""

from __future__ import annotations

import copy
import json
import random
import unittest

from pydantic import ValidationError

from stella.benchmark.hvs_contribution_scoring import (
    build_private_details,
    build_public_scorecard,
    leak_guard,
    match_value_multisets,
    score_contribution_paper,
    score_contribution_suite,
)
from stella.benchmark.hvs_contribution_scorecard import (
    HvsContributionScorecardV2,
)

ARXIV = "2601.00001"


def input_hashes() -> dict:
    return {
        "gold_selection": "0" * 64,
        "method_config": "1" * 64,
        "gold_annotations": ["2" * 64],
        "ai_documents": ["3" * 64],
    }


def scoring_contract() -> dict:
    return {
        "target": {
            "gold_schema": {
                "name": "benchmark.hvs_contribution_annotation",
                "version": 1,
            },
            "ai_schema": {
                "name": "literature_hvs_contributions",
                "version": 1,
            },
        },
        "score_spec": {"version": "3.0.0", "sha256": "4" * 64},
        "scorer": {
            "implementation": "stella.benchmark.hvs_contribution_scoring",
            "sha256": "5" * 64,
        },
    }


def public_scorecard(suite: dict) -> dict:
    return build_public_scorecard(
        suite,
        run_id="synthetic-run",
        paper_delivery={
            "complete": 1,
            "partial": 0,
            "failed": 0,
            "network_failed": 0,
            "interrupted": 0,
            "pending": 0,
            "running": 0,
            "skipped": 0,
        },
        input_hashes=input_hashes(),
        scoring_contract=scoring_contract(),
    )


def ai_identifier(value: str) -> dict:
    return {
        "value": value,
        "evidence": [
            {"kind": "text", "path": "main.tex", "start_line": 3, "end_line": 3}
        ],
    }


def gold_identifier(value: str) -> dict:
    return {"value": value, "evidence": [{"location": "Table 1"}]}


def gold_payload(contributions=None, **overrides) -> dict:
    payload = {
        "schema": {"name": "benchmark.hvs_contribution_annotation", "version": 1},
        "arxiv_id": ARXIV,
        "annotator": "expert-a",
        "annotated_at": "2026-08-22",
        "guideline_version": "pending",
        "evidence_basis": "pdf",
        "annotation_process": {
            "protocol": "contribution_migration_ai_assisted_v1",
            "preannotation_agent": "codex",
            "preannotation_model": "pre-model",
            "reconciliation_agent": "codex",
            "reconciliation_model": "reconcile-model",
            "expert_review_scope": "paper_level",
        },
        "status": "contributions_found" if contributions is None or contributions else "no_contributions",
        "contributions": contributions if contributions is not None else [gold_contribution()],
        "reviewed_exclusions": [],
    }
    if contributions:
        payload["status"] = "contributions_found"
    payload.update(overrides)
    return payload


def gold_contribution(**overrides) -> dict:
    contribution = {
        "identifiers": [gold_identifier("FIC-1")],
        "contribution_type": "candidates_found",
        "contribution_summary": "Gold summary wording A.",
        "contribution_evidence": [{"location": "Section 4"}],
        "paper_boundness": {"status": "unbound", "evidence": [{"location": "Section 5"}]},
        "quantities": [
            {
                "quantity": "observed_phase_space.distance",
                "values": [
                    gold_value("8.2", paper_preferred=True),
                    gold_value("7.9", paper_preferred=None, kind="prior_work"),
                ],
            }
        ],
    }
    contribution.update(overrides)
    return contribution


def gold_value(value, *, paper_preferred=None, kind="this_paper", error="") -> dict:
    return {
        "value": str(value),
        "error": error,
        "lower_error": "",
        "upper_error": "",
        "unit": "kpc",
        "limit_kind": "none",
        "range_lower": "",
        "range_upper": "",
        "condition": "condition",
        "paper_preferred": paper_preferred,
        "source": kind,
        "evidence": [{"location": "Table 2"}],
        "context_evidence": [],
        "source_note": "",
    }


def ai_document(contributions=None) -> dict:
    return {
        "schema": {"name": "literature_hvs_contributions", "version": 1},
        "generated_at": "2026-08-22T00:00:00+00:00",
        "paper": {"arxiv_id": ARXIV},
        "inputs": {"source_run_id": "crun-x", "paper_context_sha256": "0" * 64},
        "production": {
            "producer": "hvs_contribution_extraction",
            "method_fingerprint": "fp",
            "component_hashes": {},
        },
        "extraction": {
            "status": "complete",
            "roster_status": "contributions_found" if contributions is None or contributions else "no_contributions",
        },
        "reviewed_exclusions": [],
        "object_contributions": contributions if contributions is not None else [ai_contribution()],
    }


def ai_contribution(**overrides) -> dict:
    contribution = {
        "record_id": "obj-001",
        "identifiers": [ai_identifier("FIC-1")],
        "contribution_type": "candidates_found",
        "contribution_summary": "Completely different AI summary wording.",
        "contribution_evidence": [
            {"kind": "text", "path": "main.tex", "start_line": 3, "end_line": 3}
        ],
        "paper_boundness": {"status": "unbound", "evidence": [
            {"kind": "text", "path": "main.tex", "start_line": 3, "end_line": 3}
        ]},
        "quantity_extraction_status": "complete",
        "quantities": [
            {
                "quantity": "observed_phase_space.distance",
                "values": [
                    ai_value("8.2", paper_preferred=True),
                    ai_value("7.9", paper_preferred=None, kind="prior_work"),
                ],
            }
        ],
        "failure": None,
    }
    contribution.update(overrides)
    return contribution


def ai_value(value, *, paper_preferred=None, kind="this_paper", error=None) -> dict:
    return {
        "value": str(value),
        "error": error,
        "lower_error": None,
        "upper_error": None,
        "unit": "kpc",
        "limit_kind": "none",
        "range_lower": None,
        "range_upper": None,
        "coordinate_format": None,
        "condition": "condition",
        "paper_preferred": paper_preferred,
        "source": kind,
        "direct_evidence": [
            {
                "part": "value",
                "source": {
                    "kind": "text",
                    "path": "main.tex",
                    "start_line": 3,
                    "end_line": 3,
                    "raw_value": str(value),
                },
            }
        ],
        "context_evidence": [],
        "source_note": "",
    }


def score(gold=None, ai=None) -> dict:
    return score_contribution_paper(
        gold if gold is not None else gold_payload(),
        ai if ai is not None else ai_document(),
    )


class MultisetMatchingTest(unittest.TestCase):
    def test_order_independence(self) -> None:
        gold = [gold_value("8.2"), gold_value("7.9"), gold_value("8.6")]
        ai = [ai_value("7.9"), ai_value("8.6"), ai_value("8.2")]
        straight = match_value_multisets("observed_phase_space.distance", gold, ai)
        rng = random.Random(7)
        for _ in range(5):
            shuffled_gold = gold[:]
            shuffled_ai = ai[:]
            rng.shuffle(shuffled_gold)
            rng.shuffle(shuffled_ai)
            shuffled = match_value_multisets(
                "observed_phase_space.distance", shuffled_gold, shuffled_ai
            )
            self.assertEqual(len(straight["pairs"]), len(shuffled["pairs"]))
            self.assertEqual(straight["gold_only"], [])
            self.assertEqual(shuffled["gold_only"], [])
            self.assertEqual(
                sorted(pair["status"] for pair in straight["pairs"]),
                sorted(pair["status"] for pair in shuffled["pairs"]),
            )

    def test_pairs_to_best_values_not_positions(self) -> None:
        gold = [gold_value("8.2"), gold_value("7.9")]
        # Position-wise comparison would pair 8.2 with 7.9 (mismatch).
        ai = [ai_value("7.9"), ai_value("8.2")]
        result = match_value_multisets("observed_phase_space.distance", gold, ai)
        self.assertEqual(len(result["pairs"]), 2)
        self.assertTrue(all(pair["status"] == "value_match" for pair in result["pairs"]))

    def test_duplicate_ai_values_do_not_hide_misses(self) -> None:
        gold = [gold_value("8.2")]
        ai = [ai_value("8.2"), ai_value("8.2")]
        result = match_value_multisets("observed_phase_space.distance", gold, ai)
        self.assertEqual(len(result["pairs"]), 1)
        self.assertEqual(len(result["ai_only"]), 1)

    def test_probability_fraction_and_percent_match(self) -> None:
        gold = [gold_value("92") | {"unit": "%"}]
        ai = [ai_value("0.92") | {"unit": None}]
        result = match_value_multisets(
            "bound_assessment.unbound_probability", gold, ai
        )
        self.assertEqual(result["pairs"][0]["status"], "value_match")

    def test_duplicate_numeric_values_have_order_independent_diagnostics(self) -> None:
        gold = [
            gold_value("8.2", paper_preferred=True, kind="this_paper"),
            gold_value("8.2", paper_preferred=False, kind="prior_work"),
        ]
        ai = [
            ai_value("8.2", paper_preferred=True, kind="this_paper"),
            ai_value("8.2", paper_preferred=False, kind="prior_work"),
        ]
        straight = match_value_multisets(
            "observed_phase_space.distance", gold, ai
        )
        reversed_ai = match_value_multisets(
            "observed_phase_space.distance", gold, list(reversed(ai))
        )

        def diagnostics(result: dict) -> list[tuple]:
            return sorted(
                (
                    pair["paper_preferred_gold"],
                    pair["paper_preferred_ai"],
                    pair["source_kind_gold"],
                    pair["source_kind_ai"],
                )
                for pair in result["pairs"]
            )

        self.assertEqual(diagnostics(straight), diagnostics(reversed_ai))


class LayeredScoringTest(unittest.TestCase):
    def test_perfect_scores(self) -> None:
        result = score()
        self.assertEqual(set(result["aggregate"]), {"l0", "l1", "l2", "diagnostics"})
        self.assertEqual(result["details"]["l1"]["matched"], 1)
        self.assertEqual(result["aggregate"]["l1"]["f1"], 1.0)
        self.assertEqual(result["details"]["l2"]["paired"], 2)
        self.assertEqual(result["aggregate"]["l2"]["value_recall"], 1.0)
        self.assertEqual(result["aggregate"]["l2"]["strict_end_to_end_rate"], 1.0)
        self.assertEqual(result["aggregate"]["l1"]["matched"], 1)
        self.assertEqual(result["aggregate"]["l2"]["gold_values"], 2)
        self.assertEqual(
            result["details"]["diagnostics"]["contribution_type"]["correct"], 1
        )
        self.assertEqual(
            result["aggregate"]["diagnostics"]["paper_boundness"]["accuracy"],
            1.0,
        )

    def test_scores_are_order_independent(self) -> None:
        base = score()
        shuffled_ai = ai_document()
        shuffled_ai["object_contributions"][0]["quantities"][0]["values"].reverse()
        shuffled = score(ai=shuffled_ai)
        self.assertEqual(base["aggregate"], shuffled["aggregate"])

    def test_secondary_identifier_omission_is_not_scored_when_pairing_succeeds(self) -> None:
        gold = gold_contribution(
            identifiers=[gold_identifier("FIC-1"), gold_identifier("LONG-CATALOG-NAME")]
        )
        result = score_contribution_paper(
            gold_payload([gold]),
            ai_document([ai_contribution(identifiers=[ai_identifier("FIC-1")])]),
        )
        self.assertEqual(result["details"]["l1"]["matched"], 1)
        self.assertNotIn("identifier", json.dumps(result["aggregate"]))

    def test_full_gaia_identifier_bridges_to_bare_numeric_identifier(self) -> None:
        source_id = "1234567890123456789"
        gold = gold_contribution(
            identifiers=[gold_identifier(f"Gaia DR3 {source_id}")]
        )
        ai = ai_contribution(identifiers=[ai_identifier(source_id)])
        result = score_contribution_paper(gold_payload([gold]), ai_document([ai]))
        self.assertEqual(result["details"]["l1"]["matched"], 1)

    def test_l1_miss_propagates_to_l2(self) -> None:
        ai = ai_document(
            contributions=[
                ai_contribution(
                    record_id="obj-001",
                    identifiers=[ai_identifier("OTHER-9")],
                )
            ]
        )
        result = score(ai=ai)
        self.assertEqual(result["details"]["l1"]["matched"], 0)
        self.assertEqual(result["details"]["l1"]["gold_only"], 1)
        self.assertEqual(result["details"]["l1"]["ai_only"], 1)
        # Every gold status and value propagates to gold_only.
        self.assertEqual(
            result["details"]["diagnostics"]["paper_boundness"]["confusion"]
            ["unbound|gold_only"],
            1,
        )
        self.assertEqual(result["details"]["l2"]["gold_only"], 2)
        self.assertEqual(result["details"]["l2"]["paired"], 0)
        self.assertEqual(result["aggregate"]["l2"]["value_recall"], 0.0)
        self.assertEqual(result["aggregate"]["l2"]["strict_end_to_end_rate"], 0.0)

    def test_l1_uses_unique_coordinates_for_different_names(self) -> None:
        gold_ra = gold_value("120") | {
            "unit": "deg",
            "coordinate_format": "decimal_degrees",
        }
        gold_dec = gold_value("30") | {
            "unit": "deg",
            "coordinate_format": "decimal_degrees",
        }
        ai_ra = ai_value("120") | {
            "unit": "deg",
            "coordinate_format": "decimal_degrees",
        }
        ai_dec = ai_value("30") | {
            "unit": "deg",
            "coordinate_format": "decimal_degrees",
        }
        gold = gold_contribution(
            identifiers=[gold_identifier("GOLD-X")],
            quantities=[
                {"quantity": "observed_phase_space.ra", "values": [gold_ra]},
                {"quantity": "observed_phase_space.dec", "values": [gold_dec]},
            ],
        )
        ai = ai_contribution(
            identifiers=[ai_identifier("AI-X")],
            quantities=[
                {"quantity": "observed_phase_space.ra", "values": [ai_ra]},
                {"quantity": "observed_phase_space.dec", "values": [ai_dec]},
            ],
        )
        result = score_contribution_paper(
            gold_payload([gold]), ai_document([ai])
        )
        self.assertEqual(result["details"]["l1"]["matched"], 1)
        self.assertEqual(result["details"]["l1"]["match_methods"], {"coordinates": 1})

    def test_ambiguous_multivalue_coordinates_do_not_guess_first(self) -> None:
        def coordinate(value: str, *, ai_side: bool) -> dict:
            item = ai_value(value) if ai_side else gold_value(value)
            return item | {"unit": "deg", "coordinate_format": "decimal_degrees"}

        gold = gold_contribution(
            identifiers=[gold_identifier("GOLD-X")],
            quantities=[
                {
                    "quantity": "observed_phase_space.ra",
                    "values": [coordinate("120", ai_side=False), coordinate("121", ai_side=False)],
                },
                {"quantity": "observed_phase_space.dec", "values": [coordinate("30", ai_side=False)]},
            ],
        )
        ai = ai_contribution(
            identifiers=[ai_identifier("AI-X")],
            quantities=[
                {"quantity": "observed_phase_space.ra", "values": [coordinate("120", ai_side=True)]},
                {"quantity": "observed_phase_space.dec", "values": [coordinate("30", ai_side=True)]},
            ],
        )
        result = score_contribution_paper(gold_payload([gold]), ai_document([ai]))
        self.assertEqual(result["details"]["l1"]["matched"], 0)

    def test_wrong_preference_is_value_match_plus_diagnostic(self) -> None:
        ai = ai_document(
            contributions=[
                ai_contribution(
                    quantities=[
                        {
                            "quantity": "observed_phase_space.distance",
                            "values": [
                                ai_value("8.2", paper_preferred=False),
                                ai_value("7.9", paper_preferred=True, kind="prior_work"),
                            ],
                        }
                    ]
                )
            ]
        )
        result = score(ai=ai)
        self.assertEqual(result["details"]["l2"]["paired"], 2)
        self.assertEqual(result["details"]["l2"]["strict_agreement"], 2)
        self.assertEqual(result["details"]["diagnostics"]["paper_preferred"]["compared"], 2)
        self.assertEqual(result["details"]["diagnostics"]["paper_preferred"]["agreement"], 0)

    def test_wrong_source_kind_is_value_match_plus_diagnostic(self) -> None:
        ai = ai_document(
            contributions=[
                ai_contribution(
                    quantities=[
                        {
                            "quantity": "observed_phase_space.distance",
                            "values": [
                                ai_value("8.2", paper_preferred=True, kind="unclear"),
                                ai_value("7.9", paper_preferred=None, kind="this_paper"),
                            ],
                        }
                    ]
                )
            ]
        )
        result = score(ai=ai)
        self.assertEqual(result["details"]["l2"]["strict_agreement"], 2)
        self.assertEqual(result["details"]["diagnostics"]["source_kind"]["agreement"], 0)

    def test_different_summary_wording_not_penalized(self) -> None:
        result = score()
        audit = result["details"]["diagnostics"]["summary_evidence"]
        self.assertEqual(audit["matched"], 1)
        self.assertEqual(audit["required_summary_present"], 1)
        self.assertEqual(audit["required_evidence_present"], 1)

    def test_type_and_status_confusions_counted(self) -> None:
        ai = ai_document(
            contributions=[
                ai_contribution(
                    contribution_type="follow_up",
                    paper_boundness={"status": "possibly_unbound", "evidence": [
                        {"kind": "text", "path": "main.tex", "start_line": 3, "end_line": 3}
                    ]},
                )
            ]
        )
        result = score(ai=ai)
        self.assertEqual(
            result["details"]["diagnostics"]["contribution_type"]["confusion"]
            ["candidates_found|follow_up"],
            1,
        )
        self.assertEqual(
            result["details"]["diagnostics"]["paper_boundness"]["confusion"]
            ["unbound|possibly_unbound"],
            1,
        )

    def test_public_scorecard_leaks_no_identities_or_values(self) -> None:
        suite = score_contribution_suite([gold_payload()], {ARXIV: ai_document()})
        scorecard = public_scorecard(suite)
        forbidden = {"FIC-1", "8.2", "7.9"}
        self.assertEqual(leak_guard(scorecard, forbidden), [])
        serialized = json.dumps(scorecard)
        for forbidden in ("FIC-1", "8.2", "7.9", "expert-a"):
            self.assertNotIn(forbidden, serialized)

    def test_no_composite_or_pass_fail_key(self) -> None:
        suite = score_contribution_suite([gold_payload()], {ARXIV: ai_document()})
        scorecard = public_scorecard(suite)
        self.assertEqual(scorecard["schema"]["version"], 2)
        self.assertEqual(
            {"l0", "l1", "l2", "diagnostics"},
            {key for key in scorecard if key in {"l0", "l1", "l2", "diagnostics"}},
        )
        self.assertNotIn("aggregate", scorecard)
        self.assertNotIn("totals", scorecard)
        serialized = json.dumps(scorecard)
        for forbidden in (
            "composite",
            '"pass"',
            "verdict",
            "overall_score",
            '"l1a"',
            '"l1b"',
            '"l2a"',
            '"l2b"',
            '"delivery"',
        ):
            self.assertNotIn(forbidden, serialized)

    def test_private_details_carry_rows_and_leak_guard_detects(self) -> None:
        suite = score_contribution_suite([gold_payload()], {ARXIV: ai_document()})
        details = build_private_details(
            suite,
            input_hashes=input_hashes(),
            scoring_contract=scoring_contract(),
        )
        self.assertTrue(details["papers"][0]["value_rows"])
        self.assertEqual(leak_guard(details, {"FIC-1"}), [])  # identities stay out of rows

    def test_missing_ai_document_l0(self) -> None:
        result = score_contribution_paper(gold_payload(), None)
        self.assertFalse(result["details"]["l0"]["ai_document_delivered"])
        self.assertEqual(result["aggregate"]["l1"]["recall"], 0.0)
        self.assertIsNone(result["aggregate"]["l1"]["f1"])

        suite = score_contribution_suite([gold_payload()], {ARXIV: None})
        self.assertEqual(suite["totals"]["l0"]["documents_missing"], 1)
        self.assertEqual(suite["totals"]["l0"]["schema_invalid"], 0)
        self.assertIsNone(suite["aggregate"]["l0"]["schema_valid_rate"])

    def test_delivered_invalid_document_is_not_missing(self) -> None:
        suite = score_contribution_suite([gold_payload()], {ARXIV: {}})
        self.assertEqual(suite["totals"]["l0"]["documents_delivered"], 1)
        self.assertEqual(suite["totals"]["l0"]["documents_missing"], 0)
        self.assertEqual(suite["totals"]["l0"]["schema_invalid"], 1)
        self.assertEqual(suite["aggregate"]["l0"]["schema_valid_rate"], 0.0)

    def test_summary_and_evidence_presence_are_public_diagnostics(self) -> None:
        suite = score_contribution_suite([gold_payload()], {ARXIV: ai_document()})
        diagnostic = suite["aggregate"]["diagnostics"]["summary_evidence"]
        self.assertEqual(diagnostic["matched"], 1)
        self.assertEqual(diagnostic["required_summary_present"], 1)
        self.assertEqual(diagnostic["required_evidence_present"], 1)
        self.assertEqual(diagnostic["summary_presence_rate"], 1.0)
        self.assertEqual(diagnostic["evidence_presence_rate"], 1.0)

    def test_scorecard_model_rejects_empty_or_unknown_fields(self) -> None:
        with self.assertRaises(ValidationError):
            HvsContributionScorecardV2.model_validate({})
        card = public_scorecard(
            score_contribution_suite([gold_payload()], {ARXIV: ai_document()})
        )
        HvsContributionScorecardV2.model_validate(card)
        with self.assertRaises(ValidationError):
            HvsContributionScorecardV2.model_validate(card | {"overall": 1.0})
        inconsistent = copy.deepcopy(card)
        inconsistent["l0"]["documents"]["delivery_rate"] = 0.5
        with self.assertRaises(ValidationError):
            HvsContributionScorecardV2.model_validate(inconsistent)
