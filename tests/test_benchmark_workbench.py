from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz

from stella.benchmark.workbench import (
    Assertion,
    WorkbenchContaminationError,
    build_paper_workbench,
    ensure_reviewable,
    extract_assertions,
    locate_all,
    locate_assertion,
    render_workbench_html,
)
import json


def synthetic_payload() -> dict:
    return {
        "schema_version": "stella.literature_hvs_candidates.v0.1",
        "paper": {"title": "A synthetic HVS paper"},
        "extraction": {"status": "candidates_found"},
        "method_chain": [
            {
                "id": "step-01",
                "step_type": "galactic_potential_model",
                "parameters": [
                    {
                        "name": "potential_name",
                        "raw_value": "MWPotential2014",
                        "value": "MWPotential2014",
                    }
                ],
            },
            {"id": "step-02", "step_type": "velocity_calculation", "parameters": []},
        ],
        "candidates": [
            {
                "identifiers": {
                    "record_id": "J1234+5678",
                    "gaia_source_id": "Gaia DR3 987654321",
                    "all": [{"value": "J1234+5678"}],
                },
                "inclusion_assessment": {
                    "paper_labels": ["hvs_candidate"],
                    "galactic_bound_claim": "likely_unbound",
                    "summary": "Treated as unbound.",
                },
                "core": {
                    "observed_phase_space": {
                        "radial_velocity": {
                            "raw_value": "612.3 +/- 4.1",
                            "value": "612.3",
                            "error": "4.1",
                            "unit": "km/s",
                        }
                    },
                    "derived_kinematics": {
                        "total_velocity": {
                            "raw_value": "743^{+15}_{-12}",
                            "value": "743",
                            "lower_error": "12",
                            "upper_error": "15",
                            "unit": "km/s",
                        },
                        "tangential_velocity": None,
                    },
                    "bound_assessment": {},
                },
            }
        ],
    }


def synthetic_pdf(path: Path) -> None:
    doc = fitz.open()
    page1 = doc.new_page()
    page1.insert_text((72, 72), "An unrelated introduction page. 612.3 appears here.")
    page2 = doc.new_page()
    page2.insert_text(
        (72, 72), "Star J1234+5678 has radial velocity 612.3 km/s."
    )
    page2.insert_text((72, 110), "Total velocity 743 km/s; potential MWPotential2014.")
    doc.save(path)
    doc.close()


class ExtractAssertionsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.assertions = extract_assertions(synthetic_payload())
        self.by_id = {item.assertion_id: item for item in self.assertions}

    def test_quantities_become_assertions_with_anchors(self) -> None:
        item = self.by_id["candidate:J1234+5678|derived_kinematics.total_velocity"]
        self.assertIn("743^{+15}_{-12}", item.anchors)
        self.assertIn("743", item.anchors)
        self.assertIn("J1234+5678", item.context_terms)

    def test_null_quantities_are_skipped(self) -> None:
        self.assertNotIn(
            "candidate:J1234+5678|derived_kinematics.tangential_velocity",
            self.by_id,
        )

    def test_method_parameters_become_assertions(self) -> None:
        item = self.by_id["method|step-01|potential_name"]
        self.assertIn("MWPotential2014", item.anchors)

    def test_step_type_summary_present(self) -> None:
        item = self.by_id["method|step_types"]
        self.assertIn("galactic_potential_model", item.display_value)
        self.assertIn("velocity_calculation", item.display_value)

    def test_identity_anchor_includes_gaia_digits(self) -> None:
        item = self.by_id["candidate:J1234+5678|identifiers"]
        self.assertIn("987654321", item.anchors)


