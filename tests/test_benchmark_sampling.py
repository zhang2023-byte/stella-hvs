from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stella.benchmark.sampling import (
    ALLOCATION,
    COMPLEXITY_HIGH,
    COMPLEXITY_LOW,
    PILOT_PAPERS,
    PROXY_NEGATIVE,
    PROXY_POSITIVE,
    ROLE_BLIND,
    ROLE_VERIFICATION,
    FramePaper,
    allocate_proportionally,
    build_manifest,
    build_manifest_entries,
    measure_tex_complexity,
    systematic_sample,
)
from stella.benchmark.versions import (
    parse_abs_latest_version,
    parse_pdf_watermark_version,
)
import random


def synthetic_frame() -> list[FramePaper]:
    """A frame large enough to satisfy the real allocation quotas."""

    papers: list[FramePaper] = []
    serial = 0
    def add(count: int, status: str, n_tables: int, max_rows: int) -> None:
        nonlocal serial
        for _ in range(count):
            year_month = 1800 + (serial % 90)
            papers.append(
                FramePaper(
                    arxiv_id=f"{year_month:04d}.{10000 + serial:05d}",
                    status=status,
                    n_tables=n_tables,
                    max_table_rows=max_rows,
                )
            )
            serial += 1

    add(25, "candidates_found", 1, 10)   # positive, low complexity
    add(24, "candidates_found", 6, 80)   # positive, high complexity
    add(70, "no_candidates", 0, 0)       # negative, low complexity
    add(86, "no_candidates", 5, 60)      # negative, high complexity
    add(2, "needs_review", 5, 90)        # unfinished -> proxy negative
    return papers


class StratificationTest(unittest.TestCase):
    def test_status_maps_to_primary_stratum(self) -> None:
        positive = FramePaper("2101.00001", "candidates_found", 0, 0)
        negative = FramePaper("2101.00002", "no_candidates", 0, 0)
        unfinished = FramePaper("2101.00003", "needs_review", 0, 0)
        self.assertEqual(positive.stratum, PROXY_POSITIVE)
        self.assertEqual(negative.stratum, PROXY_NEGATIVE)
        self.assertEqual(unfinished.stratum, PROXY_NEGATIVE)

    def test_complexity_bin_thresholds(self) -> None:
        self.assertEqual(FramePaper("a", "x", 3, 39).complexity_bin, COMPLEXITY_LOW)
        self.assertEqual(FramePaper("a", "x", 4, 0).complexity_bin, COMPLEXITY_HIGH)
        self.assertEqual(FramePaper("a", "x", 0, 40).complexity_bin, COMPLEXITY_HIGH)

    def test_chronological_key_orders_by_year_month(self) -> None:
        early = FramePaper("1801.09999", "x", 0, 0)
        late = FramePaper("2206.00001", "x", 0, 0)
        self.assertLess(early.chronological_key, late.chronological_key)


class AllocationTest(unittest.TestCase):
    def test_proportional_allocation_sums_to_total(self) -> None:
        allocation = allocate_proportionally({"low": 26, "high": 23}, 28)
        self.assertEqual(sum(allocation.values()), 28)
        self.assertGreater(allocation["low"], 0)
        self.assertGreater(allocation["high"], 0)

    def test_allocation_respects_bin_population(self) -> None:
        allocation = allocate_proportionally({"low": 2, "high": 100}, 50)
        self.assertLessEqual(allocation["low"], 2)
        self.assertEqual(sum(allocation.values()), 50)

    def test_allocation_rejects_oversized_total(self) -> None:
        with self.assertRaises(ValueError):
            allocate_proportionally({"low": 3, "high": 4}, 8)


class SystematicSampleTest(unittest.TestCase):
    def test_sample_is_deterministic_for_same_seed(self) -> None:
        frame = synthetic_frame()
        first = systematic_sample(frame, 10, random.Random("seed"))
        second = systematic_sample(frame, 10, random.Random("seed"))
        self.assertEqual(first, second)

    def test_sample_has_no_duplicates_and_spans_eras(self) -> None:
        frame = synthetic_frame()
        picks = systematic_sample(frame, 20, random.Random("seed"))
        ids = [paper.arxiv_id for paper in picks]
        self.assertEqual(len(ids), len(set(ids)))
        keys = [paper.chronological_key for paper in picks]
        self.assertEqual(keys, sorted(keys))

    def test_sample_rejects_overdraw(self) -> None:
        with self.assertRaises(ValueError):
            systematic_sample(synthetic_frame()[:3], 4, random.Random("seed"))


