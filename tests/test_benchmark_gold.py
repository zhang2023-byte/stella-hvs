from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stella_benchmark.gold import GoldAssemblyError, assemble_gold  # noqa: E402
from stella_benchmark.models import (  # noqa: E402
    AdjudicationItem,
    AdjudicationRecord,
    AlignmentCluster,
    AlignmentField,
    AlignmentPaperInfo,
    AlignmentPaperStatus,
    AlignmentRecord,
    AlignmentVariantSummary,
    ExpertIdentity,
    IdentifierSummary,
    PaperStatusVerdict,
)

DIGEST = "sha256:abc"


def candidate(record_id: str, *, rv: str, claim: str = "unbound") -> dict[str, Any]:
    return {
        "identifiers": {
            "record_id": record_id,
            "paper_candidate_id": "S1",
            "gaia_source_id": "Gaia DR3 1",
            "all": [{"value": "S1", "source_refs": []}],
        },
        "inclusion_assessment": {
            "summary": "",
            "paper_labels": ["hvs_candidate"],
            "galactic_bound_claim": claim,
            "inclusion_basis": "explicit_candidate_text",
            "extraction_confidence": "high",
            "confidence_reason": "",
            "source_refs": [],
        },
        "candidate_origin": {
            "origin_type": "introduced_by_this_paper",
            "paper_reassesses_unbound_status": False,
            "source_refs": [],
            "citation": None,
        },
        "core": {
            "observed_phase_space": {
                "radial_velocity": {
                    "raw_value": rv,
                    "value": rv,
                    "unit": "km s^-1",
                    "source_refs": [],
                    "method_refs": ["step-01"],
                }
            },
            "derived_kinematics": {},
            "bound_assessment": {},
        },
    }


def payloads() -> dict[str, dict[str, Any]]:
    return {
        "a": {
            "schema_version": "stella.literature_hvs_candidates.v7",
            "paper": {"arxiv_id": "9999.00001", "title": "Test"},
            "inputs": {"paper_dir": "literature/9999.00001"},
            "extraction": {"status": "candidates_found"},
            "method_chain": [{"id": "step-01"}],
            "candidates": [candidate("9999.00001:cand-001", rv="499")],
            "candidate_groups_considered": [],
        },
        "b": {
            "schema_version": "stella.literature_hvs_candidates.v7",
            "paper": {"arxiv_id": "9999.00001", "title": "Test"},
            "inputs": {"paper_dir": "literature/9999.00001"},
            "extraction": {"status": "candidates_found"},
            "method_chain": [{"id": "step-01"}],
            "candidates": [candidate("9999.00001:cand-001", rv="510", claim="likely_unbound")],
            "candidate_groups_considered": [],
        },
    }


def alignment() -> AlignmentRecord:
    return AlignmentRecord(
        schema_version="stella.hvs_benchmark.alignment.v1",
        arxiv_id="9999.00001",
        generated_at="2026-06-10T12:00:00",
        alignment_digest=DIGEST,
        paper=AlignmentPaperInfo(title="Test", month="2026-01"),
        variants=[
            AlignmentVariantSummary(variant_id="a", status="candidates_found", candidate_count=1),
            AlignmentVariantSummary(variant_id="b", status="candidates_found", candidate_count=1),
        ],
        paper_status=AlignmentPaperStatus(
            values={"a": "candidates_found", "b": "candidates_found"}, agreement=True
        ),
        clusters=[
            AlignmentCluster(
                cluster_id="cluster-001",
                matched_by="gaia_source_id",
                members={"a": "9999.00001:cand-001", "b": "9999.00001:cand-001"},
                identifier_summary=IdentifierSummary(display="S1"),
                fields=[
                    AlignmentField(
                        field_path="core.observed_phase_space.radial_velocity",
                        kind="quantity",
                        values={"a": {"value": "499"}, "b": {"value": "510"}},
                        agreement=False,
                    ),
                    AlignmentField(
                        field_path="inclusion_assessment.galactic_bound_claim",
                        kind="categorical",
                        values={"a": "unbound", "b": "likely_unbound"},
                        agreement=False,
                    ),
                ],
            )
        ],
    )


def adjudication(
    items: list[AdjudicationItem],
    *,
    gold_status: str = "candidates_found",
    digest: str = DIGEST,
) -> AdjudicationRecord:
    return AdjudicationRecord(
        schema_version="stella.hvs_benchmark.adjudication.v1",
        arxiv_id="9999.00001",
        alignment_digest=digest,
        expert=ExpertIdentity(id="wz"),
        updated_at="2026-06-10T13:00:00",
        paper_status_verdict=PaperStatusVerdict(verdict="accept", gold_status=gold_status),
        items=items,
    )


def presence(verdict: str = "accept", base: str = "a") -> AdjudicationItem:
    return AdjudicationItem(
        item_id="cluster-001",
        kind="candidate_presence",
        cluster_id="cluster-001",
        verdict=verdict,
        base_variant=base,
    )


def field_item(field_path: str, verdict: str, **kwargs: Any) -> AdjudicationItem:
    return AdjudicationItem(
        item_id=f"cluster-001:{field_path}",
        kind="field_value",
        cluster_id="cluster-001",
        field_path=field_path,
        verdict=verdict,
        **kwargs,
    )


RV = "core.observed_phase_space.radial_velocity"
CLAIM = "inclusion_assessment.galactic_bound_claim"


