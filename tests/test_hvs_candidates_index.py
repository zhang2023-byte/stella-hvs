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


class HvsCandidatesIndexTest(unittest.TestCase):
    def test_index_records_origin_breakdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir = workspace / "literature"
            write_json(
                literature_dir / "2603.00001" / "literature_hvs_candidates.json",
                {
                    "paper": {
                        "arxiv_id": "2603.00001",
                        "title": "HVS candidates",
                        "month": "2026-03",
                    },
                    "extraction": {"status": "candidates_found"},
                    "candidates": [
                        {
                            "identifiers": {"primary": "HVS1"},
                            "candidate_assessment": {"candidate_status": "unbound_candidate"},
                            "candidate_origin": {"origin_type": "introduced_by_this_paper"},
                        },
                        {
                            "identifiers": {"primary": "HVS2"},
                            "candidate_assessment": {"candidate_status": "hvs_candidate"},
                            "candidate_origin": {"origin_type": "cited_from_literature"},
                        },
                    ],
                },
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


if __name__ == "__main__":
    unittest.main()
