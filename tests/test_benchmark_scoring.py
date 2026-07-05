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
        "schema_version": "stella.benchmark_gold_annotation.v0.1",
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

    def test_public_scorecard_does_not_leak_gold_identities(self) -> None:
        scorecard, details = self.build()
        scorecard_text = json.dumps(scorecard, ensure_ascii=False)
        details_text = json.dumps(details, ensure_ascii=False)
        self.assertNotIn("HVS-A", scorecard_text)
        self.assertIn("HVS-A", details_text)


class L2DraftTest(unittest.TestCase):
    def test_unit_synonyms_match(self) -> None:
        row = compare_quantity(
            "observed_phase_space.radial_velocity",
            {"field": "observed_phase_space.radial_velocity", "value": "234", "unit": "km/s"},
            ai_quantity("234", "km s^-1"),
        )
        self.assertEqual(row["status"], "value_match")

    def test_probability_percent_normalization(self) -> None:
        row = compare_quantity(
            "bound_assessment.unbound_probability",
            {
                "field": "bound_assessment.unbound_probability",
                "value": "0.99995",
                "unit": "",
            },
            ai_quantity("99.995", "%"),
        )
        self.assertEqual(row["status"], "value_match")

    def test_within_gold_error(self) -> None:
        row = compare_quantity(
            "observed_phase_space.radial_velocity",
            {
                "field": "observed_phase_space.radial_velocity",
                "value": "234",
                "error": "5",
                "unit": "km/s",
            },
            ai_quantity("236", "km/s"),
        )
        self.assertEqual(row["status"], "within_gold_error")

    def test_unit_mismatch(self) -> None:
        row = compare_quantity(
            "observed_phase_space.distance",
            {"field": "observed_phase_space.distance", "value": "8.2", "unit": "kpc"},
            ai_quantity("8.2", "pc"),
        )
        self.assertEqual(row["status"], "unit_mismatch")

    def test_range_bounds_compare(self) -> None:
        row = compare_quantity(
            "observed_phase_space.distance",
            {
                "field": "observed_phase_space.distance",
                "value": "",
                "limit_kind": "range",
                "range_lower": "8.2",
                "range_upper": "11.6",
                "unit": "kpc",
            },
            {
                "value": "",
                "limit_kind": "range",
                "range_lower": "8.2",
                "range_upper": "11.6",
                "unit": "kpc",
            },
        )
        self.assertEqual(row["status"], "value_match")

    def test_sexagesimal_exact_string(self) -> None:
        row = compare_quantity(
            "observed_phase_space.ra",
            {"field": "observed_phase_space.ra", "value": "12:34:02.88", "unit": "hms"},
            ai_quantity("12:34:02.88", "hms"),
        )
        self.assertEqual(row["status"], "value_match")

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


class LeakGuardHelperTest(unittest.TestCase):
    def test_gold_marker_strings_collects_identities(self) -> None:
        cli = load_script("score_benchmark_run")
        details = {
            "papers": [
                {
                    "pairs": [{"gold_id": "HVS-A-LONG"}],
                    "unmatched_gold": ["S5-HVS1"],
                    "unmatched_ai": [],
                }
            ]
        }
        markers = cli.gold_marker_strings(details)
        self.assertIn("HVS-A-LONG", markers)
        self.assertIn("S5-HVS1", markers)


if __name__ == "__main__":
    unittest.main()
