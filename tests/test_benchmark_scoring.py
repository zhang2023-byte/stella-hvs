"""Scorer tests: L1 matching plus the formal L2 contract.

Every fixture is synthetic (contamination rule: real gold never enters the
test suite). The L2 classes map one-to-one onto the rules of
docs/benchmark-l2-spec.md v0.2.
"""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

from stella.benchmark.scoring import (
    compare_pair_quantities,
    compare_quantity,
    score_paper,
    score_run,
)
from stella.schema_registry import schema_ref


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    script = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def gold_candidate(
    paper_id: str = "",
    gaia: str = "",
    aliases: list[str] | None = None,
    quantities: list[dict] | None = None,
) -> dict:
    return {
        "paper_candidate_id": paper_id,
        "gaia_source_id": gaia,
        "aliases": aliases or [],
        "origin_type": "introduced_by_this_paper",
        "quantities": quantities or [],
        "evidence": [{"location": "Sec 4"}],
    }


def gold_document(candidates: list[dict], status: str | None = None) -> dict:
    return {
        "schema": {"name": "benchmark.gold_annotation", "version": 1},
        "arxiv_id": "1902.05061",
        "status": status or ("candidates_found" if candidates else "no_candidates"),
        "candidates": candidates,
    }


def ai_candidate(
    record_id: str,
    paper_id: str = "",
    gaia: str = "",
    names: list[str] | None = None,
    core: dict | None = None,
) -> dict:
    all_entries = [{"value": value} for value in ([paper_id] if paper_id else []) + (names or [])]
    if gaia:
        all_entries.append({"value": gaia})
    return {
        "identifiers": {
            "record_id": record_id,
            "paper_candidate_id": paper_id,
            "gaia_source_id": gaia,
            "all": all_entries,
        },
        "core": core or {},
    }


def ai_document(candidates: list[dict]) -> dict:
    return {
        "extraction": {"status": "complete"},
        "candidates": candidates,
    }


def ai_quantity(value: str, unit: str = "", **extra) -> dict:
    return {"raw_value": value, "value": value, "unit": unit, **extra}


class L1MatchingTest(unittest.TestCase):
    def test_gaia_and_alias_matching_counts(self) -> None:
        gold = gold_document(
            [
                gold_candidate(paper_id="HVS-A", gaia="Gaia DR3 123456789012345"),
                gold_candidate(paper_id="StarB", aliases=["LAMOST J1234+5678"]),
            ]
        )
        ai = ai_document(
            [
                ai_candidate("x:cand-001", gaia="Gaia DR3 123456789012345"),
                ai_candidate("x:cand-002", paper_id="Star B"),
                ai_candidate("x:cand-003", paper_id="Unrelated"),
            ]
        )
        score, detail = score_paper("1902.05061", gold, ai, weight=1.0)
        self.assertEqual((score.tp, score.fp, score.fn), (2, 1, 0))
        self.assertEqual(score.match_methods, {"gaia_id": 1, "alias": 1})
        self.assertEqual(detail["unmatched_ai"], ["x:cand-003"])

    def test_negative_paper_counts_false_positives(self) -> None:
        gold = gold_document([], status="no_candidates")
        ai = ai_document([ai_candidate("x:cand-001", paper_id="Ghost")])
        score, _ = score_paper("1902.05061", gold, ai, weight=1.0)
        self.assertEqual((score.tp, score.fp, score.fn), (0, 1, 0))

    def test_missing_ai_output_counts_all_gold_as_fn(self) -> None:
        gold = gold_document([gold_candidate(paper_id="HVS-A")])
        score, _ = score_paper("1902.05061", gold, None, weight=1.0)
        self.assertTrue(score.ai_output_missing)
        self.assertEqual((score.tp, score.fp, score.fn), (0, 0, 1))

    def test_coordinate_tier_and_sensitivity(self) -> None:
        gold = gold_document(
            [
                gold_candidate(
                    quantities=[
                        {
                            "field": "observed_phase_space.ra",
                            "value": "188.5",
                            "unit": "deg",
                        },
                        {
                            "field": "observed_phase_space.dec",
                            "value": "-66.2",
                            "unit": "deg",
                        },
                    ],
                    aliases=["only-coords"],
                )
            ]
        )
        coordinate_core = {
            "observed_phase_space": {
                "ra": {
                    "value": "188.5001",
                    "unit": "deg",
                    "coordinate_format": "decimal_degrees",
                },
                "dec": {
                    "value": "-66.2",
                    "unit": "deg",
                    "coordinate_format": "decimal_degrees",
                },
            }
        }
        ai = ai_document([ai_candidate("x:cand-001", core=coordinate_core)])
        default_score, _ = score_paper("1902.05061", gold, ai, weight=1.0)
        strict_score, _ = score_paper(
            "1902.05061", gold, ai, weight=1.0, allow_coordinates=False
        )
        self.assertEqual(default_score.match_methods, {"coordinates": 1})
        self.assertEqual((default_score.tp, default_score.fp, default_score.fn), (1, 0, 0))
        self.assertEqual((strict_score.tp, strict_score.fp, strict_score.fn), (0, 1, 1))


