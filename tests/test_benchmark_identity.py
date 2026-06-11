from __future__ import annotations

import unittest

from stella.benchmark.identity import (
    CandidateIdentity,
    angular_separation_arcsec,
    identity_from_candidate,
    match_candidate_sets,
    match_identities,
    normalize_name,
    parse_epoch_year,
    parse_gaia_id,
    propagate_position,
)


def candidate(
    *,
    record_id: str,
    gaia: str = "",
    names: list[str] | None = None,
    ra: dict | None = None,
    dec: dict | None = None,
) -> dict:
    return {
        "identifiers": {
            "record_id": record_id,
            "paper_candidate_id": (names or [record_id])[0],
            "gaia_source_id": gaia,
            "all": [{"value": name, "source_refs": []} for name in (names or [])],
        },
        "core": {"observed_phase_space": {k: v for k, v in (("ra", ra), ("dec", dec)) if v is not None}},
    }


def deg(value: str) -> dict:
    return {"value": value, "unit": "deg", "coordinate_format": "decimal_degrees"}


class ParseHelpersTest(unittest.TestCase):
    def test_parse_gaia_id_strict_forms(self) -> None:
        self.assertEqual(parse_gaia_id("Gaia DR3 123456789"), ("DR3", "123456789"))
        self.assertEqual(parse_gaia_id("Gaia EDR3 42"), ("EDR3", "42"))
        self.assertIsNone(parse_gaia_id("DR3 123456789"))
        self.assertIsNone(parse_gaia_id("Gaia DR3 12a"))

    def test_normalize_name_collapses_separators(self) -> None:
        self.assertEqual(normalize_name("HVS 1"), "HVS1")
        self.assertEqual(normalize_name("hvs-1"), "HVS1")
        self.assertEqual(normalize_name("HVS_1"), "HVS1")

    def test_angular_separation_near_pole(self) -> None:
        self.assertAlmostEqual(angular_separation_arcsec(10.0, 89.9, 190.0, 89.9), 720.0, delta=1.0)


class IdentityExtractionTest(unittest.TestCase):
    def test_extracts_gaia_names_and_decimal_coordinates(self) -> None:
        identity = identity_from_candidate(
            candidate(
                record_id="x:cand-001",
                gaia="Gaia DR3 99",
                names=["HVS 1", "Gaia DR3 99"],
                ra=deg("150.5"),
                dec=deg("-3.25"),
            )
        )
        self.assertEqual(identity.gaia, ("DR3", "99"))
        self.assertEqual(identity.names, {"HVS1"})
        self.assertAlmostEqual(identity.ra_deg, 150.5)
        self.assertAlmostEqual(identity.dec_deg, -3.25)

    def test_sexagesimal_coordinates_convert(self) -> None:
        identity = identity_from_candidate(
            candidate(
                record_id="x:cand-002",
                ra={"value": "10:00:00", "unit": "hourangle", "coordinate_format": "sexagesimal_colon"},
                dec={"value": "-30:30:00", "unit": "deg", "coordinate_format": "sexagesimal_colon"},
            )
        )
        self.assertAlmostEqual(identity.ra_deg, 150.0)
        self.assertAlmostEqual(identity.dec_deg, -30.5)

    def test_unknown_coordinates_are_none(self) -> None:
        identity = identity_from_candidate(
            candidate(record_id="x:cand-003", ra={"value": "unknown", "unit": "deg", "coordinate_format": "decimal_degrees"})
        )
        self.assertIsNone(identity.ra_deg)


