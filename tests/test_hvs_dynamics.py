from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]

from stella.dyn.dynamics import (  # noqa: E402
    DEFAULT_MCMC_SAMPLES,
    KinematicArrays,
    QueryRows,
    calculate_catalog_dynamics,
    compute_dynamics_for_object,
    select_literature_radial_velocity,
    select_radial_velocity,
)


def quantity(value: str, *, error: str = "", unit: str = "km/s") -> dict[str, object]:
    payload: dict[str, object] = {"value": value, "unit": unit, "method_refs": ["step-01"]}
    if error:
        payload["error"] = error
    return payload


def object_record(
    *,
    gaia_source_id: str = "Gaia DR3 123",
    radial_velocities: list[dict[str, object] | None] | None = None,
    include_gaia_cache: bool = True,
) -> dict[str, object]:
    if radial_velocities is None:
        radial_velocities = [quantity("510", error="4")]
    candidates: list[dict[str, object]] = []
    sources: list[dict[str, object]] = []
    for index, rv in enumerate(radial_velocities, start=1):
        source_id = f"src-{index:03d}"
        sources.append(
            {
                "source": source_id,
                "paper": {"arxiv_id": f"2601.0000{index}", "month": f"2026-0{index}"},
                "source_json_path": f"literature/2601.0000{index}/literature_hvs_candidates.json",
                "record_id": f"2601.0000{index}:cand-001",
                "paper_candidate_id": f"HVS-{index}",
                "gaia_source_id": gaia_source_id,
            }
        )
        observed: dict[str, object] = {}
        if rv is not None:
            observed["radial_velocity"] = rv
        candidates.append(
            {
                "source": source_id,
                "identifiers": {
                    "record_id": f"2601.0000{index}:cand-001",
                    "paper_candidate_id": f"HVS-{index}",
                    "gaia_source_id": gaia_source_id,
                    "all": [f"HVS-{index}", gaia_source_id],
                },
                "candidate_context": {},
                "core": {"observed_phase_space": observed, "derived_kinematics": {}, "bound_assessment": {}},
                "photometry": [],
                "spectroscopy": [],
                "stellar_parameters": {"other": []},
                "abundances": [],
                "quality_flags": [],
                "orbit": {"other": []},
                "astrophysical_origin": {"hypothesis_metrics": [], "other": []},
                "extra": [],
            }
        )
    return {
        "schema_version": "stella.hvs_candidate_catalog.object.v0.1",
        "generated_at": "2026-05-25T12:00:00",
        "object_id": "Gaia_DR3_123" if gaia_source_id else "HVS_1",
        "canonical_identifier": {"kind": "gaia_source_id", "value": gaia_source_id, "source": "src-001"},
        "sources": sources,
        "method_chain": [],
        "candidates": candidates,
        "external_enrichment": {
            "status": "success" if gaia_source_id and include_gaia_cache else "not_found",
            "providers": {
                "gaia_dr3": {
                    "status": "matched",
                    "source_id": "123",
                    "raw_columns": gaia_row(),
                }
            }
            if gaia_source_id and include_gaia_cache
            else {},
        },
        "merge": {"match_strategy": "singleton", "warnings": []},
    }


def gaia_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "source_id": 123,
        "designation": "Gaia DR3 123",
        "ra": 10.0,
        "dec": 20.0,
        "parallax": 1.0,
        "parallax_error": 0.1,
        "pmra": 1.2,
        "pmra_error": 0.05,
        "pmdec": -0.2,
        "pmdec_error": 0.06,
        "parallax_pmra_corr": 0.1,
        "parallax_pmdec_corr": -0.1,
        "pmra_pmdec_corr": 0.0,
        "phot_g_mean_mag": 15.0,
        "nu_eff_used_in_astrometry": 1.5,
        "pseudocolour": "",
        "ecl_lat": 30.0,
        "astrometric_params_solved": 31,
    }
    row.update(overrides)
    return row


class FakeZeroPoint:
    def __init__(self, value: float = 0.01) -> None:
        self.value = value

    def load_tables(self) -> None:
        pass

    def get_zpt(self, *_args: object) -> np.ndarray:
        return np.array([self.value])