class ScoreRunTest(unittest.TestCase):
    def build(self) -> tuple[dict, dict]:
        gold_annotations = {
            "1111.00001": gold_document(
                [gold_candidate(paper_id="HVS-A", gaia="Gaia DR3 42")]
            ),
            "1111.00002": gold_document([], status="no_candidates"),
        }
        ai_documents = {
            "1111.00001": ai_document(
                [ai_candidate("a:cand-001", gaia="Gaia DR3 42")]
            ),
            "1111.00002": ai_document(
                [ai_candidate("b:cand-001", paper_id="Ghost")]
            ),
        }
        return score_run(
            gold_annotations=gold_annotations,
            ai_documents=ai_documents,
            weights={"1111.00001": 2.0, "1111.00002": 1.0},
            run_label="unit-test",
            run_source={"mode": "unit"},
            bootstrap_iterations=200,
            bootstrap_seed=7,
        )

    def test_aggregates_and_negative_summary(self) -> None:
        scorecard, details = self.build()
        micro = scorecard["l1"]["micro"]
        self.assertEqual((micro["tp"], micro["fp"], micro["fn"]), (1, 1, 0))
        weighted = scorecard["l1"]["weighted_micro"]
        self.assertEqual((weighted["tp"], weighted["fp"]), (2.0, 1.0))
        negative = scorecard["l1"]["negative_papers"]
        self.assertEqual(negative["count"], 1)
        self.assertEqual(negative["papers_with_false_positives"], 1)
        self.assertEqual(len(details["papers"]), 2)

    def test_bootstrap_is_deterministic(self) -> None:
        first, _ = self.build()
        second, _ = self.build()
        self.assertEqual(first["l1"]["bootstrap"], second["l1"]["bootstrap"])
        self.assertEqual(first["l2"]["bootstrap"], second["l2"]["bootstrap"])

    def test_public_scorecard_does_not_leak_gold_identities(self) -> None:
        scorecard, details = self.build()
        scorecard_text = json.dumps(scorecard, ensure_ascii=False)
        details_text = json.dumps(details, ensure_ascii=False)
        self.assertNotIn("HVS-A", scorecard_text)
        self.assertIn("HVS-A", details_text)

    def test_scorecard_schema_and_config_echo(self) -> None:
        """R10: v0.2 schema with the scorer-config echo, l2_draft retired."""
        scorecard, _ = self.build()
        self.assertEqual(scorecard["schema"], schema_ref("benchmark.scorecard", 2))
        self.assertNotIn("l2_draft", scorecard)
        config = scorecard["l2"]["config"]
        self.assertEqual(config["coordinate_bridge_arcsec"], 0.5)
        self.assertEqual(config["projection"], "unconditional_flagged")
        self.assertIn("unit_synonyms_version", config)


