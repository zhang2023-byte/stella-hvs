from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stella_benchmark.sampling import (  # noqa: E402
    allocate_per_stratum,
    assign_stratum,
    build_manifest,
    candidate_count_bucket,
    select_sample,
    year_bucket,
)


def index_item(arxiv_id: str, year: str, status: str, count: int) -> dict[str, object]:
    return {
        "arxiv_id": arxiv_id,
        "year": year,
        "month": f"{year}-01",
        "extraction_status": status,
        "candidate_count": count,
    }


def index_record(items: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": "stella.literature_hvs_index.v1",
        "generated_at": "2026-06-10T12:00:00",
        "papers": items,
    }


class BucketTest(unittest.TestCase):
    def test_year_bucket_edges(self) -> None:
        self.assertEqual(year_bucket("2018"), "2018-2020")
        self.assertEqual(year_bucket("2020"), "2018-2020")
        self.assertEqual(year_bucket("2021"), "2021-2023")
        self.assertEqual(year_bucket("2023"), "2021-2023")
        self.assertEqual(year_bucket("2024"), "2024-2026")
        self.assertEqual(year_bucket("2026"), "2024-2026")
        self.assertEqual(year_bucket(""), "unknown")
        self.assertEqual(year_bucket("n/a"), "unknown")

    def test_candidate_count_bucket_edges(self) -> None:
        self.assertEqual(candidate_count_bucket(0), "0")
        self.assertEqual(candidate_count_bucket(1), "1-3")
        self.assertEqual(candidate_count_bucket(3), "1-3")
        self.assertEqual(candidate_count_bucket(4), "4-20")
        self.assertEqual(candidate_count_bucket(20), "4-20")
        self.assertEqual(candidate_count_bucket(21), ">20")

    def test_assign_stratum(self) -> None:
        item = index_item("2402.10714", "2024", "candidates_found", 72)
        self.assertEqual(assign_stratum(item), "2024-2026|candidates_found|>20")


class AllocationTest(unittest.TestCase):
    def test_each_nonempty_stratum_gets_one(self) -> None:
        allocation = allocate_per_stratum({"a": 5, "b": 1, "c": 30}, 6)
        self.assertEqual(set(allocation), {"a", "b", "c"})
        self.assertGreaterEqual(min(allocation.values()), 1)
        self.assertEqual(sum(allocation.values()), 6)

    def test_allocation_caps_at_stratum_size(self) -> None:
        allocation = allocate_per_stratum({"a": 2, "b": 3}, 10)
        self.assertEqual(allocation, {"a": 2, "b": 3})

    def test_small_size_prefers_largest_strata(self) -> None:
        allocation = allocate_per_stratum({"a": 1, "b": 50, "c": 10}, 2)
        self.assertEqual(allocation, {"b": 1, "c": 1})

    def test_empty_strata_excluded(self) -> None:
        allocation = allocate_per_stratum({"a": 0, "b": 4}, 3)
        self.assertEqual(allocation, {"b": 3})


def make_items() -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for i in range(8):
        items.append(index_item(f"1804.{i:05d}", "2018", "candidates_found", 2))
    for i in range(8):
        items.append(index_item(f"2402.{i:05d}", "2024", "candidates_found", 30))
    for i in range(8):
        items.append(index_item(f"2501.{i:05d}", "2025", "no_candidates", 0))
    items.append(index_item("2301.00001", "2023", "partial", 5))
    return items


class SelectSampleTest(unittest.TestCase):
    def test_seed_determinism(self) -> None:
        record = index_record(make_items())
        first = select_sample(record, size=6, seed=42)
        second = select_sample(record, size=6, seed=42)
        self.assertEqual(
            [paper.arxiv_id for paper in first], [paper.arxiv_id for paper in second]
        )
        third = select_sample(record, size=6, seed=43)
        self.assertEqual(len(third), 6)

    def test_non_sampled_statuses_excluded(self) -> None:
        record = index_record(make_items())
        selected = select_sample(record, size=25, seed=1)
        self.assertNotIn("2301.00001", [paper.arxiv_id for paper in selected])
        self.assertEqual(len(selected), 24)

    def test_strata_coverage(self) -> None:
        record = index_record(make_items())
        selected = select_sample(record, size=6, seed=7)
        strata = {paper.stratum for paper in selected}
        self.assertEqual(
            strata,
            {
                "2018-2020|candidates_found|1-3",
                "2024-2026|candidates_found|>20",
                "2024-2026|no_candidates|0",
            },
        )

    def test_exclude_arxiv_ids(self) -> None:
        record = index_record(make_items())
        excluded = {f"1804.{i:05d}" for i in range(8)}
        selected = select_sample(record, size=10, seed=7, exclude_arxiv_ids=excluded)
        self.assertTrue(excluded.isdisjoint({paper.arxiv_id for paper in selected}))


class BuildManifestTest(unittest.TestCase):
    def test_manifest_round_trip(self) -> None:
        record = index_record(make_items())
        manifest = build_manifest(
            record, size=5, seed=11, source_index_path="literature", frozen=True
        )
        self.assertEqual(manifest.schema_version, "stella.hvs_benchmark.manifest.v1")
        self.assertTrue(manifest.frozen)
        self.assertEqual(manifest.selection.size, len(manifest.papers))
        self.assertEqual(manifest.seed, 11)
        arxiv_ids = [paper.arxiv_id for paper in manifest.papers]
        self.assertEqual(arxiv_ids, sorted(arxiv_ids))


if __name__ == "__main__":
    unittest.main()
