from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stella_benchmark.adjudication import (  # noqa: E402
    PAPER_STATUS_ITEM,
    atomic_save_adjudication,
    load_adjudication,
    missing_items,
    required_item_ids,
    upsert_verdict,
)
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


def make_alignment(*, spot_checks: list[str] | None = None) -> AlignmentRecord:
    return AlignmentRecord(
        schema_version="stella.hvs_benchmark.alignment.v1",
        arxiv_id="9999.00001",
        generated_at="2026-06-10T12:00:00",
        alignment_digest="sha256:abc",
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
                members={"a": "x:cand-001", "b": "x:cand-001"},
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
                        values={"a": "unbound", "b": "unbound"},
                        agreement=True,
                    ),
                ],
            )
        ],
        consensus_spot_checks=spot_checks or [],
    )


def make_adjudication(items: list[AdjudicationItem], *, with_status: bool = True) -> AdjudicationRecord:
    return AdjudicationRecord(
        schema_version="stella.hvs_benchmark.adjudication.v1",
        arxiv_id="9999.00001",
        alignment_digest="sha256:abc",
        expert=ExpertIdentity(id="wz", name="Will"),
        updated_at="2026-06-10T13:00:00",
        paper_status_verdict=(
            PaperStatusVerdict(verdict="accept", gold_status="candidates_found")
            if with_status
            else None
        ),
        items=items,
    )


def presence_item() -> AdjudicationItem:
    return AdjudicationItem(
        item_id="cluster-001",
        kind="candidate_presence",
        cluster_id="cluster-001",
        verdict="accept",
        base_variant="a",
    )


def rv_item() -> AdjudicationItem:
    return AdjudicationItem(
        item_id="cluster-001:core.observed_phase_space.radial_velocity",
        kind="field_value",
        cluster_id="cluster-001",
        field_path="core.observed_phase_space.radial_velocity",
        verdict="accept",
    )


class RequiredItemsTest(unittest.TestCase):
    def test_required_items_cover_presence_disagreements_and_spot_checks(self) -> None:
        alignment = make_alignment(
            spot_checks=["cluster-001:inclusion_assessment.galactic_bound_claim"]
        )
        self.assertEqual(
            required_item_ids(alignment),
            [
                "cluster-001",
                "cluster-001:core.observed_phase_space.radial_velocity",
                "cluster-001:inclusion_assessment.galactic_bound_claim",
            ],
        )

    def test_missing_items_gate(self) -> None:
        alignment = make_alignment()
        self.assertEqual(
            missing_items(alignment, None),
            [
                PAPER_STATUS_ITEM,
                "cluster-001",
                "cluster-001:core.observed_phase_space.radial_velocity",
            ],
        )
        partial = make_adjudication([presence_item()])
        self.assertEqual(
            missing_items(alignment, partial),
            ["cluster-001:core.observed_phase_space.radial_velocity"],
        )
        complete = make_adjudication([presence_item(), rv_item()])
        self.assertEqual(missing_items(alignment, complete), [])

    def test_missing_paper_status(self) -> None:
        alignment = make_alignment()
        record = make_adjudication([presence_item(), rv_item()], with_status=False)
        self.assertEqual(missing_items(alignment, record), [PAPER_STATUS_ITEM])


class PersistenceTest(unittest.TestCase):
    def test_round_trip_and_atomic_save(self) -> None:
        record = make_adjudication([presence_item(), rv_item()])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "adjudication" / "9999.00001.adjudication.json"
            atomic_save_adjudication(path, record)
            loaded = load_adjudication(path)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.model_dump(), record.model_dump())
            leftovers = [p for p in path.parent.iterdir() if p.name != path.name]
            self.assertEqual(leftovers, [])

    def test_load_missing_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(load_adjudication(Path(tmp) / "missing.json"))

    def test_upsert_replaces_by_item_id(self) -> None:
        record = make_adjudication([presence_item(), rv_item()])
        replacement = rv_item().model_copy(update={"verdict": "fix", "fixed_payload": {"value": "500"}})
        updated = upsert_verdict(record, replacement)
        self.assertEqual(len(updated.items), 2)
        by_id = {item.item_id: item for item in updated.items}
        self.assertEqual(
            by_id["cluster-001:core.observed_phase_space.radial_velocity"].verdict, "fix"
        )
        # original record is untouched
        self.assertEqual(
            {item.verdict for item in record.items}, {"accept"}
        )

    def test_duplicate_item_ids_rejected(self) -> None:
        with self.assertRaises(ValueError):
            make_adjudication([presence_item(), presence_item()])


if __name__ == "__main__":
    unittest.main()