class R1ComparisonSurfaceTest(unittest.TestCase):
    def test_ai_only_within_vocabulary_is_flagged(self) -> None:
        gold = gold_candidate(paper_id="HVS-A", quantities=[])
        ai = ai_candidate(
            "x:cand-001",
            paper_id="HVS-A",
            core={
                "observed_phase_space": {
                    "radial_velocity": ai_quantity("512", "km/s"),
                }
            },
        )
        rows = compare_pair_quantities(gold, ai)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "ai_only")
        self.assertEqual(rows[0]["field"], "observed_phase_space.radial_velocity")

    def test_gold_only_when_ai_field_empty(self) -> None:
        gold = gold_candidate(
            paper_id="HVS-A",
            quantities=[
                {
                    "field": "observed_phase_space.parallax",
                    "value": "0.05",
                    "unit": "mas",
                }
            ],
        )
        ai = ai_candidate("x:cand-001", paper_id="HVS-A", core={})
        rows = compare_pair_quantities(gold, ai)
        self.assertEqual(rows[0]["status"], "gold_only")

    def test_out_of_vocabulary_ai_fields_never_score(self) -> None:
        """total_velocity is outside the scored vocabulary: a bare AI
        total_velocity with no gold whole-speed row is not ai_only."""
        gold = gold_candidate(paper_id="HVS-A", quantities=[])
        ai = ai_candidate(
            "x:cand-001",
            paper_id="HVS-A",
            core={
                "derived_kinematics": {
                    "total_velocity": ai_quantity("640", "km/s"),
                }
            },
        )
        self.assertEqual(compare_pair_quantities(gold, ai), [])


class R2ProjectionTest(unittest.TestCase):
    def test_total_velocity_projection_fallback(self) -> None:
        gold = gold_candidate(
            paper_id="HVS-A",
            quantities=[
                {
                    "field": "derived_kinematics.galactic_rest_frame_velocity",
                    "value": "743",
                    "unit": "km/s",
                }
            ],
        )
        ai = ai_candidate(
            "x:cand-001",
            paper_id="HVS-A",
            core={
                "derived_kinematics": {
                    "total_velocity": ai_quantity("743", "km/s"),
                }
            },
        )
        rows = compare_pair_quantities(gold, ai)
        self.assertEqual(rows[0]["status"], "value_match")
        self.assertTrue(rows[0]["projected_from_total_velocity"])

    def test_own_field_wins_over_projection(self) -> None:
        gold = gold_candidate(
            paper_id="HVS-A",
            quantities=[
                {
                    "field": "derived_kinematics.galactic_rest_frame_velocity",
                    "value": "743",
                    "unit": "km/s",
                }
            ],
        )
        ai = ai_candidate(
            "x:cand-001",
            paper_id="HVS-A",
            core={
                "derived_kinematics": {
                    "galactic_rest_frame_velocity": ai_quantity("743", "km/s"),
                    "total_velocity": ai_quantity("999", "km/s"),
                }
            },
        )
        rows = compare_pair_quantities(gold, ai)
        self.assertEqual(rows[0]["status"], "value_match")
        self.assertNotIn("projected_from_total_velocity", rows[0])

    def test_without_projection_view_reverts_to_gold_only(self) -> None:
        gold_annotations = {
            "1111.00001": gold_document(
                [
                    gold_candidate(
                        paper_id="HVS-A",
                        gaia="Gaia DR3 42",
                        quantities=[
                            {
                                "field": "derived_kinematics.galactic_rest_frame_velocity",
                                "value": "743",
                                "unit": "km/s",
                            }
                        ],
                    )
                ]
            ),
        }
        ai_documents = {
            "1111.00001": ai_document(
                [
                    ai_candidate(
                        "a:cand-001",
                        gaia="Gaia DR3 42",
                        core={
                            "derived_kinematics": {
                                "total_velocity": ai_quantity("743", "km/s"),
                            }
                        },
                    )
                ]
            ),
        }
        scorecard, _ = score_run(
            gold_annotations=gold_annotations,
            ai_documents=ai_documents,
            weights={},
            run_label="unit-test",
            run_source={"mode": "unit"},
            bootstrap_iterations=10,
            bootstrap_seed=7,
        )
        with_projection = scorecard["l2"]["micro"]
        without = scorecard["l2"]["micro_without_projection"]
        self.assertEqual(with_projection["delivery_end_to_end_strict"], 1.0)
        self.assertIsNone(without["agreement_over_compared_strict"])
        self.assertEqual(without["coverage"], 0.0)


