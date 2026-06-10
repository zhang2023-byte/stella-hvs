from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stella_benchmark.metrics import (  # noqa: E402
    bootstrap_micro_ci,
    cohen_kappa,
    convert_value,
    detection_summary,
    field_outcome,
    match_candidates,
    numeric_match,
    paper_status_summary,
    score_paper,
)
from stella_benchmark.field_specs import FieldSpec  # noqa: E402

RV_SPEC = FieldSpec("core.observed_phase_space.radial_velocity", "quantity")
CLAIM_SPEC = FieldSpec("inclusion_assessment.galactic_bound_claim", "categorical")


def candidate(
    *,
    gaia: str = "",
    names: list[str] | None = None,
    rv: dict[str, Any] | None = None,
    claim: str = "unbound",
) -> dict[str, Any]:
    return {
        "identifiers": {
            "record_id": "x:cand-001",
            "paper_candidate_id": (names or ["S"])[0],
            "gaia_source_id": gaia,
            "all": [{"value": name} for name in (names or [])],
        },
        "inclusion_assessment": {"galactic_bound_claim": claim},
        "core": {"observed_phase_space": ({"radial_velocity": rv} if rv else {})},
    }


def rv(value: str, unit: str = "km s^-1", **kwargs: str) -> dict[str, Any]:
    return {"raw_value": value, "value": value, "unit": unit, **kwargs}


def paper(candidates: list[dict[str, Any]], status: str | None = None) -> dict[str, Any]:
    return {
        "extraction": {"status": status or ("candidates_found" if candidates else "no_candidates")},
        "candidates": candidates,
    }


class MatchTest(unittest.TestCase):
    def test_gaia_tier_beats_overlap(self) -> None:
        gold = [candidate(gaia="Gaia DR3 1", names=["A"]), candidate(names=["B"])]
        variant = [candidate(names=["B"]), candidate(gaia="Gaia DR3 1", names=["other"])]
        self.assertEqual(match_candidates(gold, variant), [(0, 1), (1, 0)])

    def test_one_to_one_matching(self) -> None:
        gold = [candidate(names=["A", "B"])]
        variant = [candidate(names=["A"]), candidate(names=["B"])]
        pairs = match_candidates(gold, variant)
        self.assertEqual(len(pairs), 1)

    def test_largest_overlap_wins(self) -> None:
        gold = [candidate(names=["A", "B", "C"])]
        variant = [candidate(names=["C"]), candidate(names=["A", "B"])]
        self.assertEqual(match_candidates(gold, variant), [(0, 1)])


class NumericTest(unittest.TestCase):
    def test_strict_and_loose_tolerance(self) -> None:
        self.assertTrue(numeric_match(499.0, 499.0, rel_tol=1e-6))
        self.assertFalse(numeric_match(499.0, 499.4, rel_tol=1e-6))
        self.assertTrue(numeric_match(499.0, 499.4, rel_tol=1e-2))
        self.assertFalse(numeric_match(499.0, 510.0, rel_tol=1e-2))

    def test_unit_conversion(self) -> None:
        self.assertAlmostEqual(convert_value(1.0, "mas yr^-1", "mas/yr") or 0.0, 1.0)
        self.assertAlmostEqual(convert_value(1.0, "arcsec", "mas") or 0.0, 1000.0)
        self.assertIsNone(convert_value(1.0, "notaunit", "km/s"))

    def test_identical_unit_text_bypasses_parsing(self) -> None:
        self.assertEqual(convert_value(5.0, "weird unit", "weird  unit"), 5.0)