class FakeClients:
    def __init__(
        self,
        *,
        gaia_rows: list[dict[str, object]] | None = None,
        simbad_rows: list[dict[str, object]] | None = None,
    ) -> None:
        self.gaia_rows = gaia_rows if gaia_rows is not None else [gaia_row()]
        self.simbad_rows = simbad_rows or []
        self.gaia_query_count = 0
        self.simbad_query_count = 0

    def query_gaia_by_source_ids(self, source_ids: list[str]) -> QueryRows:
        self.gaia_query_count += 1
        return QueryRows(rows=self.gaia_rows, units={})

    def query_simbad_by_identifiers(self, identifiers: list[str]) -> QueryRows:
        self.simbad_query_count += 1
        return QueryRows(rows=self.simbad_rows, units={"rvz_radvel": "km/s"})


def fake_sample_provider(captured: dict[str, object] | None = None):
    def provider(astrometry, rv, samples: int, seed: int | None):
        if captured is not None:
            captured["samples"] = samples
            captured["rv_source"] = rv.source
            captured["rv_lower_limit"] = rv.lower_limit
        rv_value = 0.0 if rv.value is None else float(rv.value)
        return {
            "parallax": np.full(samples, astrometry.corrected_parallax_mas),
            "pmra": np.full(samples, astrometry.pmra_masyr),
            "pmdec": np.full(samples, astrometry.pmdec_masyr),
            "radial_velocity": np.full(samples, rv_value),
        }

    return provider


def fake_kinematics_provider(unbound_count: int):
    def provider(astrometry, rv, posterior):
        samples = len(posterior["parallax"])
        total = np.full(samples, 400.0)
        escape = np.full(samples, 500.0)
        if unbound_count:
            total[:unbound_count] = 600.0
        return KinematicArrays(
            total_velocity_kms=total,
            escape_velocity_kms=escape,
            galactocentric_radius_kpc=np.full(samples, 8.0),
            heliocentric_distance_kpc=1.0 / posterior["parallax"],
            radial_velocity_kms=posterior["radial_velocity"],
        )

    return provider


