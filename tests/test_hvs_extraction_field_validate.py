"""Field structural/locator validation, hydration, and bibliography tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stella.hvs_extraction.ecsv import parse_ecsv_structure
from stella.hvs_extraction.ecsv_cells import cell_at, parse_ecsv_row
from stella.hvs_extraction.field_validate import (
    BIBLIOGRAPHY_UNRESOLVED,
    CONFLICT_RESOLUTION_INCONSISTENT,
    COORDINATE_FORMAT_INCONSISTENT,
    DIRECT_EVIDENCE_MISSING,
    DIRECT_EVIDENCE_UNEXPECTED,
    ECSV_COMPONENT_NOT_FOUND,
    ECSV_LINE_NOT_DATA_ROW,
    ORIGIN_BIBKEY_FORBIDDEN,
    ORIGIN_BIBKEY_REQUIRED,
    QUANTITY_EMPTY,
    RANGE_INCONSISTENT,
    RESOLVED,
    TEXT_RAW_VALUE_NOT_FOUND,
    UNCERTAINTY_INCOMPLETE_ASYMMETRIC,
    UNCERTAINTY_MIXED,
    FieldValidationContext,
    hydrate_field_submission,
    resolve_bibliography_key,
    validate_field_submission,
)
from tests.test_hvs_extraction_field_schema import valid_submission


TEX_TEXT = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "HVS-1 is unbound with radial velocity 805 km/s \\cite{smith2024}.\n"
    "WD-9 is bound.\n"
    "\\bibliography{references}\n"
    "\\end{document}\n"
)
GOOD_ECSV = (
    "# %ECSV 1.0\n"
    "# ---\n"
    "# datatype:\n"
    "# - {name: col_001, datatype: string, description: Name}\n"
    "# - {name: col_002, datatype: string, description: RV [km s^-1]}\n"
    "# schema: astropy-2.0\n"
    "col_001 col_002\n"
    "HVS-1 805\n"
    "HVS-2 900\n"
)


def make_ctx(tmp: Path) -> FieldValidationContext:
    ecsv_path = tmp / "t1.ecsv"
    ecsv_path.write_text(GOOD_ECSV, encoding="utf-8")
    structure = parse_ecsv_structure(ecsv_path)
    return FieldValidationContext(
        tex_line_counts={"main.tex": 6},
        tex_texts={"main.tex": TEX_TEXT},
        ecsv_structures={"catalog_tables/t1.ecsv": structure},
        ecsv_texts={"catalog_tables/t1.ecsv": GOOD_ECSV},
    )


class EcsvCellParserTest(unittest.TestCase):
    def test_plain_quoted_and_empty_cells(self) -> None:
        self.assertEqual(parse_ecsv_row('a  "b c"  ""'), ["a", "b c", ""])
        self.assertEqual(parse_ecsv_row('"say ""hi""" x'), ['say "hi"', "x"])
        self.assertEqual(cell_at("HVS-1 805", 1), "805")

    def test_unterminated_quote_fails(self) -> None:
        with self.assertRaises(Exception):
            parse_ecsv_row('"open')


class FieldValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.ctx = make_ctx(Path(self.tmp.name))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def validate(self, payload: dict):
        return validate_field_submission(payload, self.ctx)

    def test_valid_submission_passes(self) -> None:
        self.assertEqual(self.validate(valid_submission()), [])

    def test_quantity_structural_invariants(self) -> None:
        cases = {
            QUANTITY_EMPTY: {"value": None},
            UNCERTAINTY_MIXED: {"error": "5", "lower_error": "4"},
            UNCERTAINTY_INCOMPLETE_ASYMMETRIC: {"lower_error": "4"},
            RANGE_INCONSISTENT: {"limit_kind": "range", "range_lower": "1", "range_upper": "2"},
        }
        for code, overrides in cases.items():
            with self.subTest(code=code):
                payload = valid_submission()
                quantity = payload["core"]["observed_phase_space"]["radial_velocity"]
                quantity.update(overrides)
                issues = self.validate(payload)
                self.assertIn(code, [issue.code for issue in issues])

    def test_direct_evidence_mapping(self) -> None:
        payload = valid_submission()
        quantity = payload["core"]["observed_phase_space"]["radial_velocity"]
        quantity["error"] = "12"
        issues = self.validate(payload)
        self.assertIn(DIRECT_EVIDENCE_MISSING, [issue.code for issue in issues])
        # An evidence item for an unpopulated component is unexpected.
        quantity["error"] = None
        quantity["direct_evidence"].append(
            {
                "part": "lower_error",
                "source": dict(quantity["direct_evidence"][0]["source"]),
            }
        )
        issues = self.validate(payload)
        codes = [issue.code for issue in issues]
        self.assertIn(DIRECT_EVIDENCE_UNEXPECTED, codes)

    def test_coordinate_format_checks(self) -> None:
        payload = valid_submission()
        coord = {
            "value": "12:34:56.7",
            "error": None,
            "lower_error": None,
            "upper_error": None,
            "unit": "h",
            "limit_kind": "none",
            "range_lower": None,
            "range_upper": None,
            "direct_evidence": [
                {
                    "part": "value",
                    "source": {
                        "kind": "text",
                        "path": "main.tex",
                        "start_line": 3,
                        "end_line": 3,
                        "raw_value": "805",
                    },
                }
            ],
            "context_evidence": [],
            "coordinate_format": "sexagesimal_colon",
        }
        payload["core"]["observed_phase_space"]["ra"] = coord
        self.assertEqual(self.validate(payload), [])
        coord["coordinate_format"] = "sexagesimal_hms"
        payload["core"]["observed_phase_space"]["dec"] = dict(coord)
        issues = self.validate(payload)
        self.assertIn(COORDINATE_FORMAT_INCONSISTENT, [issue.code for issue in issues])

    def test_origin_conditional_rules(self) -> None:
        payload = valid_submission()
        payload["candidate_origin"]["origin_type"] = "cited_from_literature"
        issues = self.validate(payload)
        self.assertIn(ORIGIN_BIBKEY_REQUIRED, [issue.code for issue in issues])
        payload["candidate_origin"]["bibkey"] = "smith2024"
        self.assertEqual(self.validate(payload), [])
        payload["candidate_origin"]["origin_type"] = "introduced_by_this_paper"
        issues = self.validate(payload)
        self.assertIn(ORIGIN_BIBKEY_FORBIDDEN, [issue.code for issue in issues])

    def test_text_raw_value_must_occur_verbatim(self) -> None:
        payload = valid_submission()
        payload["core"]["observed_phase_space"]["radial_velocity"]["direct_evidence"][0][
            "source"
        ]["raw_value"] = "999"
        issues = self.validate(payload)
        self.assertIn(TEXT_RAW_VALUE_NOT_FOUND, [issue.code for issue in issues])

    def test_ecsv_locator_checks_and_compound_component(self) -> None:
        payload = valid_submission()
        source = {
            "kind": "ecsv_cell",
            "path": "catalog_tables/t1.ecsv",
            "line": 8,
            "column": "col_002",
        }
        payload["core"]["observed_phase_space"]["radial_velocity"]["direct_evidence"][0][
            "source"
        ] = source
        self.assertEqual(self.validate(payload), [])
        source["line"] = 7
        issues = self.validate(payload)
        self.assertIn(ECSV_LINE_NOT_DATA_ROW, [issue.code for issue in issues])
        source["line"] = 8
        source["component_raw_value"] = "999"
        issues = self.validate(payload)
        self.assertIn(ECSV_COMPONENT_NOT_FOUND, [issue.code for issue in issues])
        source["component_raw_value"] = "80"
        self.assertEqual(self.validate(payload), [])

    def test_conflict_resolution_consistency(self) -> None:
        payload = valid_submission()
        payload["provenance_conflicts"].append(
            {
                "field": "observed_phase_space.radial_velocity",
                "tex_source": {"path": "main.tex", "start_line": 3, "end_line": 3},
                "ecsv_source": {
                    "path": "catalog_tables/t1.ecsv",
                    "line": 8,
                    "column": "col_002",
                },
                "resolution": "unresolved",
                "reason": "The cell and the TeX disagree.",
            }
        )
        issues = self.validate(payload)
        self.assertIn(CONFLICT_RESOLUTION_INCONSISTENT, [issue.code for issue in issues])
        payload["provenance_conflicts"][0]["resolution"] = "use_tex"
        self.assertEqual(self.validate(payload), [])

    def test_hydration_copies_exact_sources(self) -> None:
        payload = valid_submission()
        payload["core"]["observed_phase_space"]["radial_velocity"]["direct_evidence"][0][
            "source"
        ] = {
            "kind": "ecsv_cell",
            "path": "catalog_tables/t1.ecsv",
            "line": 8,
            "column": "col_002",
        }
        hydrated = hydrate_field_submission(
            payload, self.ctx, tex_sha256={"main.tex": "0" * 64}
        )
        source = hydrated["core"]["observed_phase_space"]["radial_velocity"][
            "direct_evidence"
        ][0]["source"]
        self.assertEqual(source["cell_raw_value"], "805")
        self.assertEqual(source["quantity_raw_value"], "805")
        self.assertEqual(source["column_header"], "RV [km s^-1]")
        origin_ref = hydrated["candidate_origin"]["evidence"][0]
        self.assertEqual(
            origin_ref["resolved_text"],
            "HVS-1 is unbound with radial velocity 805 km/s \\cite{smith2024}.",
        )


class BibliographyResolutionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.source_dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_bib_resolution_with_metadata(self) -> None:
        (self.source_dir / "references.bib").write_text(
            "@article{smith2024,\n"
            "  author = {Smith, A. and {\\it Jones}, B.},\n"
            "  year = {2024},\n"
            "  title = {HVS {\\it survey}},\n"
            "  doi = {10.1234/x}\n"
            "}\n",
            encoding="utf-8",
        )
        resolution = resolve_bibliography_key(
            "smith2024",
            [{"kind": "bib", "path": "references.bib", "start_line": None, "end_line": None}],
            self.source_dir,
        )
        self.assertEqual(resolution.status, RESOLVED)
        metadata = resolution.reference["metadata"]
        self.assertEqual(metadata["year"], "2024")
        self.assertEqual(metadata["title"], "HVS {\\it survey}")
        self.assertEqual(metadata["doi"], "10.1234/x")
        self.assertEqual(resolution.reference["start_line"], 1)
        self.assertEqual(resolution.reference["end_line"], 6)

    def test_bbl_resolution(self) -> None:
        (self.source_dir / "main.bbl").write_text(
            "\\begin{thebibliography}{1}\n"
            "\\bibitem{smith2024} Smith 2024.\n"
            "\\bibitem{other} Other.\n"
            "\\end{thebibliography}\n",
            encoding="utf-8",
        )
        resolution = resolve_bibliography_key(
            "smith2024",
            [{"kind": "bbl", "path": "main.bbl", "start_line": None, "end_line": None}],
            self.source_dir,
        )
        self.assertEqual(resolution.status, RESOLVED)
        self.assertEqual(resolution.reference["start_line"], 2)
        self.assertEqual(resolution.reference["end_line"], 3)

    def test_unresolved_is_diagnostic_not_failure(self) -> None:
        (self.source_dir / "references.bib").write_text(
            "@article{other, title={x}}\n", encoding="utf-8"
        )
        resolution = resolve_bibliography_key(
            "smith2024",
            [{"kind": "bib", "path": "references.bib", "start_line": None, "end_line": None}],
            self.source_dir,
        )
        self.assertEqual(resolution.status, BIBLIOGRAPHY_UNRESOLVED)
        self.assertEqual(resolution.reason, "bibliography_key_not_found")
        empty = resolve_bibliography_key("smith2024", [], self.source_dir)
        self.assertEqual(empty.reason, "bibliography_source_missing")


if __name__ == "__main__":
    unittest.main()