class FieldOutcomeTest(unittest.TestCase):
    def test_quantity_outcomes(self) -> None:
        gold = candidate(rv=rv("499"))
        self.assertEqual(field_outcome(RV_SPEC, gold, candidate(rv=rv("499")), rel_tol=1e-6), "correct")
        self.assertEqual(field_outcome(RV_SPEC, gold, candidate(rv=rv("510")), rel_tol=1e-6), "wrong")
        self.assertEqual(field_outcome(RV_SPEC, gold, candidate(), rel_tol=1e-6), "missing")
        self.assertEqual(field_outcome(RV_SPEC, candidate(), candidate(rv=rv("1")), rel_tol=1e-6), "spurious")
        self.assertIsNone(field_outcome(RV_SPEC, candidate(), candidate(), rel_tol=1e-6))

    def test_quantity_unit_conversion_in_comparison(self) -> None:
        gold = candidate(rv=rv("0.499", unit="Mm/s"))
        variant = candidate(rv=rv("499", unit="km s^-1"))
        self.assertEqual(field_outcome(RV_SPEC, gold, variant, rel_tol=1e-6), "correct")

    def test_error_handling(self) -> None:
        gold = candidate(rv=rv("499", error="6"))
        self.assertEqual(
            field_outcome(RV_SPEC, gold, candidate(rv=rv("499", error="6")), rel_tol=1e-6), "correct"
        )
        self.assertEqual(
            field_outcome(RV_SPEC, gold, candidate(rv=rv("499", error="7")), rel_tol=1e-6), "wrong"
        )
        self.assertEqual(
            field_outcome(RV_SPEC, gold, candidate(rv=rv("499")), rel_tol=1e-6), "wrong"
        )
        symmetric_as_asymmetric = candidate(rv=rv("499", lower_error="6", upper_error="6"))
        self.assertEqual(field_outcome(RV_SPEC, gold, symmetric_as_asymmetric, rel_tol=1e-6), "correct")
        asymmetric = candidate(rv=rv("499", lower_error="5", upper_error="7"))
        self.assertEqual(field_outcome(RV_SPEC, gold, asymmetric, rel_tol=1e-6), "wrong")

    def test_categorical_outcome(self) -> None:
        gold = candidate(claim="unbound")
        self.assertEqual(field_outcome(CLAIM_SPEC, gold, candidate(claim="unbound"), rel_tol=1e-6), "correct")
        self.assertEqual(
            field_outcome(CLAIM_SPEC, gold, candidate(claim="likely_unbound"), rel_tol=1e-6), "wrong"
        )


class DetectionTest(unittest.TestCase):
    def scores(self) -> dict[str, dict[str, Any]]:
        gold_one = paper([candidate(gaia="Gaia DR3 1"), candidate(gaia="Gaia DR3 2")])
        variant_one = paper([candidate(gaia="Gaia DR3 1"), candidate(gaia="Gaia DR3 9")])
        gold_two = paper([])
        variant_two = paper([candidate(gaia="Gaia DR3 5")], status="candidates_found")
        return {
            "p1": score_paper(gold_one, variant_one),
            "p2": score_paper(gold_two, variant_two),
        }

    def test_hand_computed_micro_metrics(self) -> None:
        summary = detection_summary(self.scores())
        # p1: tp=1 fp=1 fn=1; p2: tp=0 fp=1 fn=0
        self.assertEqual((summary["tp"], summary["fp"], summary["fn"]), (1, 2, 1))
        self.assertAlmostEqual(summary["micro_precision"], 1 / 3)
        self.assertAlmostEqual(summary["micro_recall"], 1 / 2)
        self.assertAlmostEqual(summary["micro_f1"], 0.4)
        self.assertAlmostEqual(summary["macro_f1"], 0.25)  # p1 f1=0.5, p2 f1=0
        self.assertEqual(summary["no_candidate_specificity"], 0.0)

    def test_missing_variant_counts_as_all_fn(self) -> None:
        gold = paper([candidate(gaia="Gaia DR3 1")])
        score = score_paper(gold, None)
        self.assertEqual((score["tp"], score["fp"], score["fn"]), (0, 0, 1))
        self.assertEqual(score["variant_status"], "missing")

    def test_status_summary(self) -> None:
        summary = paper_status_summary(self.scores())
        self.assertAlmostEqual(summary["accuracy"], 0.5)
        self.assertEqual(summary["confusion"]["no_candidates"]["candidates_found"], 1)

    def test_bootstrap_deterministic(self) -> None:
        scores = self.scores()
        first = bootstrap_micro_ci(scores, n_resamples=200, seed=7)
        second = bootstrap_micro_ci(scores, n_resamples=200, seed=7)
        self.assertEqual(first, second)
        self.assertLessEqual(first["micro_f1"][0], first["micro_f1"][1])


class KappaTest(unittest.TestCase):
    def test_known_contingency(self) -> None:
        labels_a = ["accept"] * 20 + ["reject"] * 5 + ["accept"] * 10 + ["reject"] * 15
        labels_b = ["accept"] * 20 + ["accept"] * 5 + ["reject"] * 10 + ["reject"] * 15
        kappa = cohen_kappa(labels_a, labels_b)
        # observed=0.7, expected=0.5 -> kappa=0.4
        self.assertAlmostEqual(kappa or 0.0, 0.4)

    def test_perfect_agreement(self) -> None:
        self.assertEqual(cohen_kappa(["a", "b"], ["a", "b"]), 1.0)

    def test_length_mismatch(self) -> None:
        self.assertIsNone(cohen_kappa(["a"], ["a", "b"]))


if __name__ == "__main__":
    unittest.main()