class HvsDynamicsTest(unittest.TestCase):
    def test_missing_gaia_source_skips(self) -> None:
        result = compute_dynamics_for_object(
            object_record(gaia_source_id="", radial_velocities=[quantity("1")]),
            clients=FakeClients(),
            zero_point_module=FakeZeroPoint(),
            sample_provider=fake_sample_provider(),
            kinematics_provider=fake_kinematics_provider(0),
            generated_at="2026-05-26T12:00:00",
        )
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["status_reason"], "gaia astrometry not available")

    def test_zero_point_missing_required_columns_skips(self) -> None:
        record = object_record()
        row = record["external_enrichment"]["providers"]["gaia_dr3"]["raw_columns"]  # type: ignore[index]
        row.pop("phot_g_mean_mag")
        result = compute_dynamics_for_object(
            record,
            clients=FakeClients(),
            zero_point_module=FakeZeroPoint(),
            sample_provider=fake_sample_provider(),
            kinematics_provider=fake_kinematics_provider(0),
            generated_at="2026-05-26T12:00:00",
        )
        self.assertEqual(result["status_reason"], "zero point correction not available")

    def test_parallax_quality_gate_skips(self) -> None:
        record = object_record()
        row = record["external_enrichment"]["providers"]["gaia_dr3"]["raw_columns"]  # type: ignore[index]
        row["parallax"] = 0.2
        row["parallax_error"] = 0.1
        result = compute_dynamics_for_object(
            record,
            clients=FakeClients(),
            zero_point_module=FakeZeroPoint(0.0),
            sample_provider=fake_sample_provider(),
            kinematics_provider=fake_kinematics_provider(0),
            generated_at="2026-05-26T12:00:00",
        )
        self.assertEqual(result["status_reason"], "parallax uncertainty too large")
        self.assertAlmostEqual(result["astrometry"]["corrected_parallax_over_error"], 2.0)

    def test_default_uses_external_cache_without_network_queries(self) -> None:
        clients = FakeClients()
        result = compute_dynamics_for_object(
            object_record(),
            clients=clients,
            zero_point_module=FakeZeroPoint(),
            sample_provider=fake_sample_provider(),
            kinematics_provider=fake_kinematics_provider(0),
            generated_at="2026-05-26T12:00:00",
        )
        self.assertEqual(result["status"], "computed")
        self.assertEqual(result["astrometry"]["provider"], "external_enrichment.providers.gaia_dr3.raw_columns")
        self.assertEqual(clients.gaia_query_count, 0)
        self.assertEqual(clients.simbad_query_count, 0)

    def test_default_can_use_matched_cached_gaia_source_without_identifier(self) -> None:
        clients = FakeClients()
        record = object_record(gaia_source_id="", radial_velocities=[quantity("510", error="4")])
        record["external_enrichment"] = {
            "status": "success",
            "providers": {
                "gaia_dr3": {
                    "status": "matched",
                    "source_id": "123",
                    "raw_columns": gaia_row(),
                }
            },
        }
        result = compute_dynamics_for_object(
            record,
            clients=clients,
            zero_point_module=FakeZeroPoint(),
            sample_provider=fake_sample_provider(),
            kinematics_provider=fake_kinematics_provider(0),
            generated_at="2026-05-26T12:00:00",
        )
        self.assertEqual(result["status"], "computed")
        self.assertEqual(result["gaia_source_id"], "Gaia DR3 123")
        self.assertIn("gaia_source_id_from_external_cache", {item["type"] for item in result["warnings"]})
        self.assertEqual(clients.gaia_query_count, 0)

    def test_missing_external_cache_skips_without_network(self) -> None:
        clients = FakeClients()
        result = compute_dynamics_for_object(
            object_record(include_gaia_cache=False),
            clients=clients,
            zero_point_module=FakeZeroPoint(),
            sample_provider=fake_sample_provider(),
            kinematics_provider=fake_kinematics_provider(0),
            generated_at="2026-05-26T12:00:00",
        )
        self.assertEqual(result["status_reason"], "gaia astrometry not available")
        self.assertEqual(clients.gaia_query_count, 0)

    def test_refresh_mode_queries_gaia_only_and_ignores_simbad_rv(self) -> None:
        clients = FakeClients(simbad_rows=[{"main_id": "HVS-A", "rvz_radvel": 512.0, "rvz_err": 3.0}])
        result = compute_dynamics_for_object(
            object_record(radial_velocities=[None], include_gaia_cache=False),
            clients=clients,
            zero_point_module=FakeZeroPoint(),
            sample_provider=fake_sample_provider(),
            kinematics_provider=fake_kinematics_provider(0),
            external_cache_mode="refresh",
            generated_at="2026-05-26T12:00:00",
        )
        self.assertEqual(result["status"], "computed")
        self.assertEqual(result["radial_velocity_source"]["source"], "minimum_grf_velocity")
        self.assertTrue(result["radial_velocity_source"]["lower_limit"])
        self.assertEqual(clients.gaia_query_count, 1)
        self.assertEqual(clients.simbad_query_count, 0)

    def test_literature_rv_uses_smallest_error(self) -> None:
        selected = select_literature_radial_velocity(
            object_record(radial_velocities=[quantity("510", error="20"), quantity("500", error="2")])
        )
        self.assertIsNotNone(selected)
        self.assertEqual(selected.value, 500.0)
        self.assertEqual(selected.error, 2.0)

    def test_rv_without_error_is_fixed_and_warned(self) -> None:
        result = compute_dynamics_for_object(
            object_record(radial_velocities=[quantity("510")]),
            clients=FakeClients(),
            zero_point_module=FakeZeroPoint(),
            sample_provider=fake_sample_provider(),
            kinematics_provider=fake_kinematics_provider(0),
            generated_at="2026-05-26T12:00:00",
        )
        warning_types = {item["type"] for item in result["warnings"]}
        self.assertIn("radial_velocity_uncertainty_missing", warning_types)
        self.assertIn("radial_velocity_held_fixed", warning_types)

    def test_missing_literature_rv_ignores_simbad_and_uses_lower_limit(self) -> None:
        clients = FakeClients(simbad_rows=[{"main_id": "HVS-A", "rvz_radvel": 512.0, "rvz_err": 3.0}])
        record = object_record(radial_velocities=[None])
        record["external_enrichment"]["providers"]["simbad"] = {  # type: ignore[index]
            "status": "matched",
            "radial_velocity": {"value": 512.0, "error": 3.0},
        }
        lower_limit, lower_warnings = select_radial_velocity(
            record,
            clients,
        )
        self.assertEqual(lower_limit.source, "minimum_grf_velocity")
        self.assertTrue(lower_limit.lower_limit)
        self.assertEqual(clients.simbad_query_count, 0)
        self.assertIn("minimum_grf_velocity_assumption", {item["type"] for item in lower_warnings})

    def test_default_samples_drive_probability_and_graveyard(self) -> None:
        captured: dict[str, object] = {}
        result = compute_dynamics_for_object(
            object_record(),
            clients=FakeClients(),
            zero_point_module=FakeZeroPoint(),
            sample_provider=fake_sample_provider(captured),
            kinematics_provider=fake_kinematics_provider(0),
            generated_at="2026-05-26T12:00:00",
        )
        self.assertEqual(captured["samples"], DEFAULT_MCMC_SAMPLES)
        self.assertEqual(result["sampling"]["sample_count"], DEFAULT_MCMC_SAMPLES)
        self.assertEqual(result["mc_counts"]["unbound_count"], 0)
        self.assertTrue(result["graveyard"])

    def test_beta_parameters_use_boubert_definition(self) -> None:
        result = compute_dynamics_for_object(
            object_record(),
            clients=FakeClients(),
            zero_point_module=FakeZeroPoint(),
            sample_provider=fake_sample_provider(),
            kinematics_provider=fake_kinematics_provider(7),
            samples=10,
            generated_at="2026-05-26T12:00:00",
        )
        self.assertFalse(result["graveyard"])
        self.assertEqual(result["mc_counts"]["unbound_count"], 7)
        self.assertEqual(result["mc_counts"]["bound_count"], 3)
        self.assertEqual(result["p_bound_beta"]["alpha"], 3.5)
        self.assertEqual(result["p_bound_beta"]["beta"], 7.5)
        self.assertEqual(result["p_unbound_beta"]["alpha"], 7.5)
        self.assertEqual(result["p_unbound_beta"]["beta"], 3.5)

    def test_catalog_dry_run_and_write_preserve_object_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            catalog_dir = Path(tmpdir) / "catalog"
            candidates_dir = catalog_dir / "candidates"
            candidates_dir.mkdir(parents=True)
            path = candidates_dir / "Gaia_DR3_123.json"
            original = object_record()
            path.write_text(json.dumps(original, indent=2), encoding="utf-8")

            dry = calculate_catalog_dynamics(
                catalog_dir,
                clients=FakeClients(),
                zero_point_module=FakeZeroPoint(),
                sample_provider=fake_sample_provider(),
                kinematics_provider=fake_kinematics_provider(0),
                samples=10,
                write=True,
                dry_run=True,
                generated_at="2026-05-26T12:00:00",
            )
            self.assertEqual(dry["written_paths"], [])
            self.assertNotIn("dynamics", json.loads(path.read_text(encoding="utf-8")))

            written = calculate_catalog_dynamics(
                catalog_dir,
                clients=FakeClients(),
                zero_point_module=FakeZeroPoint(),
                sample_provider=fake_sample_provider(),
                kinematics_provider=fake_kinematics_provider(2),
                samples=10,
                write=True,
                generated_at="2026-05-26T12:00:00",
            )
            updated = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(written["written_paths"]), 1)
            self.assertEqual(updated["object_id"], original["object_id"])
            self.assertEqual(updated["dynamics"]["status"], "computed")
            self.assertEqual(updated["dynamics"]["mc_counts"]["unbound_count"], 2)


if __name__ == "__main__":
    unittest.main()
