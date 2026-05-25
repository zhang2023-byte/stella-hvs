from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from high_velocity_lit.hvs_catalog_enrichment import (  # noqa: E402
    EnrichmentError,
    QueryRows,
    enrich_object_records,
)


def quantity(value: str, *, unit: str = "") -> dict[str, object]:
    return {"value": value, "unit": unit, "method_refs": ["step-01"]}


def object_record(
    *,
    object_id: str = "Gaia_DR3_123",
    gaia_source_id: str = "Gaia DR3 123",
    ra: str = "10.0",
    dec: str = "20.0",
) -> dict[str, object]:
    return {
        "schema_version": "stella.hvs_candidate_catalog.object.v5",
        "generated_at": "2026-05-25T12:00:00",
        "object_id": object_id,
        "canonical_identifier": {"kind": "gaia_source_id", "value": gaia_source_id, "source": "src-001"},
        "sources": [
            {
                "source": "src-001",
                "paper": {"arxiv_id": "2601.00001", "month": "2026-01"},
                "source_json_path": "literature/2601.00001/literature_hvs_candidates.json",
                "record_id": "2601.00001:cand-001",
                "paper_candidate_id": "HVS-A",
                "gaia_source_id": gaia_source_id,
            }
        ],
        "method_chain": [],
        "candidates": [
            {
                "source": "src-001",
                "identifiers": {
                    "record_id": "2601.00001:cand-001",
                    "paper_candidate_id": "HVS-A",
                    "gaia_source_id": gaia_source_id,
                    "all": ["HVS-A", gaia_source_id],
                },
                "candidate_context": {},
                "core": {
                    "observed_phase_space": {
                        "ra": quantity(ra, unit="deg"),
                        "dec": quantity(dec, unit="deg"),
                        "parallax": quantity("0.30", unit="mas"),
                        "proper_motion_ra": quantity("1.20", unit="mas/yr"),
                        "proper_motion_dec": quantity("-0.20", unit="mas/yr"),
                        "radial_velocity": quantity("510", unit="km/s"),
                    },
                    "derived_kinematics": {},
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
            }
        ],
        "merge": {"match_strategy": "gaia_source_id", "warnings": []},
    }


class FakeClients:
    def __init__(
        self,
        *,
        simbad_identifier_rows: list[dict[str, object]] | None = None,
        simbad_region_rows: list[dict[str, object]] | None = None,
        gaia_id_rows: list[dict[str, object]] | None = None,
        gaia_region_rows: list[dict[str, object]] | None = None,
        fail_simbad: bool = False,
        fail_gaia: bool = False,
    ) -> None:
        self.simbad_identifier_rows = simbad_identifier_rows or []
        self.simbad_region_rows = simbad_region_rows or []
        self.gaia_id_rows = gaia_id_rows or []
        self.gaia_region_rows = gaia_region_rows or []
        self.fail_simbad = fail_simbad
        self.fail_gaia = fail_gaia
        self.simbad_identifier_queries: list[list[str]] = []
        self.gaia_source_id_queries: list[list[str]] = []

    def query_simbad_by_identifiers(self, identifiers: list[str]) -> QueryRows:
        self.simbad_identifier_queries.append(identifiers)
        if self.fail_simbad:
            raise RuntimeError("simbad down")
        return QueryRows(
            rows=self.simbad_identifier_rows,
            units={"ra": "deg", "dec": "deg", "rvz_radvel": "km/s", "V": "mag"},
        )

    def query_simbad_by_regions(self, coordinates: list[object]) -> QueryRows:
        if self.fail_simbad:
            raise RuntimeError("simbad down")
        return QueryRows(rows=self.simbad_region_rows, units={"ra": "deg", "dec": "deg"})

    def query_gaia_by_source_ids(self, source_ids: list[str]) -> QueryRows:
        self.gaia_source_id_queries.append(source_ids)
        if self.fail_gaia:
            raise RuntimeError("gaia down")
        return QueryRows(
            rows=self.gaia_id_rows,
            units={"ra": "deg", "dec": "deg", "parallax": "mas", "pmra": "mas/yr", "radial_velocity": "km/s"},
        )

    def query_gaia_by_regions(self, coordinates: list[object]) -> QueryRows:
        if self.fail_gaia:
            raise RuntimeError("gaia down")
        return QueryRows(
            rows=self.gaia_region_rows,
            units={"ra": "deg", "dec": "deg", "parallax": "mas", "radial_velocity": "km/s"},
        )


class HvsCatalogEnrichmentTest(unittest.TestCase):
    def test_successful_identifier_enrichment_adds_simbad_gaia_and_comparisons(self) -> None:
        clients = FakeClients(
            simbad_identifier_rows=[
                {
                    "oid": "1",
                    "main_id": "HVS-A",
                    "ids": "HVS-A|Gaia DR3 123|HD 1",
                    "ra": 10.0,
                    "dec": 20.0,
                    "otype": "*",
                    "otype_txt": "Star",
                    "sp_type": "B",
                    "rvz_radvel": 512.0,
                    "rvz_err": 2.0,
                    "V": 14.2,
                }
            ],
            gaia_id_rows=[
                {
                    "source_id": 123,
                    "designation": "Gaia DR3 123",
                    "ra": 10.0001,
                    "dec": 20.0001,
                    "parallax": 0.31,
                    "pmra": 1.25,
                    "pmdec": -0.25,
                    "radial_velocity": 509.0,
                    "phot_g_mean_mag": 15.1,
                    "teff_gspphot": 12000,
                    "ruwe": 1.1,
                }
            ],
        )

        enriched = enrich_object_records([object_record()], mode="auto", clients=clients, queried_at="2026-05-25T12:00:00")

        external = enriched[0]["external_enrichment"]
        self.assertEqual(external["status"], "success")
        self.assertEqual(external["providers"]["simbad"]["main_id"], "HVS-A")
        self.assertIn("HD 1", external["providers"]["simbad"]["aliases"])
        self.assertEqual(external["providers"]["gaia_dr3"]["source_id"], "123")
        self.assertEqual(external["providers"]["gaia_dr3"]["stellar_parameters"]["teff_gspphot"]["value"], 12000)
        self.assertTrue(external["verification"]["simbad_identifier_match"])
        self.assertTrue(external["verification"]["gaia_source_id_match"])
        comparison_fields = {item["field"] for item in external["verification"]["value_comparisons"]}
        self.assertIn("parallax", comparison_fields)
        self.assertIn("radial_velocity", comparison_fields)
        self.assertIn("Gaia DR3 123", clients.simbad_identifier_queries[0])
        self.assertEqual(clients.gaia_source_id_queries[0], ["123"])

    def test_no_external_match_records_not_found(self) -> None:
        enriched = enrich_object_records([object_record()], mode="auto", clients=FakeClients(), queried_at="2026-05-25T12:00:00")

        external = enriched[0]["external_enrichment"]
        self.assertEqual(external["status"], "not_found")
        self.assertEqual(external["providers"]["simbad"]["status"], "not_found")
        self.assertEqual(external["providers"]["gaia_dr3"]["status"], "not_found")

    def test_simbad_gaia_alias_is_used_for_gaia_dr3_lookup(self) -> None:
        clients = FakeClients(
            simbad_identifier_rows=[
                {
                    "oid": "1",
                    "main_id": "HVS-A",
                    "ids": "HVS-A|Gaia DR3 777",
                    "ra": 10.0,
                    "dec": 20.0,
                }
            ],
            gaia_id_rows=[{"source_id": 777, "designation": "Gaia DR3 777", "ra": 10.0, "dec": 20.0}],
        )

        enriched = enrich_object_records(
            [object_record(gaia_source_id="", object_id="HVS-A")],
            mode="auto",
            clients=clients,
            queried_at="2026-05-25T12:00:00",
        )

        self.assertEqual(clients.gaia_source_id_queries[0], ["777"])
        self.assertEqual(enriched[0]["external_enrichment"]["providers"]["gaia_dr3"]["source_id"], "777")

    def test_auto_mode_records_provider_failures_as_warnings(self) -> None:
        enriched = enrich_object_records(
            [object_record()],
            mode="auto",
            clients=FakeClients(fail_simbad=True, fail_gaia=True),
            queried_at="2026-05-25T12:00:00",
        )

        external = enriched[0]["external_enrichment"]
        self.assertEqual(external["status"], "failed")
        warning_types = {warning["type"] for warning in external["warnings"]}
        self.assertIn("simbad_identifier_query_failed", warning_types)
        self.assertIn("gaia_source_id_query_failed", warning_types)

    def test_required_mode_raises_on_provider_failure(self) -> None:
        with self.assertRaises(EnrichmentError):
            enrich_object_records(
                [object_record()],
                mode="required",
                clients=FakeClients(fail_simbad=True),
                queried_at="2026-05-25T12:00:00",
            )

    def test_coordinate_gaia_match_with_different_literature_gaia_id_warns(self) -> None:
        clients = FakeClients(
            gaia_region_rows=[
                {
                    "source_id": 123,
                    "designation": "Gaia DR3 123",
                    "ra": 10.0001,
                    "dec": 20.0001,
                    "parallax": 0.31,
                }
            ]
        )

        enriched = enrich_object_records(
            [object_record(gaia_source_id="Gaia DR3 999")],
            mode="auto",
            clients=clients,
            queried_at="2026-05-25T12:00:00",
        )

        external = enriched[0]["external_enrichment"]
        self.assertEqual(external["providers"]["gaia_dr3"]["matched_by"], "coordinates")
        warning_types = {warning["type"] for warning in external["warnings"]}
        self.assertIn("external_gaia_source_id_mismatch", warning_types)

    def test_source_id_match_with_far_official_coordinates_warns_without_changing_merge(self) -> None:
        clients = FakeClients(gaia_id_rows=[{"source_id": 123, "designation": "Gaia DR3 123", "ra": 40.0, "dec": 20.0}])

        enriched = enrich_object_records([object_record()], mode="auto", clients=clients, queried_at="2026-05-25T12:00:00")

        self.assertEqual(enriched[0]["merge"]["match_strategy"], "gaia_source_id")
        warning_types = {warning["type"] for warning in enriched[0]["external_enrichment"]["warnings"]}
        self.assertIn("gaia_dr3_far_from_literature_coordinates", warning_types)

    def test_off_mode_disables_enrichment(self) -> None:
        enriched = enrich_object_records([object_record()], mode="off", clients=FakeClients(), queried_at="2026-05-25T12:00:00")

        self.assertEqual(enriched[0]["external_enrichment"]["status"], "disabled")
        self.assertEqual(enriched[0]["external_enrichment"]["providers"], {})


if __name__ == "__main__":
    unittest.main()