class MatchIdentitiesTest(unittest.TestCase):
    def test_gaia_id_match_wins(self) -> None:
        left = CandidateIdentity(gaia=("DR3", "99"), names={"A"})
        right = CandidateIdentity(gaia=("DR3", "99"), names={"B"})
        result = match_identities(left, right)
        self.assertTrue(result.matched)
        self.assertEqual(result.method, "gaia_id")

    def test_same_release_gaia_conflict_vetoes_alias_match(self) -> None:
        left = CandidateIdentity(gaia=("DR3", "99"), names={"HVS1"})
        right = CandidateIdentity(gaia=("DR3", "100"), names={"HVS1"})
        result = match_identities(left, right)
        self.assertFalse(result.matched)
        self.assertEqual(result.method, "gaia_conflict")

    def test_different_release_falls_through_to_alias(self) -> None:
        left = CandidateIdentity(gaia=("DR2", "99"), names={"HVS1"})
        right = CandidateIdentity(gaia=("DR3", "100"), names={"HVS1"})
        result = match_identities(left, right)
        self.assertTrue(result.matched)
        self.assertEqual(result.method, "alias")

    def test_coordinate_match_respects_tolerance_boundary(self) -> None:
        left = CandidateIdentity(ra_deg=150.0, dec_deg=0.0)
        inside = CandidateIdentity(ra_deg=150.0 + 0.9 / 3600.0, dec_deg=0.0)
        outside = CandidateIdentity(ra_deg=150.0 + 1.1 / 3600.0, dec_deg=0.0)
        self.assertTrue(match_identities(left, inside, fallback_tolerance_arcsec=1.0).matched)
        self.assertFalse(match_identities(left, outside, fallback_tolerance_arcsec=1.0).matched)

    def test_fallback_default_is_five_arcsec(self) -> None:
        left = CandidateIdentity(ra_deg=150.0, dec_deg=0.0)
        inside = CandidateIdentity(ra_deg=150.0 + 4.5 / 3600.0, dec_deg=0.0)
        outside = CandidateIdentity(ra_deg=150.0 + 5.5 / 3600.0, dec_deg=0.0)
        self.assertTrue(match_identities(left, inside).matched)
        self.assertFalse(match_identities(left, outside).matched)

    def test_propagation_recovers_high_proper_motion_match(self) -> None:
        # Star at epoch J2000 with mu_alpha* = 500 mas/yr drifts ~8 arcsec by
        # J2016: the raw separation fails the 5-arcsec fallback, but epoch
        # propagation brings both sides to J2016 and matches at 2 arcsec.
        drift_deg = 500.0 * 16.0 / 3.6e6
        old_epoch = CandidateIdentity(
            ra_deg=150.0, dec_deg=0.0, pm_ra_masyr=500.0, pm_dec_masyr=0.0, epoch_year=2000.0
        )
        gaia_epoch = CandidateIdentity(
            ra_deg=150.0 + drift_deg, dec_deg=0.0, pm_ra_masyr=500.0, pm_dec_masyr=0.0, epoch_year=2016.0
        )
        result = match_identities(old_epoch, gaia_epoch)
        self.assertTrue(result.matched)
        self.assertEqual(result.method, "coordinates")
        self.assertIn("propagated@J2016", result.detail)
        self.assertLess(result.separation_arcsec, 0.1)

        # Without proper motion / epoch on one side, the same pair stays
        # unmatched (8 arcsec > 5 arcsec fallback) and goes to manual review.
        no_pm = CandidateIdentity(ra_deg=150.0, dec_deg=0.0)
        result = match_identities(no_pm, gaia_epoch)
        self.assertFalse(result.matched)
        self.assertEqual(result.method, "coordinates_too_far")
        self.assertIn("unpropagated", result.detail)

    def test_propagate_position_applies_cos_dec_to_ra(self) -> None:
        ra, dec = propagate_position(10.0, 60.0, 360.0, 0.0, from_year=2000.0, to_year=2010.0)
        self.assertAlmostEqual(dec, 60.0)
        self.assertAlmostEqual(ra, 10.0 + (360.0 * 10.0 / 3.6e6) / 0.5, places=9)

    def test_no_evidence_does_not_match(self) -> None:
        result = match_identities(CandidateIdentity(names={"A"}), CandidateIdentity(names={"B"}))
        self.assertFalse(result.matched)
        self.assertEqual(result.method, "no_evidence")


