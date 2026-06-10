from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stella_benchmark.alignment import (  # noqa: E402
    align_candidates,
    build_alignment_record,
    compute_alignment_digest,
    normalize_identifier,
    sample_spot_checks,
)
from stella_benchmark.evidence import EvidenceResolver  # noqa: E402

ECSV_TEXT = """# %ECSV 1.0
# ---
# datatype:
# - {name: name, datatype: string}
# - {name: vrad, datatype: float64}
# schema: astropy-2.0
name vrad
LP40-365 499
HVS9999 800
"""

TEX_TEXT = "line one\nthe radial velocity of 499 km/s\nline three\n"


def candidate(
    record_id: str,
    *,
    gaia: str = "",
    names: list[str] | None = None,
    claim: str = "unbound",
    rv: str | None = None,
    ecsv_ref: bool = False,
) -> dict[str, object]:
    refs: list[dict[str, object]] = [
        {
            "kind": "text",
            "path": "literature/9999.00001/arxiv_source/main.tex",
            "start_line": 2,
            "end_line": 2,
            "context": "radial velocity",
        }
    ]
    if ecsv_ref:
        refs = [
            {
                "kind": "ecsv_cell",
                "path": "literature/9999.00001/catalog_tables/table-1.ecsv",
                "line": 8,
                "column": "vrad",
                "column_header": "v_rad",
                "raw_value": "499",
            }
        ]
    result: dict[str, object] = {
        "identifiers": {
            "record_id": record_id,
            "paper_candidate_id": (names or ["unnamed"])[0],
            "gaia_source_id": gaia,
            "all": [{"value": name, "source_refs": []} for name in (names or [])],
        },
        "inclusion_assessment": {
            "summary": "",
            "paper_labels": ["hvs_candidate"],
            "galactic_bound_claim": claim,
            "inclusion_basis": "explicit_candidate_text",
            "extraction_confidence": "high",
            "confidence_reason": "",
            "source_refs": refs,
        },
        "candidate_origin": {
            "origin_type": "introduced_by_this_paper",
            "paper_reassesses_unbound_status": False,
            "source_refs": [],
            "citation": None,
        },
        "core": {
            "observed_phase_space": {},
            "derived_kinematics": {},
            "bound_assessment": {},
        },
    }
    if rv is not None:
        result["core"]["observed_phase_space"]["radial_velocity"] = {
            "raw_value": rv,
            "value": rv,
            "unit": "km s^-1",
            "source_refs": refs,
            "method_refs": ["step-01"],
        }
    return result


def payload(arxiv_id: str, candidates: list[dict[str, object]], status: str | None = None) -> dict[str, object]:
    return {
        "schema_version": "stella.literature_hvs_candidates.v7",
        "generated_at": "2026-06-10T12:00:00",
        "paper": {"arxiv_id": arxiv_id, "title": "Test paper", "month": "2026-01", "links": {}},
        "extraction": {"status": status or ("candidates_found" if candidates else "no_candidates")},
        "candidates": candidates,
    }


class WorkspaceMixin(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        paper_dir = self.workspace / "literature" / "9999.00001"
        (paper_dir / "arxiv_source").mkdir(parents=True)
        (paper_dir / "catalog_tables").mkdir(parents=True)
        (paper_dir / "arxiv_source" / "main.tex").write_text(TEX_TEXT, encoding="utf-8")
        (paper_dir / "catalog_tables" / "table-1.ecsv").write_text(ECSV_TEXT, encoding="utf-8")
        self.resolver = EvidenceResolver(self.workspace)


class NormalizeIdentifierTest(unittest.TestCase):
    def test_normalization(self) -> None:
        self.assertEqual(normalize_identifier("  Gaia DR3   123 "), "gaia dr3 123")
        self.assertEqual(normalize_identifier("*HVS 1"), "hvs 1")
        self.assertEqual(normalize_identifier("[XYZ2020] 17"), "xyz2020] 17")


class AlignTest(WorkspaceMixin):
    def test_gaia_tier_match(self) -> None:
        payloads = {
            "a": payload("9999.00001", [candidate("9999.00001:cand-001", gaia="Gaia DR3 1", names=["S1"])]),
            "b": payload("9999.00001", [candidate("9999.00001:cand-001", gaia="Gaia DR3 1", names=["other"])]),
        }
        clusters = align_candidates(payloads)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].matched_by, "gaia_source_id")
        self.assertEqual(set(clusters[0].members), {"a", "b"})

    def test_identifier_overlap_transitive_match(self) -> None:
        payloads = {
            "a": payload("9999.00001", [candidate("x:cand-001", names=["LP 40-365", "GD 492"])]),
            "b": payload("9999.00001", [candidate("x:cand-001", names=["gd 492", "NLTT 56122"])]),
            "c": payload("9999.00001", [candidate("x:cand-001", names=["NLTT  56122"])]),
        }
        clusters = align_candidates(payloads)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].matched_by, "identifier_overlap")
        self.assertEqual(set(clusters[0].members), {"a", "b", "c"})

    def test_unmatched_candidates_split(self) -> None:
        payloads = {
            "a": payload("9999.00001", [candidate("x:cand-001", names=["S1"])]),
            "b": payload("9999.00001", [candidate("x:cand-001", names=["S2"])]),
        }
        clusters = align_candidates(payloads)
        self.assertEqual(len(clusters), 2)
        self.assertTrue(all(cluster.matched_by == "unmatched" for cluster in clusters))
        self.assertEqual({cluster.missing_in[0] for cluster in clusters}, {"a", "b"})

    def test_same_variant_collision_flags_conflict(self) -> None:
        payloads = {
            "a": payload(
                "9999.00001",
                [
                    candidate("x:cand-001", names=["S1", "alias"]),
                    candidate("x:cand-002", names=["alias", "S2"]),
                ],
            ),
        }
        clusters = align_candidates(payloads)
        self.assertEqual(len(clusters), 1)
        self.assertTrue(clusters[0].conflict)