class R3NumericLadderTest(unittest.TestCase):
    FIELD = "observed_phase_space.radial_velocity"

    def quantity(self, **extra) -> dict:
        return {"field": self.FIELD, "value": "234", "unit": "km/s", **extra}

    def test_exact_match_ignores_spelling(self) -> None:
        row = compare_quantity(self.FIELD, self.quantity(), ai_quantity("234.0", "km/s"))
        self.assertEqual(row["status"], "value_match")

    def test_approximation_marker_is_stripped(self) -> None:
        row = compare_quantity(self.FIELD, self.quantity(), ai_quantity("~234", "km/s"))
        self.assertEqual(row["status"], "value_match")

    def test_within_symmetric_gold_error(self) -> None:
        row = compare_quantity(
            self.FIELD, self.quantity(error="5"), ai_quantity("236", "km/s")
        )
        self.assertEqual(row["status"], "within_gold_error")

    def test_directional_asymmetric_error(self) -> None:
        above = compare_quantity(
            self.FIELD,
            self.quantity(lower_error="2", upper_error="10"),
            ai_quantity("242", "km/s"),
        )
        below = compare_quantity(
            self.FIELD,
            self.quantity(lower_error="2", upper_error="10"),
            ai_quantity("226", "km/s"),
        )
        self.assertEqual(above["status"], "within_gold_error")
        self.assertEqual(below["status"], "value_mismatch")

    def test_plain_mismatch(self) -> None:
        row = compare_quantity(self.FIELD, self.quantity(), ai_quantity("-485", "km/s"))
        self.assertEqual(row["status"], "value_mismatch")


class R4UnitTest(unittest.TestCase):
    def test_unit_synonyms_match(self) -> None:
        row = compare_quantity(
            "observed_phase_space.radial_velocity",
            {"field": "observed_phase_space.radial_velocity", "value": "234", "unit": "km/s"},
            ai_quantity("234", "km s^-1"),
        )
        self.assertEqual(row["status"], "value_match")

    def test_no_dimensional_conversion(self) -> None:
        row = compare_quantity(
            "observed_phase_space.distance",
            {"field": "observed_phase_space.distance", "value": "8.2", "unit": "kpc"},
            ai_quantity("8.2", "pc"),
        )
        self.assertEqual(row["status"], "unit_mismatch")

    def test_one_sided_missing_unit_compares_values(self) -> None:
        row = compare_quantity(
            "observed_phase_space.distance",
            {"field": "observed_phase_space.distance", "value": "8.2", "unit": "kpc"},
            ai_quantity("8.2", ""),
        )
        self.assertEqual(row["status"], "value_match")
        self.assertTrue(row["unit_missing_one_side"])

    def test_latex_residue_is_spelling_not_mismatch(self) -> None:
        # Synonym table v2: braces, $ delimiters, \mathrm, and spacing
        # macros are markup residue, not a different printed unit
        # (gold8-b-01 regression: "mas yr^{-1}" vs "mas yr^-1").
        for spelling in (
            "mas yr^{-1}",
            "mas yr$^{-1}$",
            r"$\mathrm{mas\,yr^{-1}}$",
        ):
            row = compare_quantity(
                "observed_phase_space.proper_motion_ra",
                {
                    "field": "observed_phase_space.proper_motion_ra",
                    "value": "-15.377",
                    "unit": "mas yr^-1",
                },
                ai_quantity("-15.377", spelling),
            )
            self.assertEqual(row["status"], "value_match", spelling)

    def test_latex_stripping_never_converts_dimensions(self) -> None:
        row = compare_quantity(
            "observed_phase_space.distance",
            {"field": "observed_phase_space.distance", "value": "8.2", "unit": "kpc"},
            ai_quantity("8.2", "{pc}"),
        )
        self.assertEqual(row["status"], "unit_mismatch")


