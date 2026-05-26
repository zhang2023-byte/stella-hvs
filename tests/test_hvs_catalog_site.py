from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stella_html.catalog_site import (  # noqa: E402
    CANDIDATES_DIRNAME,
    build_index_row,
    build_static_html,
    has_external_html_dependencies,
    load_catalog_snapshot,
    method_lineage,
    render_live_index_html,
)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def quantity(
    value: str,
    *,
    unit: str = "km/s",
    method_ref: str = "step-02",
    lower_error: str = "",
    upper_error: str = "",
) -> dict[str, object]:
    record: dict[str, object] = {"value": value, "unit": unit, "method_refs": [method_ref]}
    if lower_error:
        record["lower_error"] = lower_error
    if upper_error:
        record["upper_error"] = upper_error
    return record


def object_record() -> dict[str, object]:
    return {
        "schema_version": "stella.hvs_candidate_catalog.object.v5",
        "generated_at": "2026-05-20T10:00:00",
        "object_id": "Gaia_DR3_123",
        "canonical_identifier": {"kind": "gaia_source_id", "value": "Gaia DR3 123", "source": "src-001"},
        "sources": [
            {
                "source": "src-001",
                "paper": {
                    "arxiv_id": "2601.00001",
                    "bibcode": "2026A&A...001A...1A",
                    "title": "First paper",
                    "month": "2026-01",
                    "links": {"abs": "https://arxiv.org/abs/2601.00001"},
                },
                "source_json_path": "literature/2601.00001/literature_hvs_candidates.json",
                "record_id": "2601.00001:cand-001",
                "paper_candidate_id": "HVS-A",
                "gaia_source_id": "Gaia DR3 123",
            },
            {
                "source": "src-002",
                "paper": {
                    "arxiv_id": "2602.00002",
                    "bibcode": "2026MNRAS.002..2B",
                    "title": "Second paper",
                    "month": "2026-02",
                    "links": {"abs": "https://arxiv.org/abs/2602.00002"},
                },
                "source_json_path": "literature/2602.00002/literature_hvs_candidates.json",
                "record_id": "2602.00002:cand-001",
                "paper_candidate_id": "HVS-B",
                "gaia_source_id": "Gaia DR3 123",
            },
        ],
        "method_chain": [
            {
                "source": "src-001",
                "steps": [
                    {"id": "step-01", "step_type": "input_catalog", "summary": "Input.", "depends_on": []},
                    {
                        "id": "step-02",
                        "step_type": "velocity_calculation",
                        "summary": "Velocity.",
                        "depends_on": ["step-01"],
                    },
                    {
                        "id": "step-03",
                        "step_type": "escape_or_bound_assessment",
                        "summary": "Probability.",
                        "depends_on": ["step-02"],
                    },
                ],
            }
        ],
        "candidates": [
            {
                "source": "src-001",
                "identifiers": {
                    "record_id": "2601.00001:cand-001",
                    "paper_candidate_id": "HVS-A",
                    "gaia_source_id": "Gaia DR3 123",
                },
                "candidate_context": {
                    "paper_labels": ["hvs_candidate"],
                    "galactic_bound_claim": "unbound",
                    "inclusion_basis": "explicit_unbound_text",
                    "extraction_confidence": "high",
                    "origin_type": "introduced_by_this_paper",
                    "paper_reassesses_unbound_status": True,
                },
                "core": {
                    "observed_phase_space": {
                        "ra": quantity("10.1", unit="deg", method_ref="step-01"),
                        "dec": quantity("-20.2", unit="deg", method_ref="step-01"),
                        "parallax": quantity("0.31", unit="mas", method_ref="step-01"),
                        "proper_motion_ra": quantity("1.2", unit="mas/yr", method_ref="step-01"),
                        "proper_motion_dec": quantity("-0.2", unit="mas/yr", method_ref="step-01"),
                        "radial_velocity": quantity("510", unit="km/s", method_ref="step-01"),
                    },
                    "derived_kinematics": {
                        "total_velocity": quantity("740", method_ref="step-02", lower_error="-20", upper_error="+30")
                    },
                    "bound_assessment": {"unbound_probability": quantity("0.82", unit="", method_ref="step-03")},
                },
                "photometry": [{"measurement_type": "magnitude", "band": "G", **quantity("17.1", unit="mag")}],
                "spectroscopy": [],
                "stellar_parameters": {"mass": quantity("3.0", unit="Msun"), "other": []},
                "abundances": [],
                "quality_flags": [{"name": "RUWE", **quantity("1.1", unit="")}],
                "orbit": {"flight_time": quantity("40", unit="Myr"), "other": []},
                "astrophysical_origin": {
                    "origin_site": quantity("LMC", unit=""),
                    "hypothesis_metrics": [
                        {"hypothesis": "LMC origin", "metric_type": "probability", **quantity("0.7", unit="")}
                    ],
                    "other": [],
                },
                "extra": [{"name": "custom_metric", **quantity("42", unit="")}],
            },
            {
                "source": "src-002",
                "identifiers": {
                    "record_id": "2602.00002:cand-001",
                    "paper_candidate_id": "HVS-B",
                    "gaia_source_id": "Gaia DR3 123",
                },
                "candidate_context": {
                    "paper_labels": ["hvs_candidate"],
                    "galactic_bound_claim": "possibly_unbound",
                    "inclusion_basis": "explicit_candidate_text",
                    "extraction_confidence": "medium",
                    "origin_type": "cited_from_literature",
                    "paper_reassesses_unbound_status": True,
                },
                "core": {
                    "observed_phase_space": {
                        "ra": quantity("10.3", unit="deg", method_ref="step-01"),
                        "dec": quantity("-20.4", unit="deg", method_ref="step-01"),
                        "parallax": quantity("0.12", unit="mas", method_ref="step-01"),
                    },
                    "derived_kinematics": {"total_velocity": quantity("690", method_ref="step-02")},
                    "bound_assessment": {},
                },
                "photometry": [],
                "spectroscopy": [],
                "stellar_parameters": {"other": []},
                "abundances": [],
                "quality_flags": [],
                "orbit": {"other": []},
                "astrophysical_origin": {"hypothesis_metrics": [], "other": []},
                "extra": [],
            },
        ],
        "external_enrichment": {
            "status": "success",
            "queried_at": "2026-05-20T10:00:00",
            "providers": {
                "simbad": {
                    "status": "matched",
                    "matched_by": "identifier",
                    "main_id": "HVS-A",
                    "object_type": "Star",
                    "radial_velocity": {"value": "505", "unit": "km/s"},
                },
                "gaia_dr3": {
                    "status": "matched",
                    "matched_by": "source_id",
                    "source_id": "123",
                    "designation": "Gaia DR3 123",
                },
            },
            "verification": {
                "coordinate_separations_arcsec": {"simbad": 0.2, "gaia_dr3": 0.1},
                "value_comparisons": [
                    {
                        "source": "src-001",
                        "field": "radial_velocity",
                        "literature_value": "510",
                        "official_value": 505,
                        "difference": 5,
                        "unit": "km/s",
                    }
                ],
            },
            "warnings": [{"type": "simbad_coordinate_match", "message": "Matched by coordinates."}],
        },
        "dynamics": {
            "schema_version": "stella.hvs_dynamics.v1",
            "generated_at": "2026-05-20T10:00:00",
            "status": "computed",
            "status_reason": "",
            "gaia_source_id": "Gaia DR3 123",
            "radial_velocity_source": {
                "source": "literature",
                "source_detail": "literature/2601.00001/literature_hvs_candidates.json",
                "value": 510,
                "error": 2,
                "unit": "km/s",
                "bibcode": "",
                "lower_limit": False,
            },
            "astrometry": {
                "provider": "external_enrichment.providers.gaia_dr3.raw_columns",
                "source_id": "123",
                "corrected_parallax_mas": 0.29,
                "parallax_error_mas": 0.03,
                "corrected_parallax_over_error": 9.67,
            },
            "sampling": {"sample_count": 10000},
            "total_velocity_grf_kms": {"p16": 700, "median": 740, "p84": 780},
            "escape_velocity_kms": {"p16": 610, "median": 620, "p84": 630},
            "p_bound_beta": {"p16": 0.17, "median": 0.18, "p84": 0.19},
            "p_unbound_beta": {"p16": 0.81, "median": 0.82, "p84": 0.83},
            "mc_counts": {"sample_count": 10000, "bound_count": 1800, "unbound_count": 8200},
            "graveyard": False,
            "lower_limit": False,
            "warnings": [{"type": "rv_source", "message": "Using literature RV."}],
        },
        "merge": {
            "match_strategy": "gaia_source_id",
            "evidence": [{"evidence_type": "gaia_source_id", "decision": "accepted"}],
            "warnings": [],
        },
    }


