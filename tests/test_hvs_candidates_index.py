from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from high_velocity_lit.hvs_candidates_index import rebuild_hvs_candidates_index, render_hvs_candidates_index  # noqa: E402


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def candidate_payload() -> dict[str, object]:
    return {
        "schema_version": "stella.literature_hvs_candidates.v2",
        "generated_at": "2026-05-12T12:00:00",
        "paper": {
            "arxiv_id": "2603.00001",
            "bibcode": "2026MNRAS.123..456H",
            "title": "HVS candidates",
            "month": "2026-03",
            "source_note_json": "notes/2026/2026-03/2026-03.json",
            "links": {"abs": "https://arxiv.org/abs/2603.00001", "pdf": "https://arxiv.org/pdf/2603.00001"},
        },
        "inputs": {
            "paper_dir": "literature/2603.00001",
            "audit_path": "literature/2603.00001/audit.json",
            "catalog_review_path": "literature/2603.00001/catalog_review.json",
            "catalog_extraction_path": "literature/2603.00001/catalog_extraction.json",
            "ecsv_paths": [],
        },
        "extraction": {
            "status": "candidates_found",
            "extracted_at": "2026-05-12T12:00:00",
            "extractor": "agent",
            "summary": "Fixture extraction.",
        },
        "method_chain": [],
        "candidates": [
            {
                "candidate_id": "2603.00001:candidate-001",
                "identifiers": {"primary": "HVS1", "aliases": []},
                "candidate_assessment": {
                    "summary": "Fixture candidate.",
                    "candidate_status": "unbound_candidate",
                    "confidence": "high",
                    "source_refs": [],
                },
                "candidate_origin": {
                    "origin_type": "introduced_by_this_paper",
                    "paper_reassesses_unbound_status": True,
                    "source_refs": [],
                },
                "method_chain_refs": [],
                "core": {"observed_phase_space": {}, "derived_kinematics": {}, "probabilities": {}},
                "extra": [],
            },
            {
                "candidate_id": "2603.00001:candidate-002",
                "identifiers": {"primary": "HVS2", "aliases": []},
                "candidate_assessment": {
                    "summary": "Fixture candidate.",
                    "candidate_status": "hvs_candidate",
                    "confidence": "high",
                    "source_refs": [],
                },
                "candidate_origin": {
                    "origin_type": "cited_from_literature",
                    "paper_reassesses_unbound_status": True,
                    "source_refs": [],
                },
                "method_chain_refs": [],
                "core": {"observed_phase_space": {}, "derived_kinematics": {}, "probabilities": {}},
                "extra": [],
            },
        ],
        "candidate_groups_considered": [],
    }


class HvsCandidatesIndexTest(unittest.TestCase):
    def test_index_records_origin_breakdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir = workspace / "literature"
            write_json(
                literature_dir / "2603.00001" / "literature_hvs_candidates.json",
                candidate_payload(),
            )

            index = rebuild_hvs_candidates_index(literature_dir, workspace=workspace)

            self.assertEqual(
                index["summary"]["total_by_origin"],
                {"introduced_by_this_paper": 1, "cited_from_literature": 1},
            )
            paper = index["papers"][0]
            self.assertEqual(
                paper["candidate_origins"],
                {"introduced_by_this_paper": 1, "cited_from_literature": 1},
            )

            markdown = render_hvs_candidates_index(index)
            self.assertIn("Origin breakdown", markdown)
            self.assertIn("introduced_by_this_paper: 1", markdown)
            self.assertIn("cited_from_literature: 1", markdown)

    def test_index_skips_schema_invalid_candidate_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir = workspace / "literature"
            write_json(
                literature_dir / "2603.00001" / "literature_hvs_candidates.json",
                {"paper": {"arxiv_id": "2603.00001"}, "candidates": []},
            )

            index = rebuild_hvs_candidates_index(literature_dir, workspace=workspace)

            self.assertEqual(index["summary"]["paper_count"], 0)
            self.assertEqual(index["summary"]["skipped_count"], 1)
            self.assertIn("literature/2603.00001/literature_hvs_candidates.json", index["skipped"][0]["path"])


if __name__ == "__main__":
    unittest.main()
