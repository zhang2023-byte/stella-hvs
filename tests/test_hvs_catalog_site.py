from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module

from stella.html.catalog_site import (  # noqa: E402
    CANDIDATES_DIRNAME,
    build_index_row,
    build_static_html,
    build_static_site,
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
                        "distance": quantity("8.2", unit="kpc", method_ref="step-01"),
                    },
                    "derived_kinematics": {
                        "total_velocity": quantity("740", method_ref="step-02", lower_error="-20", upper_error="+30")
                    },
                    "bound_assessment": {"unbound_probability": quantity("0.82", unit="", method_ref="step-03")},
                },
                "photometry": [{"measurement_type": "magnitude", "band": "G", **quantity("17.1", unit="mag")}],
                "spectroscopy": [{"measurement_type": "spectral_type", "spectral_type": "B9", "value": "B9"}],
                "stellar_parameters": {
                    "teff": quantity("12000", unit="K"),
                    "log_g": quantity("4.1", unit="dex"),
                    "metallicity": quantity("-1.2", unit="dex"),
                    "mass": quantity("3.0", unit="Msun"),
                    "other": [],
                },
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
                        "spectral_type": {"value": "B8", "bibcode": "2026A&A...001A...1A"},
                    },
                    "gaia_dr3": {
                        "status": "matched",
                        "matched_by": "source_id",
                        "source_id": "123",
                        "designation": "Gaia DR3 123",
                        "astrometry": {
                            "ra": {"value": 10.11, "unit": "deg"},
                            "dec": {"value": -20.21, "unit": "deg"},
                            "parallax": {"value": 0.29, "unit": "mas"},
                            "pmra": {"value": 1.1, "unit": "mas / yr"},
                            "pmdec": {"value": -0.3, "unit": "mas / yr"},
                        },
                        "photometry": {
                            "phot_g_mean_mag": {"value": 17.2, "unit": "mag"},
                            "bp_rp": {"value": 0.4, "unit": "mag"},
                        },
                        "stellar_parameters": {
                            "distance_gspphot": {"value": 8000, "unit": "pc"},
                            "teff_gspphot": {"value": 11900, "unit": "K"},
                            "logg_gspphot": {"value": 4.0, "unit": "log(cm.s**-2)"},
                            "mh_gspphot": {"value": -1.1, "unit": "dex"},
                        },
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
            "posterior": {"heliocentric_distance_kpc": {"p16": 7.4, "median": 8.0, "p84": 8.6}},
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

    def test_snapshot_reads_local_ads_metadata_for_reported_by(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = root / "catalog"
            literature = root / "literature"
            write_json(
                catalog / "03_hvs_candidates_index.json",
                {"summary": {"object_count": 1}, "objects": [{"object_id": "Gaia_DR3_123"}]},
            )
            write_json(catalog / CANDIDATES_DIRNAME / "Gaia_DR3_123.json", object_record())
            write_json(
                literature / "2601.00001" / "ads_metadata.json",
                {
                    "response": {
                        "docs": [
                            {
                                "first_author": "Alpha, A.",
                                "author": ["Alpha, A.", "Beta, B."],
                                "year": "2026",
                                "pubdate": "2026-01-04",
                                "citation_count": 5,
                                "bibcode": "2026A&A...001A...1A",
                            }
                        ]
                    }
                },
            )
            write_json(
                literature / "2602.00002" / "ads_metadata.json",
                {
                    "response": {
                        "docs": [
                            {
                                "first_author": "Gamma, G.",
                                "author": ["Gamma, G."],
                                "year": "2026",
                                "pubdate": "2026-02-01",
                                "citation_count": 42,
                                "bibcode": "2026MNRAS.002..2B",
                            }
                        ]
                    }
                },
            )

            snapshot = load_catalog_snapshot(catalog, literature_dir=literature)
            row = snapshot["rows"][0]

            self.assertEqual(row["discovery_month"], "2026-01")
            self.assertEqual(row["sources"][0]["paper_metadata"]["reported_by"], "Alpha et al. 2026")
            self.assertEqual(row["sources"][0]["paper_metadata"]["citation_count"], 5.0)
            self.assertEqual(row["sources"][1]["paper_metadata"]["reported_by"], "Gamma 2026")
            self.assertEqual(snapshot["paper_metadata"]["2602.00002"]["citation_count"], 42.0)

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

    def test_snapshot_skips_malformed_candidate_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalog = Path(tmp) / "catalog"
            write_json(
                catalog / "03_hvs_candidates_index.json",
                {"summary": {}, "objects": [{"object_id": "Gaia_DR3_123"}]},
            )
            write_json(catalog / CANDIDATES_DIRNAME / "Gaia_DR3_123.json", object_record())
            # A corrupt sibling JSON must not abort the whole snapshot build.
            (catalog / CANDIDATES_DIRNAME / "broken.json").write_text("{ not json", encoding="utf-8")

            snapshot = load_catalog_snapshot(catalog)

            self.assertEqual(len(snapshot["objects"]), 1)
            self.assertEqual(snapshot["rows"][0]["identifier"], "Gaia DR3 123")

    def test_index_row_extracts_quantities_without_source_overwrite(self) -> None:
        row = build_index_row(object_record())

        self.assertEqual(row["bibcodes"], ["2026A&A...001A...1A", "2026MNRAS.002..2B"])
        self.assertEqual(row["sources"][0]["phase_space"]["ra"], "10.1")
        self.assertEqual(row["sources"][0]["phase_space"]["distance"], "8.2")
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
        self.assertEqual(row["dynamics"]["heliocentric_distance_kpc"]["median"], 8.0)
        self.assertEqual(row["dynamics"]["velocity_margin_kms"], 120.0)
        self.assertEqual(row["dynamics"]["radial_velocity_source"]["source"], "literature")
        self.assertEqual(row["dynamics"]["corrected_parallax_over_error"], 9.67)
        self.assertEqual(row["dynamics"]["warning_count"], 1)
        self.assertEqual(row["external"]["status"], "success")
        self.assertEqual(row["external"]["gaia_dr3"]["matched_by"], "source_id")
        self.assertEqual(row["external"]["simbad"]["matched_by"], "identifier")
        self.assertEqual(row["discovery_month"], "2026-01")
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
        self.assertIn('data-paper-metadata="assets/paper-metadata.json"', html)

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

    def test_static_html_inlines_png_hero_asset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = root / "catalog"
            assets = root / "assets"
            write_json(catalog / "03_hvs_candidates_index.json", {"summary": {"object_count": 1}, "objects": []})
            write_json(catalog / CANDIDATES_DIRNAME / "Gaia_DR3_123.json", object_record())
            assets.mkdir()
            css_path = assets / "stella.css"
            js_path = assets / "catalog-viewer.js"
            hero_path = assets / "stella-hvs-hero.png"
            css_path.write_text('.masthead { background-image: url("stella-hvs-hero.png"); }', encoding="utf-8")
            js_path.write_text('document.body.dataset.loaded = "yes";', encoding="utf-8")
            hero_path.write_bytes(b"\x89PNG\r\n\x1a\n")

            html = build_static_html(catalog, css_path, js_path, hero_path)

            self.assertIn("data:image/png;base64", html)
            self.assertNotIn("stella-hvs-hero.png", html)
            self.assertFalse(has_external_html_dependencies(html))

    def test_home_filters_use_bounded_inputs_not_sliders(self) -> None:
        js = (ROOT / "src" / "stella" / "html" / "assets" / "catalog-viewer.js").read_text(encoding="utf-8")

        self.assertIn("data-filter-bound", js)
        self.assertIn("filterValidationErrors", js)
        self.assertNotIn('type="range"', js)
        self.assertNotIn("data-range-filter", js)

    def test_home_filter_input_updates_table_without_rebuilding_home(self) -> None:
        js = (ROOT / "src" / "stella" / "html" / "assets" / "catalog-viewer.js").read_text(encoding="utf-8")
        update_body = js.split("function updateFilterBound", 1)[1].split("function route", 1)[0]

        self.assertIn("catalog-table-region", js)
        self.assertIn("scheduleCatalogTableUpdate", update_body)
        self.assertIn("updateFilterCardState", update_body)
        self.assertNotIn("renderHome()", update_body)

    def test_home_empty_table_cells_are_unboxed(self) -> None:
        css = (ROOT / "src" / "stella" / "html" / "assets" / "stella.css").read_text(encoding="utf-8")
        empty_inline_rule = css.split(".empty-inline {", 1)[1].split("}", 1)[0]

        self.assertIn("background: transparent", empty_inline_rule)
        self.assertIn("border: 0", empty_inline_rule)
        self.assertNotIn(".empty-inline,\n.empty-state", css)

    def test_home_sorting_is_limited_to_approved_columns(self) -> None:
        js = (ROOT / "src" / "stella" / "html" / "assets" / "catalog-viewer.js").read_text(encoding="utf-8")
        sortable_block = js.split("const SORTABLE_HOME_KEYS", 1)[1].split("]);", 1)[0]

        for key in ("discovery", "total_velocity", "p_unbound", "radial_velocity"):
            self.assertIn(f'"{key}"', sortable_block)
        for key in ("identifier", "reported_by", "teff", "log_g", "metallicity"):
            self.assertNotIn(f'"{key}"', sortable_block)
        self.assertIn("renderHomeHeader", js)
        self.assertIn("plain-header-label", js)

    def test_reported_by_source_mode_can_show_all_sources(self) -> None:
        js = (ROOT / "src" / "stella" / "html" / "assets" / "catalog-viewer.js").read_text(encoding="utf-8")

        self.assertIn('["all", "all"]', js)
        self.assertIn('modes.reportedBy === "all"', js)
        self.assertIn("sortedPaperEntries", js)

    def test_source_mode_change_avoids_full_home_rerender(self) -> None:
        js = (ROOT / "src" / "stella" / "html" / "assets" / "catalog-viewer.js").read_text(encoding="utf-8")
        mode_change_body = js.split('if (mode && Object.prototype.hasOwnProperty.call(state.homeConfig.modes, mode)) {', 1)[
            1
        ].split("const visibleColumn", 1)[0]

        self.assertIn("updateRangeFilters()", mode_change_body)
        self.assertIn("updateCatalogTable()", mode_change_body)
        self.assertNotIn("renderHome()", mode_change_body)

    def test_home_cells_use_compact_values_tooltips_and_source_labels(self) -> None:
        js = (ROOT / "src" / "stella" / "html" / "assets" / "catalog-viewer.js").read_text(encoding="utf-8")

        self.assertIn("renderDisplayQuantityMath", js)
        self.assertIn("formatIntervalNumber", js)
        self.assertIn('label !== "probability" && error != null', js)
        self.assertIn('title="${escapeHtml(title)}"', js)
        self.assertIn('new Set(["discovery", "reported_by", "radec", "pm", "parallax", "g_mag", "bp_rp"])', js)
        self.assertIn('text: "(" + valid.map((part) => part.text).join(", ") + ")"', js)

    def test_method_dag_uses_dark_readable_colors(self) -> None:
        css = (ROOT / "src" / "stella" / "html" / "assets" / "stella.css").read_text(encoding="utf-8")
        dag_scroll_rule = css.split(".dag-scroll {", 1)[1].split("}", 1)[0]
        dag_node_rect_rule = css.split(".dag-node rect {", 1)[1].split("}", 1)[0]

        self.assertIn("#050505", dag_scroll_rule)
        self.assertNotIn("#fbfdfb", dag_scroll_rule)
        self.assertIn("fill: #0a0a0a", dag_node_rect_rule)
        self.assertNotIn("fill: #fff", dag_node_rect_rule)

    def test_static_site_generates_multi_file_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = root / "catalog"
            assets = root / "assets"
            write_json(catalog / "03_hvs_candidates_index.json", {"summary": {"object_count": 1}, "objects": []})
            write_json(catalog / CANDIDATES_DIRNAME / "Gaia_DR3_123.json", object_record())
            assets.mkdir()
            css_path = assets / "stella.css"
            js_path = assets / "catalog-viewer.js"
            hero_path = assets / "stella-hvs-hero.png"
            css_path.write_text('.masthead { background-image: url("stella-hvs-hero.png"); }', encoding="utf-8")
            js_path.write_text('window.loaded = true;', encoding="utf-8")
            hero_path.write_bytes(b"\x89PNG\r\n\x1a\n")
            static_dir = root / "static"

            index_path = build_static_site(static_dir, catalog, css_path, js_path, hero_path)

            self.assertEqual(index_path, static_dir / "index.html")
            self.assertTrue((static_dir / "index.html").exists())
            self.assertTrue((static_dir / "stella.css").exists())
            self.assertTrue((static_dir / "catalog-viewer.js").exists())
            self.assertTrue((static_dir / "catalog-data.js").exists())
            self.assertTrue((static_dir / "stella-hvs-hero.png").exists())

            html = (static_dir / "index.html").read_text(encoding="utf-8")
            self.assertIn('<link rel="stylesheet" href="stella.css">', html)
            self.assertIn('<script src="catalog-data.js"></script>', html)
            self.assertIn('<script src="catalog-viewer.js"></script>', html)
            self.assertNotIn("<style>", html)
            self.assertNotIn("window.STELLA_CATALOG_SNAPSHOT", html)

            data_js = (static_dir / "catalog-data.js").read_text(encoding="utf-8")
            self.assertTrue(data_js.startswith("window.STELLA_CATALOG_SNAPSHOT = "))
            self.assertTrue(data_js.endswith(";"))
            snapshot = json.loads(data_js[len("window.STELLA_CATALOG_SNAPSHOT = "):-1])
            self.assertEqual(snapshot["schema_version"], "stella.hvs_catalog_site.snapshot.v2")

    def test_external_links_pass_through_url_scheme_allowlist(self) -> None:
        js = (ROOT / "src" / "stella" / "html" / "assets" / "catalog-viewer.js").read_text(encoding="utf-8")

        self.assertIn("function safeUrl", js)
        self.assertIn("escapeHtml(safeUrl(links.abs", js)
        self.assertIn("escapeHtml(safeUrl(links.pdf))", js)
        self.assertIn("escapeHtml(safeUrl(item.href))", js)

    def test_static_html_bundles_local_latex_math_renderer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = root / "catalog"
            record = object_record()
            record["sources"][0]["paper"]["title"] = "Velocity test $v_{\\rm GRF}>v_{\\rm esc}$"
            record["method_chain"][0]["steps"][1]["summary"] = "Uses $\\frac{1}{2}v^2$."
            write_json(catalog / "03_hvs_candidates_index.json", {"summary": {"object_count": 1}, "objects": []})
            write_json(catalog / CANDIDATES_DIRNAME / "Gaia_DR3_123.json", record)

            assets = ROOT / "src" / "stella" / "html" / "assets"
            html = build_static_html(
                catalog,
                assets / "stella.css",
                assets / "catalog-viewer.js",
                assets / "stella-hero.svg",
            )

            self.assertIn("function textWithMath", html)
            self.assertIn("function renderQuantityMath", html)
            self.assertIn("function latexForUnit", html)
            self.assertIn("quantity-math", html)
            self.assertIn("math-formula", html)
            self.assertIn("\\frac{1}{2}", html)
            self.assertFalse(has_external_html_dependencies(html))


class ServeCatalogSiteCliTest(unittest.TestCase):
    def test_defaults_bind_localhost_static_mode(self) -> None:
        serve = _load_script("serve_catalog_site")
        args = serve.build_parser().parse_args([])

        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.mode, "static")
        self.assertEqual(args.port, 8080)

    def test_host_can_be_overridden_for_explicit_exposure(self) -> None:
        serve = _load_script("serve_catalog_site")
        args = serve.build_parser().parse_args(["--host", "0.0.0.0", "--mode", "live"])

        self.assertEqual(args.host, "0.0.0.0")
        self.assertEqual(args.mode, "live")


class PreparePagesSiteCliTest(unittest.TestCase):
    def test_defaults_copy_static_site_to_site_directory(self) -> None:
        pages = _load_script("prepare_pages_site")
        args = pages.build_parser().parse_args([])

        self.assertEqual(args.source, ROOT / "catalog" / "html" / "static")
        self.assertEqual(args.site_dir, ROOT / "site")

    def test_prepare_pages_site_copies_bundle_and_cleans_stale_files(self) -> None:
        pages = _load_script("prepare_pages_site")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "static"
            site = root / "site"
            source.mkdir()
            (source / "index.html").write_text("<!doctype html>\n", encoding="utf-8")
            (source / "catalog-data.js").write_text("window.STELLA_CATALOG_SNAPSHOT = {};", encoding="utf-8")
            (source / ".DS_Store").write_text("local metadata", encoding="utf-8")
            site.mkdir()
            (site / "stale.txt").write_text("remove me", encoding="utf-8")

            result = pages.prepare_pages_site(source, site)

            self.assertEqual(result, site.resolve())
            self.assertTrue((site / "index.html").exists())
            self.assertTrue((site / "catalog-data.js").exists())
            self.assertTrue((site / ".nojekyll").exists())
            self.assertFalse((site / ".DS_Store").exists())
            self.assertFalse((site / "stale.txt").exists())


if __name__ == "__main__":
    unittest.main()