class HvsCatalogSiteTest(unittest.TestCase):
    def test_snapshot_loads_catalog_and_counts_objects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp) / "catalog"
            write_json(
                catalog / "03_hvs_candidates_index.json",
                {
                    "schema_version": "stella.hvs_candidate_catalog.index.v3",
                    "summary": {
                        "object_count": 1,
                        "source_count": 2,
                        "candidate_count": 2,
                        "objects_with_gaia_count": 1,
                        "warning_count": 0,
                        "skipped_count": 0,
                    },
                    "objects": [{"object_id": "Gaia_DR3_123"}],
                },
            )
            write_json(catalog / CANDIDATES_DIRNAME / "Gaia_DR3_123.json", object_record())

            snapshot = load_catalog_snapshot(catalog)

            self.assertEqual(snapshot["schema_version"], "stella.hvs_catalog_site.snapshot.v2")
            self.assertEqual(snapshot["summary"]["object_count"], 1)
            self.assertEqual(len(snapshot["objects"]), 1)
            self.assertEqual(snapshot["rows"][0]["identifier"], "Gaia DR3 123")
            self.assertEqual(snapshot["rows"][0]["dynamics"]["status"], "computed")

    def test_snapshot_ignores_old_object_schema_versions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp) / "catalog"
            write_json(catalog / "03_hvs_candidates_index.json", {"summary": {}, "objects": []})
            old_record = object_record()
            old_record["schema_version"] = "stella.hvs_candidate_catalog.object.v2"
            write_json(catalog / CANDIDATES_DIRNAME / "Gaia_DR3_123.json", old_record)

            snapshot = load_catalog_snapshot(catalog)

            self.assertEqual(snapshot["objects"], [])
            self.assertEqual(snapshot["rows"], [])

    def test_index_row_extracts_quantities_without_source_overwrite(self) -> None:
        row = build_index_row(object_record())

        self.assertEqual(row["bibcodes"], ["2026A&A...001A...1A", "2026MNRAS.002..2B"])
        self.assertEqual(row["sources"][0]["phase_space"]["ra"], "10.1")
        self.assertNotIn("distance", row["sources"][0]["phase_space"])
        self.assertEqual(row["sources"][0]["phase_space"]["parallax"], "0.31")
        self.assertEqual(row["sources"][0]["total_velocity"], "740 -20 +30")
        self.assertEqual(row["sources"][0]["unbound_probability"], "0.82")
        self.assertEqual(row["sources"][1]["phase_space"]["ra"], "10.3")
        self.assertEqual(row["sources"][1]["phase_space"]["parallax"], "0.12")
        self.assertEqual(row["sources"][1]["total_velocity"], "690")
        self.assertEqual(row["sources"][1]["unbound_probability"], "")
        self.assertEqual(row["enrichment_status"], "success")
        self.assertEqual(row["candidate_context"]["bound_claims"], ["unbound", "possibly_unbound"])
        self.assertEqual(row["candidate_context"]["origin_types"], ["introduced_by_this_paper", "cited_from_literature"])
        self.assertEqual(row["dynamics"]["status"], "computed")
        self.assertEqual(row["dynamics"]["p_unbound"]["median"], 0.82)
        self.assertEqual(row["dynamics"]["total_velocity_grf_kms"]["median"], 740.0)
        self.assertEqual(row["dynamics"]["escape_velocity_kms"]["median"], 620.0)
        self.assertEqual(row["dynamics"]["velocity_margin_kms"], 120.0)
        self.assertEqual(row["dynamics"]["radial_velocity_source"]["source"], "literature")
        self.assertEqual(row["dynamics"]["corrected_parallax_over_error"], 9.67)
        self.assertEqual(row["dynamics"]["warning_count"], 1)
        self.assertEqual(row["external"]["status"], "success")
        self.assertEqual(row["external"]["gaia_dr3"]["matched_by"], "source_id")
        self.assertEqual(row["external"]["simbad"]["matched_by"], "identifier")
        self.assertEqual(row["external"]["warning_count"], 1)
        self.assertEqual(row["external"]["value_comparison_count"], 1)
        self.assertEqual(row["merge"]["evidence_count"], 1)
        self.assertEqual(row["quantity_coverage"]["photometry"], 1)

    def test_index_row_extracts_skipped_dynamics_audit(self) -> None:
        record = object_record()
        record["dynamics"] = {
            "schema_version": "stella.hvs_dynamics.v1",
            "status": "skipped",
            "status_reason": "parallax uncertainty too large",
            "astrometry": {
                "corrected_parallax_mas": 0.35,
                "parallax_error_mas": 0.10,
                "corrected_parallax_over_error": 3.5,
            },
            "warnings": [],
        }

        row = build_index_row(record)

        self.assertEqual(row["dynamics"]["status"], "skipped")
        self.assertEqual(row["dynamics"]["status_reason"], "parallax uncertainty too large")
        self.assertEqual(row["dynamics"]["corrected_parallax_over_error"], 3.5)
        self.assertIsNone(row["dynamics"]["p_unbound"]["median"])
        self.assertFalse(row["dynamics"]["lower_limit"])

    def test_method_lineage_follows_recursive_dependencies(self) -> None:
        steps = object_record()["method_chain"][0]["steps"]  # type: ignore[index]

        lineage = method_lineage(steps, ["step-03"])  # type: ignore[arg-type]

        self.assertEqual(lineage["direct"], ["step-03"])
        self.assertEqual(lineage["ancestors"], ["step-01", "step-02"])
        self.assertEqual(lineage["edges"], ["step-01->step-02", "step-02->step-03"])

    def test_live_html_points_at_catalog_root(self) -> None:
        html = render_live_index_html(catalog_root="../..")

        self.assertIn('data-catalog-root="../.."', html)

    def test_static_html_is_self_contained(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = root / "catalog"
            assets = root / "assets"
            write_json(catalog / "03_hvs_candidates_index.json", {"summary": {"object_count": 1}, "objects": []})
            write_json(catalog / CANDIDATES_DIRNAME / "Gaia_DR3_123.json", object_record())
            assets.mkdir()
            css_path = assets / "stella.css"
            js_path = assets / "catalog-viewer.js"
            hero_path = assets / "stella-hero.svg"
            css_path.write_text('.hero { background-image: url("stella-hero.svg"); }', encoding="utf-8")
            js_path.write_text('document.body.dataset.loaded = "yes";', encoding="utf-8")
            hero_path.write_text("<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>", encoding="utf-8")

            html = build_static_html(catalog, css_path, js_path, hero_path)

            self.assertIn("window.STELLA_CATALOG_SNAPSHOT", html)
            self.assertIn("data:image/svg+xml;base64", html)
            self.assertFalse(has_external_html_dependencies(html))
            self.assertNotIn("<script src=", html)
            self.assertNotIn("<link href=", html)


if __name__ == "__main__":
    unittest.main()