class AssembleGoldTest(unittest.TestCase):
    def test_accept_all_uses_base_variant_and_renumbers(self) -> None:
        record = adjudication([presence(), field_item(RV, "accept"), field_item(CLAIM, "accept")])
        gold, provenance = assemble_gold(
            alignment(), record, payloads(), adjudication_path="benchmark/adjudication/x.json"
        )
        self.assertEqual(len(gold["candidates"]), 1)
        gold_candidate = gold["candidates"][0]
        self.assertEqual(gold_candidate["core"]["observed_phase_space"]["radial_velocity"]["value"], "499")
        self.assertEqual(gold_candidate["identifiers"]["record_id"], "9999.00001:cand-001")
        self.assertEqual(gold["extraction"]["status"], "candidates_found")
        self.assertIn("expert: wz", gold["extraction"]["extractor"])
        targets = {entry.target: entry for entry in provenance.entries}
        self.assertEqual(targets[f"cluster-001:{RV}"].source, "verdict")

    def test_auto_consensus_provenance_for_unadjudicated_fields(self) -> None:
        record = adjudication([presence(), field_item(RV, "accept"), field_item(CLAIM, "accept")])
        align = alignment()
        align.clusters[0].fields[1] = align.clusters[0].fields[1].model_copy(
            update={"agreement": True}
        )
        record = adjudication([presence(), field_item(RV, "accept")])
        _, provenance = assemble_gold(
            align, record, payloads(), adjudication_path="benchmark/adjudication/x.json"
        )
        targets = {entry.target: entry for entry in provenance.entries}
        claim_entry = targets[f"cluster-001:{CLAIM}"]
        self.assertEqual(claim_entry.source, "auto_consensus")
        self.assertEqual(claim_entry.base_variant, "a")

    def test_accept_variant_copies_subtree(self) -> None:
        record = adjudication(
            [
                presence(),
                field_item(RV, "accept_variant", accepted_from_variant="b"),
                field_item(CLAIM, "accept"),
            ]
        )
        gold, _ = assemble_gold(
            alignment(), record, payloads(), adjudication_path="benchmark/adjudication/x.json"
        )
        self.assertEqual(
            gold["candidates"][0]["core"]["observed_phase_space"]["radial_velocity"]["value"], "510"
        )

    def test_fix_sets_payload(self) -> None:
        fixed = {"raw_value": "505", "value": "505", "unit": "km s^-1", "source_refs": [], "method_refs": ["step-01"]}
        record = adjudication(
            [presence(), field_item(RV, "fix", fixed_payload=fixed), field_item(CLAIM, "accept")]
        )
        gold, _ = assemble_gold(
            alignment(), record, payloads(), adjudication_path="benchmark/adjudication/x.json"
        )
        self.assertEqual(
            gold["candidates"][0]["core"]["observed_phase_space"]["radial_velocity"]["value"], "505"
        )

    def test_reject_field_empties_optional_quantity(self) -> None:
        record = adjudication(
            [presence(), field_item(RV, "reject_field"), field_item(CLAIM, "accept")]
        )
        gold, _ = assemble_gold(
            alignment(), record, payloads(), adjudication_path="benchmark/adjudication/x.json"
        )
        self.assertIsNone(gold["candidates"][0]["core"]["observed_phase_space"]["radial_velocity"])

    def test_reject_field_on_required_categorical_fails(self) -> None:
        record = adjudication(
            [presence(), field_item(RV, "accept"), field_item(CLAIM, "reject_field")]
        )
        with self.assertRaises(GoldAssemblyError):
            assemble_gold(
                alignment(), record, payloads(), adjudication_path="benchmark/adjudication/x.json"
            )

    def test_reject_presence_drops_candidate(self) -> None:
        record = adjudication([presence(verdict="reject")], gold_status="no_candidates")
        gold, _ = assemble_gold(
            alignment(), record, payloads(), adjudication_path="benchmark/adjudication/x.json"
        )
        self.assertEqual(gold["candidates"], [])
        self.assertEqual(gold["extraction"]["status"], "no_candidates")

    def test_status_candidate_consistency_enforced(self) -> None:
        record = adjudication([presence(verdict="reject")], gold_status="candidates_found")
        with self.assertRaises(GoldAssemblyError):
            assemble_gold(
                alignment(), record, payloads(), adjudication_path="benchmark/adjudication/x.json"
            )

    def test_add_missing_appends_candidate(self) -> None:
        added = candidate("ignored", rv="700")
        record = adjudication(
            [
                presence(),
                field_item(RV, "accept"),
                field_item(CLAIM, "accept"),
                AdjudicationItem(
                    item_id="missing-001",
                    kind="candidate_addition",
                    verdict="add_missing",
                    added_payload=added,
                    rationale="row 9 of table 1",
                ),
            ]
        )
        gold, provenance = assemble_gold(
            alignment(), record, payloads(), adjudication_path="benchmark/adjudication/x.json"
        )
        self.assertEqual(len(gold["candidates"]), 2)
        self.assertEqual(gold["candidates"][1]["identifiers"]["record_id"], "9999.00001:cand-002")
        targets = {entry.target for entry in provenance.entries}
        self.assertIn("missing-001", targets)

    def test_digest_mismatch_rejected(self) -> None:
        record = adjudication([presence()], digest="sha256:other")
        with self.assertRaises(GoldAssemblyError):
            assemble_gold(
                alignment(), record, payloads(), adjudication_path="benchmark/adjudication/x.json"
            )

    def test_missing_presence_verdict_rejected(self) -> None:
        record = adjudication([field_item(RV, "accept")])
        with self.assertRaises(GoldAssemblyError):
            assemble_gold(
                alignment(), record, payloads(), adjudication_path="benchmark/adjudication/x.json"
            )


if __name__ == "__main__":
    unittest.main()