class ManifestTest(unittest.TestCase):
    def setUp(self) -> None:
        self.frame = synthetic_frame()
        self.manifest = build_manifest(self.frame, seed=20260611)

    def test_manifest_is_deterministic(self) -> None:
        again = build_manifest(synthetic_frame(), seed=20260611)
        self.assertEqual(self.manifest, again)

    def test_different_seed_changes_sample(self) -> None:
        other = build_manifest(synthetic_frame(), seed=1)
        ours = {entry["arxiv_id"] for entry in self.manifest["papers"]}
        theirs = {entry["arxiv_id"] for entry in other["papers"]}
        self.assertNotEqual(ours, theirs)

    def test_role_counts_match_allocation(self) -> None:
        for stratum in (PROXY_POSITIVE, PROXY_NEGATIVE):
            entries = [
                entry
                for entry in self.manifest["papers"]
                if entry["stratum"] == stratum
            ]
            blind = [e for e in entries if e["role"] == ROLE_BLIND]
            verification = [
                e for e in entries if e["role"] == ROLE_VERIFICATION
            ]
            overlap = [e for e in entries if e["overlap"]]
            quota = ALLOCATION[stratum]
            self.assertEqual(len(blind), quota["blind"])
            self.assertEqual(len(verification), quota["verification"])
            self.assertEqual(len(overlap), quota["overlap"])

    def test_overlap_papers_are_blind(self) -> None:
        for entry in self.manifest["papers"]:
            if entry["overlap"]:
                self.assertEqual(entry["role"], ROLE_BLIND)

    def test_sampled_papers_are_unique_and_from_frame(self) -> None:
        ids = [entry["arxiv_id"] for entry in self.manifest["papers"]]
        self.assertEqual(len(ids), len(set(ids)))
        frame_ids = {paper.arxiv_id for paper in self.frame}
        self.assertTrue(set(ids) <= frame_ids)

    def test_weights_are_cell_population_over_sampled(self) -> None:
        cells = self.manifest["frame"]["cells"]
        for entry in self.manifest["papers"]:
            cell = cells[f"{entry['stratum']}/{entry['complexity_bin']}"]
            expected = cell["population"] / cell["sampled"]
            self.assertAlmostEqual(entry["sampling_weight"], expected, places=5)

    def test_weighted_sample_recovers_stratum_populations(self) -> None:
        totals: dict[str, float] = {}
        for entry in self.manifest["papers"]:
            totals[entry["stratum"]] = (
                totals.get(entry["stratum"], 0.0) + entry["sampling_weight"]
            )
        for stratum, population in self.manifest["frame"]["strata"].items():
            self.assertAlmostEqual(totals[stratum], population, places=3)

    def test_pilot_papers_are_rejected_from_frame(self) -> None:
        pilot_id = sorted(PILOT_PAPERS)[0]
        polluted = synthetic_frame() + [
            FramePaper(pilot_id, "candidates_found", 0, 0)
        ]
        with self.assertRaises(ValueError):
            build_manifest_entries(polluted)


class TexComplexityTest(unittest.TestCase):
    def test_counts_tables_and_rows_including_deluxetable(self) -> None:
        tex = (
            "\\begin{table}\n\\begin{tabular}{cc}\na & b \\\\\nc & d \\\\\n"
            "\\end{tabular}\n\\end{table}\n"
            "\\begin{deluxetable*}{ccc}\nx & y & z \\\\\nq & r & s \\\\\n"
            "t & u & v \\\\\n\\end{deluxetable*}\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "arxiv_source"
            source_dir.mkdir()
            (source_dir / "paper.tex").write_text(tex, encoding="utf-8")
            n_tables, max_rows = measure_tex_complexity(source_dir)
        self.assertEqual(n_tables, 2)
        self.assertEqual(max_rows, 3)

    def test_missing_source_dir_counts_as_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            n_tables, max_rows = measure_tex_complexity(Path(tmp) / "absent")
        self.assertEqual((n_tables, max_rows), (0, 0))


class VersionParsingTest(unittest.TestCase):
    def test_parse_pdf_watermark(self) -> None:
        text = "arXiv:2101.10878v2  [astro-ph.GA]  26 Jan 2021"
        self.assertEqual(parse_pdf_watermark_version(text, "2101.10878"), 2)
        self.assertIsNone(parse_pdf_watermark_version(text, "2101.99999"))

    def test_parse_abs_latest_version_takes_max(self) -> None:
        html = (
            '<a href="/abs/2101.10878v1">[v1]</a>'
            '<a href="/abs/2101.10878v2">[v2]</a>'
        )
        self.assertEqual(parse_abs_latest_version(html, "2101.10878"), 2)
        self.assertIsNone(parse_abs_latest_version("<html></html>", "2101.10878"))


if __name__ == "__main__":
    unittest.main()