class R5CoordinateTest(unittest.TestCase):
    def test_same_format_sexagesimal_match(self) -> None:
        row = compare_quantity(
            "observed_phase_space.ra",
            {"field": "observed_phase_space.ra", "value": "12:34:02.88", "unit": "hms"},
            ai_quantity("12:34:02.88", "", coordinate_format="sexagesimal_colon"),
        )
        self.assertEqual(row["status"], "value_match")

    def test_cross_format_within_bridge(self) -> None:
        """Regression fixture modeled on the dec mismatch from dev round 1:
        gold transcribes the PDF's sexagesimal, the AI the ECSV decimal."""
        row = compare_quantity(
            "observed_phase_space.dec",
            {"field": "observed_phase_space.dec", "value": "-66:12:00.5", "unit": "dms"},
            ai_quantity("-66.20008", "deg", coordinate_format="decimal_degrees"),
        )
        self.assertEqual(row["status"], "value_match_cross_format")

    def test_cross_format_exact_is_labeled_cross_format(self) -> None:
        row = compare_quantity(
            "observed_phase_space.ra",
            {"field": "observed_phase_space.ra", "value": "12:34:02.88", "unit": "hms"},
            ai_quantity("188.512", "deg", coordinate_format="decimal_degrees"),
        )
        self.assertEqual(row["status"], "value_match_cross_format")

    def test_cross_format_beyond_bridge_is_mismatch(self) -> None:
        row = compare_quantity(
            "observed_phase_space.dec",
            {"field": "observed_phase_space.dec", "value": "-66:12:00", "unit": "dms"},
            ai_quantity("-66.2050", "deg", coordinate_format="decimal_degrees"),
        )
        self.assertEqual(row["status"], "value_mismatch")


class R6LimitTest(unittest.TestCase):
    def test_limit_kind_flip_is_semantic_error(self) -> None:
        row = compare_quantity(
            "derived_kinematics.galactic_rest_frame_velocity",
            {
                "field": "derived_kinematics.galactic_rest_frame_velocity",
                "value": "700",
                "unit": "km/s",
            },
            ai_quantity("700", "km/s", limit_kind="lower_limit"),
        )
        self.assertEqual(row["status"], "limit_kind_mismatch")

    def test_range_bounds_use_numeric_ladder(self) -> None:
        gold = {
            "field": "observed_phase_space.distance",
            "value": "",
            "limit_kind": "range",
            "range_lower": "8.2",
            "range_upper": "11.6",
            "unit": "kpc",
        }
        exact = compare_quantity(
            "observed_phase_space.distance",
            gold,
            {
                "value": "",
                "limit_kind": "range",
                "range_lower": "8.20",
                "range_upper": "11.6",
                "unit": "kpc",
            },
        )
        off = compare_quantity(
            "observed_phase_space.distance",
            gold,
            {
                "value": "",
                "limit_kind": "range",
                "range_lower": "8.2",
                "range_upper": "11.7",
                "unit": "kpc",
            },
        )
        self.assertEqual(exact["status"], "value_match")
        self.assertEqual(off["status"], "value_mismatch")


class R7ProbabilityTest(unittest.TestCase):
    def test_percent_and_fraction_align_both_ways(self) -> None:
        fraction_gold = compare_quantity(
            "bound_assessment.unbound_probability",
            {
                "field": "bound_assessment.unbound_probability",
                "value": "0.99995",
                "unit": "",
            },
            ai_quantity("99.995", "%"),
        )
        percent_gold = compare_quantity(
            "bound_assessment.bound_probability",
            {
                "field": "bound_assessment.bound_probability",
                "value": "98",
                "unit": "%",
            },
            ai_quantity("0.98", ""),
        )
        self.assertEqual(fraction_gold["status"], "value_match")
        self.assertEqual(percent_gold["status"], "value_match")


class R8GoldNoteTest(unittest.TestCase):
    def test_mismatch_carries_gold_note_flag(self) -> None:
        row = compare_quantity(
            "derived_kinematics.galactic_rest_frame_velocity",
            {
                "field": "derived_kinematics.galactic_rest_frame_velocity",
                "value": "743",
                "unit": "km/s",
                "notes": "paper also quotes 820 km/s under a GC-origin prior",
            },
            ai_quantity("820", "km/s"),
        )
        self.assertEqual(row["status"], "value_mismatch")
        self.assertTrue(row["gold_note_present"])