class BuildRecordTest(WorkspaceMixin):
    def make_payloads(self) -> dict[str, dict[str, object]]:
        return {
            "a": payload(
                "9999.00001",
                [candidate("x:cand-001", gaia="Gaia DR3 1", names=["S1"], rv="499", ecsv_ref=True)],
            ),
            "b": payload(
                "9999.00001",
                [candidate("x:cand-001", gaia="Gaia DR3 1", names=["S1"], rv="510", claim="likely_unbound")],
            ),
        }

    def test_field_diff_and_evidence(self) -> None:
        record = build_alignment_record("9999.00001", self.make_payloads(), self.resolver, seed=1)
        self.assertEqual(len(record.clusters), 1)
        fields = {field.field_path: field for field in record.clusters[0].fields}

        rv = fields["core.observed_phase_space.radial_velocity"]
        self.assertFalse(rv.agreement)
        self.assertEqual(rv.values["a"]["value"], "499")
        self.assertEqual(rv.values["b"]["value"], "510")
        ecsv_evidence = rv.evidence["a"][0]
        self.assertEqual(ecsv_evidence.kind, "ecsv_cell")
        self.assertEqual(ecsv_evidence.row_cells["vrad"], "499")
        text_evidence = rv.evidence["b"][0]
        self.assertEqual(text_evidence.kind, "text")
        self.assertIn("499", text_evidence.lines[0])

        claim = fields["inclusion_assessment.galactic_bound_claim"]
        self.assertFalse(claim.agreement)
        self.assertTrue(fields["identifiers.gaia_source_id"].agreement)

        self.assertTrue(record.paper_status.agreement)
        self.assertTrue(record.alignment_digest.startswith("sha256:"))

    def test_digest_stability_and_sensitivity(self) -> None:
        payloads = self.make_payloads()
        digest_one = compute_alignment_digest(payloads)
        digest_two = compute_alignment_digest(self.make_payloads())
        self.assertEqual(digest_one, digest_two)
        changed = self.make_payloads()
        changed["b"]["candidates"][0]["core"]["observed_phase_space"]["radial_velocity"]["value"] = "511"
        self.assertNotEqual(digest_one, compute_alignment_digest(changed))

    def test_uncovered_rows_reported(self) -> None:
        record = build_alignment_record("9999.00001", self.make_payloads(), self.resolver, seed=1)
        rows = record.recall_assists.uncovered_ecsv_rows
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].line, 9)
        self.assertEqual(rows[0].identifier_guess, "HVS9999")

    def test_spot_checks_deterministic(self) -> None:
        record = build_alignment_record(
            "9999.00001", self.make_payloads(), self.resolver, spot_check_fraction=0.5, seed=3
        )
        again = build_alignment_record(
            "9999.00001", self.make_payloads(), self.resolver, spot_check_fraction=0.5, seed=3
        )
        self.assertEqual(record.consensus_spot_checks, again.consensus_spot_checks)
        self.assertTrue(record.consensus_spot_checks)
        for item in record.consensus_spot_checks:
            self.assertIn(":", item)

    def test_spot_checks_skip_single_member_clusters(self) -> None:
        payloads = {"a": payload("9999.00001", [candidate("x:cand-001", names=["S1"])])}
        clusters = align_candidates(payloads)
        resolver = self.resolver
        from stella_benchmark.alignment import diff_cluster_fields

        record_candidate = payloads["a"]["candidates"][0]
        clusters[0].fields = diff_cluster_fields({"a": record_candidate}, resolver)
        self.assertEqual(sample_spot_checks(clusters, fraction=1.0, seed=1), [])


if __name__ == "__main__":
    unittest.main()