class EpochParsingTest(unittest.TestCase):
    def test_reference_epoch_values_parse(self) -> None:
        self.assertEqual(parse_epoch_year({"epoch_kind": "reference_epoch", "value": "J2016.0"}), 2016.0)
        self.assertEqual(parse_epoch_year({"epoch_kind": "reference_epoch", "value": "2015.5"}), 2015.5)

    def test_equinox_and_unknown_epochs_are_unusable(self) -> None:
        self.assertIsNone(parse_epoch_year({"epoch_kind": "equinox", "value": "J2000.0"}))
        self.assertIsNone(parse_epoch_year({"epoch_kind": "not_reported", "value": "unknown"}))
        self.assertIsNone(parse_epoch_year({"epoch_kind": "reference_epoch", "value": "unknown"}))

    def test_identity_extraction_picks_up_pm_and_epoch(self) -> None:
        record = candidate(
            record_id="x:cand-001",
            ra={"value": "150.0", "unit": "deg", "coordinate_format": "decimal_degrees",
                "epoch": {"epoch_kind": "reference_epoch", "value": "J2016.0"}},
            dec={"value": "0.0", "unit": "deg", "coordinate_format": "decimal_degrees"},
        )
        record["core"]["observed_phase_space"]["proper_motion_ra"] = {"value": "500", "unit": "mas/yr"}
        record["core"]["observed_phase_space"]["proper_motion_dec"] = {"value": "-20", "unit": "mas yr^-1"}
        identity = identity_from_candidate(record)
        self.assertEqual(identity.epoch_year, 2016.0)
        self.assertEqual(identity.pm_ra_masyr, 500.0)
        self.assertEqual(identity.pm_dec_masyr, -20.0)
        self.assertTrue(identity.propagatable())

    def test_unexpected_pm_units_are_refused(self) -> None:
        record = candidate(record_id="x:cand-002", ra=deg("150.0"), dec=deg("0.0"))
        record["core"]["observed_phase_space"]["proper_motion_ra"] = {"value": "0.5", "unit": "arcsec/yr"}
        identity = identity_from_candidate(record)
        self.assertIsNone(identity.pm_ra_masyr)


class MatchCandidateSetsTest(unittest.TestCase):
    def test_one_to_one_greedy_matching_across_tiers(self) -> None:
        left = [
            candidate(record_id="g:cand-001", gaia="Gaia DR3 1", names=["S1"]),
            candidate(record_id="g:cand-002", names=["HVS 7"]),
            candidate(record_id="g:cand-003", ra=deg("10.0"), dec=deg("10.0")),
            candidate(record_id="g:cand-004", names=["LONER"]),
        ]
        right = [
            candidate(record_id="p:cand-001", names=["HVS-7"]),
            candidate(record_id="p:cand-002", gaia="Gaia DR3 1", names=["other"]),
            candidate(record_id="p:cand-003", ra=deg("10.0"), dec=deg("10.0001")),
        ]

        report = match_candidate_sets(left, right, fallback_tolerance_arcsec=1.0)

        methods = {(pair["left_record_id"], pair["right_record_id"]): pair["method"] for pair in report["pairs"]}
        self.assertEqual(methods[("g:cand-001", "p:cand-002")], "gaia_id")
        self.assertEqual(methods[("g:cand-002", "p:cand-001")], "alias")
        self.assertEqual(methods[("g:cand-003", "p:cand-003")], "coordinates")
        self.assertEqual(report["unmatched_left"], ["g:cand-004"])
        self.assertEqual(report["unmatched_right"], [])

    def test_closest_coordinate_pair_wins(self) -> None:
        left = [candidate(record_id="g:cand-001", ra=deg("10.0"), dec=deg("0.0"))]
        right = [
            candidate(record_id="p:far", ra=deg("10.00020"), dec=deg("0.0")),
            candidate(record_id="p:near", ra=deg("10.00005"), dec=deg("0.0")),
        ]

        report = match_candidate_sets(left, right, fallback_tolerance_arcsec=1.0)

        self.assertEqual(len(report["pairs"]), 1)
        self.assertEqual(report["pairs"][0]["right_record_id"], "p:near")
        self.assertEqual(report["unmatched_right"], ["p:far"])


if __name__ == "__main__":
    unittest.main()
