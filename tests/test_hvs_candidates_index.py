from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
SCRIPT = ROOT / "scripts" / "build_hvs_candidates_index.py"
SPEC = importlib.util.spec_from_file_location("build_hvs_candidates_index", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
build_index_cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_index_cli)

from high_velocity_lit.hvs_candidates_index import rebuild_hvs_candidates_index, render_hvs_candidates_index  # noqa: E402
from high_velocity_lit.schema_specs import LITERATURE_HVS_CANDIDATES_SCHEMA_VERSION  # noqa: E402


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def candidate_payload() -> dict[str, object]:
    return {
        "schema_version": LITERATURE_HVS_CANDIDATES_SCHEMA_VERSION,
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
                "identifiers": {
                    "record_id": "2603.00001:cand-001",
                    "paper_candidate_id": "HVS1",
                    "gaia_source_id": "Gaia DR3 123456789",
                    "all": [{"value": "HVS1", "source_refs": []}, {"value": "Gaia DR3 123456789", "source_refs": []}],
                },
                "inclusion_assessment": {
                    "summary": "Fixture candidate.",
                    "paper_labels": ["unbound_star"],
                    "galactic_bound_claim": "unbound",
                    "inclusion_basis": "explicit_unbound_text",
                    "extraction_confidence": "high",
                    "confidence_reason": "Fixture candidate evidence.",
                    "source_refs": [],
                },
                "candidate_origin": {
                    "origin_type": "introduced_by_this_paper",
                    "paper_reassesses_unbound_status": True,
                    "source_refs": [],
                },
                "core": {"observed_phase_space": {}, "derived_kinematics": {}, "bound_assessment": {}},
                "photometry": [],
                "spectroscopy": [],
                "stellar_parameters": {"other": []},
                "abundances": [],
                "quality_flags": [],
                "orbit": {"other": []},
                "astrophysical_origin": {"hypothesis_metrics": [], "other": []},
                "extra": [],
            },
            {
                "identifiers": {
                    "record_id": "2603.00001:cand-002",
                    "paper_candidate_id": "HVS2",
                    "gaia_source_id": "",
                    "all": [{"value": "HVS2", "source_refs": []}],
                },
                "inclusion_assessment": {
                    "summary": "Fixture candidate.",
                    "paper_labels": ["hvs_candidate"],
                    "galactic_bound_claim": "possibly_unbound",
                    "inclusion_basis": "cited_prior_candidate_reassessed",
                    "extraction_confidence": "high",
                    "confidence_reason": "Fixture candidate evidence.",
                    "source_refs": [],
                },
                "candidate_origin": {
                    "origin_type": "cited_from_literature",
                    "paper_reassesses_unbound_status": True,
                    "source_refs": [],
                },
                "core": {"observed_phase_space": {}, "derived_kinematics": {}, "bound_assessment": {}},
                "photometry": [],
                "spectroscopy": [],
                "stellar_parameters": {"other": []},
                "abundances": [],
                "quality_flags": [],
                "orbit": {"other": []},
                "astrophysical_origin": {"hypothesis_metrics": [], "other": []},
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
            self.assertEqual(paper["paper_labels"], {"unbound_star": 1, "hvs_candidate": 1})
            self.assertEqual(paper["galactic_bound_claims"], {"unbound": 1, "possibly_unbound": 1})
            self.assertEqual(
                paper["inclusion_bases"],
                {"explicit_unbound_text": 1, "cited_prior_candidate_reassessed": 1},
            )
            self.assertEqual(paper["sample_paper_candidate_ids"], ["HVS1", "HVS2"])
            self.assertEqual(paper["sample_gaia_source_ids"], ["Gaia DR3 123456789"])

            markdown = render_hvs_candidates_index(index)
            self.assertIn("Paper labels", markdown)
            self.assertIn("Bound claims", markdown)
            self.assertIn("Origin breakdown", markdown)
            self.assertIn("Sample paper candidate IDs", markdown)
            self.assertIn("Sample Gaia source IDs", markdown)
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

    def test_cli_fail_on_skipped_exits_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            literature_dir = workspace / "literature"
            write_json(
                literature_dir / "2603.00001" / "literature_hvs_candidates.json",
                {"paper": {"arxiv_id": "2603.00001"}, "candidates": []},
            )

            with patch.object(
                sys,
                "argv",
                [
                    "build_hvs_candidates_index.py",
                    "--literature-dir",
                    str(literature_dir),
                    "--fail-on-skipped",
                ],
            ):
                with patch("sys.stderr", new_callable=io.StringIO) as stderr:
                    with patch("sys.stdout", new_callable=io.StringIO):
                        exit_code = build_index_cli.main()

            self.assertEqual(exit_code, 1)
            self.assertIn("Skipped malformed HVS candidate files", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