class R9AggregationTest(unittest.TestCase):
    def build(self) -> tuple[dict, dict]:
        rv = {
            "field": "observed_phase_space.radial_velocity",
            "value": "234",
            "unit": "km/s",
        }
        distance = {
            "field": "observed_phase_space.distance",
            "value": "8.2",
            "unit": "kpc",
        }
        gold_annotations = {
            # Paper 1: one matched candidate (rv correct, distance ai_only
            # hallucination check) and one L1-missed candidate whose two
            # quantities must propagate as gold_only.
            "1111.00001": gold_document(
                [
                    gold_candidate(paper_id="HVS-A", gaia="Gaia DR3 42", quantities=[rv]),
                    gold_candidate(paper_id="HVS-B", quantities=[rv, distance]),
                ]
            ),
            # Paper 2: negative paper — its FP must stay out of L2 entirely.
            "1111.00002": gold_document([], status="no_candidates"),
        }
        ai_documents = {
            "1111.00001": ai_document(
                [
                    ai_candidate(
                        "a:cand-001",
                        gaia="Gaia DR3 42",
                        core={
                            "observed_phase_space": {
                                "radial_velocity": ai_quantity("234", "km/s"),
                                "distance": ai_quantity("9.9", "kpc"),
                            }
                        },
                    )
                ]
            ),
            "1111.00002": ai_document([ai_candidate("b:cand-001", paper_id="Ghost")]),
        }
        return score_run(
            gold_annotations=gold_annotations,
            ai_documents=ai_documents,
            weights={"1111.00001": 2.0},
            run_label="unit-test",
            run_source={"mode": "unit"},
            bootstrap_iterations=50,
            bootstrap_seed=7,
        )

    def test_l1_misses_propagate_and_layers_diverge(self) -> None:
        scorecard, _ = self.build()
        micro = scorecard["l2"]["micro"]
        matched_only = scorecard["l2"]["micro_matched_pairs_only"]
        # 3 gold quantities total; 1 compared and correct; 2 gold_only from
        # the missed candidate; 1 ai_only hallucination.
        self.assertEqual(micro["gold_quantities"], 3)
        self.assertEqual(micro["compared"], 1)
        self.assertEqual(micro["ai_only"], 1)
        self.assertEqual(micro["agreement_over_compared_strict"], 1.0)
        self.assertAlmostEqual(micro["delivery_end_to_end_strict"], 1 / 3)
        self.assertEqual(micro["fill_precision_strict"], 0.5)
        # Matched-pairs-only view is independent of the L1 miss.
        self.assertEqual(matched_only["gold_quantities"], 1)
        self.assertEqual(matched_only["delivery_end_to_end_strict"], 1.0)

    def test_negative_paper_excluded_from_l2(self) -> None:
        scorecard, _ = self.build()
        per_field = scorecard["l2"]["per_field"]
        total_rows = sum(
            bucket["gold_quantities"] + bucket["ai_only"]
            for bucket in per_field.values()
        )
        self.assertEqual(total_rows, 4)  # nothing from the negative paper

    def test_weighted_micro_uses_sampling_weights(self) -> None:
        scorecard, _ = self.build()
        weighted = scorecard["l2"]["weighted_micro"]
        self.assertEqual(weighted["gold_quantities"], 6.0)
        self.assertEqual(weighted["strict_matches"], 2.0)


class LeakGuardHelperTest(unittest.TestCase):
    def test_gold_marker_strings_collects_identities_and_values(self) -> None:
        cli = load_script("score_benchmark_run")
        details = {
            "papers": [
                {
                    "pairs": [
                        {
                            "gold_id": "HVS-A-LONG",
                            "l2": [
                                {
                                    "field": "observed_phase_space.radial_velocity",
                                    "status": "value_match",
                                    "gold": "234 ± 5 km/s",
                                    "gold_note": "alternate 240 km/s",
                                }
                            ],
                        }
                    ],
                    "unmatched_gold": [
                        {
                            "gold_id": "S5-HVS1",
                            "l2": [
                                {
                                    "field": "observed_phase_space.distance",
                                    "status": "gold_only",
                                    "gold": "8.2 kpc",
                                }
                            ],
                        }
                    ],
                    "unmatched_ai": [],
                }
            ]
        }
        markers = cli.gold_marker_strings(details)
        self.assertIn("HVS-A-LONG", markers)
        self.assertIn("S5-HVS1", markers)
        self.assertIn("234 ± 5 km/s", markers)
        self.assertIn("8.2 kpc", markers)
        self.assertIn("alternate 240 km/s", markers)


if __name__ == "__main__":
    unittest.main()