class EnsureReviewableTest(unittest.TestCase):
    MANIFEST = {
        "papers": [
            {"arxiv_id": "1111.00001", "role": "verification", "overlap": False},
            {"arxiv_id": "2222.00002", "role": "blind", "overlap": True},
        ]
    }

    def test_verification_paper_is_allowed(self) -> None:
        self.assertEqual(
            ensure_reviewable(self.MANIFEST, "1111.00001"), "verification"
        )

    def test_blind_paper_is_refused(self) -> None:
        with self.assertRaises(WorkbenchContaminationError):
            ensure_reviewable(self.MANIFEST, "2222.00002")

    def test_blind_paper_is_refused_even_with_allow_unsampled(self) -> None:
        with self.assertRaises(WorkbenchContaminationError):
            ensure_reviewable(self.MANIFEST, "2222.00002", allow_unsampled=True)

    def test_unsampled_paper_needs_explicit_flag(self) -> None:
        with self.assertRaises(ValueError):
            ensure_reviewable(self.MANIFEST, "3333.00003")
        self.assertEqual(
            ensure_reviewable(self.MANIFEST, "3333.00003", allow_unsampled=True),
            "unsampled",
        )


class AnchoringTest(unittest.TestCase):
    def test_context_term_prefers_the_right_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "paper.pdf"
            synthetic_pdf(pdf_path)
            assertion = Assertion(
                assertion_id="a",
                group="candidate:J1234+5678",
                label="observed_phase_space.radial_velocity",
                display_value="612.3 km/s",
                anchors=("612.3",),
                context_terms=("J1234+5678",),
            )
            with fitz.open(pdf_path) as doc:
                page_texts = [doc[i].get_text() for i in range(doc.page_count)]
                hit = locate_assertion(doc, assertion, page_texts)
        self.assertIsNotNone(hit)
        # "612.3" appears on page 1 too; the candidate name pins page 2.
        self.assertEqual(hit.page_index, 1)
        self.assertEqual(hit.term, "612.3")

    def test_locate_all_renders_snippets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "paper.pdf"
            synthetic_pdf(pdf_path)
            assertions = extract_assertions(synthetic_payload())
            snippets_dir = Path(tmp) / "snippets"
            with fitz.open(pdf_path) as doc:
                located = locate_all(doc, assertions, snippets_dir)
            with_hits = [item for item in located if item.hit is not None]
            self.assertGreaterEqual(len(with_hits), 3)
            for item in with_hits:
                self.assertTrue((Path(tmp) / item.snippet_relpath).is_file())


class HtmlRenderingTest(unittest.TestCase):
    def test_page_contains_assertions_links_and_export(self) -> None:
        assertions = extract_assertions(synthetic_payload())
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "paper.pdf"
            synthetic_pdf(pdf_path)
            with fitz.open(pdf_path) as doc:
                located = locate_all(doc, assertions, Path(tmp) / "snippets")
            page = render_workbench_html(
                "9901.00001", "A synthetic HVS paper", located, "../../../literature/9901.00001/arxiv.pdf"
            )
        self.assertIn("data-assertion-id", page)
        self.assertIn("#page=2", page)
        self.assertIn('id="export"', page)
        self.assertIn("Candidate: J1234+5678", page)

    def test_unlocated_anchored_assertion_gets_notice(self) -> None:
        from stella.benchmark.workbench import LocatedAssertion

        missing = LocatedAssertion(
            assertion=Assertion(
                assertion_id="candidate:X|derived_kinematics.total_velocity",
                group="candidate:X",
                label="derived_kinematics.total_velocity",
                display_value="999.9 km/s",
                anchors=("999.9",),
            )
        )
        page = render_workbench_html("9901.00001", "t", [missing], "paper.pdf")
        self.assertIn("not auto-located", page)

    def test_build_paper_workbench_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf_path = root / "paper.pdf"
            synthetic_pdf(pdf_path)
            extraction_path = root / "literature_hvs_candidates.json"
            extraction_path.write_text(
                json.dumps(synthetic_payload()), encoding="utf-8"
            )
            report = build_paper_workbench(
                "9901.00001",
                extraction_path,
                pdf_path,
                root / "out",
                pdf_href="../paper.pdf",
            )
            self.assertTrue((root / "out" / "index.html").is_file())
            self.assertGreaterEqual(report["located"], 3)
            self.assertGreater(report["assertions"], report["located"])


if __name__ == "__main__":
    unittest.main()
