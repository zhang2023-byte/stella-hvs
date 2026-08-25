"""Optional ECSV selection tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from stella.lit.extraction.ecsv import (
    STATUS_COMPLETE,
    STATUS_PARTIAL,
    STATUS_UNAVAILABLE,
    EcsvStructureError,
    parse_ecsv_structure,
    select_ecsv_tables,
)
from stella.lit.extraction.tex_graph import resolve_tex_graph


ARXIV_ID = "2406.99999"
MAIN_TEX = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "\\begin{table}\n"
    "rows\n"
    "\\end{table}\n"
    "\\end{document}\n"
)
GOOD_ECSV = (
    "# %ECSV 1.0\n"
    "# ---\n"
    "# datatype:\n"
    "# - {name: col_001, datatype: string}\n"
    "# schema: astropy-2.0\n"
    "col_001 col_002\n"
    "1 2\n"
    "3 4\n"
)


def make_workspace(tmp: str, *, catalog: dict | None, ecsv_files: dict[str, str]) -> tuple[Path, Path]:
    workspace = Path(tmp)
    paper_dir = workspace / "literature" / ARXIV_ID
    (paper_dir / "arxiv_source").mkdir(parents=True)
    (paper_dir / "arxiv_source" / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    (paper_dir / "arxiv_source" / "draft.tex").write_text("unused\n", encoding="utf-8")
    if catalog is not None:
        (paper_dir / "catalog_extraction.json").write_text(
            json.dumps(catalog), encoding="utf-8"
        )
    for relative, content in ecsv_files.items():
        path = paper_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return workspace, paper_dir


def catalog_entry(
    table_id: str,
    *,
    table_status: str = "success",
    ecsv_path: str | None = f"literature/{ARXIV_ID}/catalog_tables/t1.ecsv",
    source_path: str | None = f"literature/{ARXIV_ID}/arxiv_source/main.tex",
    start_line: int | None = 3,
    end_line: int | None = 5,
    with_file: bool = True,
) -> dict:
    files = []
    if with_file:
        files.append(
            {
                "id": table_id,
                "status": "written",
                "source_ref": {
                    "path": source_path,
                    "start_line": start_line,
                    "end_line": end_line,
                    "label": "tab:x",
                },
            }
        )
    table: dict = {"id": table_id, "status": table_status, "label": "tab:x"}
    if ecsv_path is not None:
        table["ecsv_path"] = ecsv_path
    return {"files": files, "tables": [table]}


def select(workspace: Path, paper_dir: Path):
    graph = resolve_tex_graph(paper_dir / "arxiv_source")
    return select_ecsv_tables(workspace, paper_dir, graph)


class EcsvStructureTest(unittest.TestCase):
    def test_parse_good_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.ecsv"
            path.write_text(GOOD_ECSV, encoding="utf-8")
            structure = parse_ecsv_structure(path)
            self.assertEqual(structure.columns, ("col_001", "col_002"))
            self.assertEqual(structure.column_row_line, 6)
            self.assertEqual(structure.data_row_lines, (7, 8))

    def test_rejects_missing_header_and_missing_data_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.ecsv"
            bad.write_text("col_001\n1\n", encoding="utf-8")
            with self.assertRaises(EcsvStructureError):
                parse_ecsv_structure(bad)
            empty = Path(tmp) / "empty.ecsv"
            empty.write_text("# %ECSV 1.0\n# ---\ncol_001\n", encoding="utf-8")
            with self.assertRaises(EcsvStructureError):
                parse_ecsv_structure(empty)


class EcsvSelectionTest(unittest.TestCase):
    def test_complete_selection_with_minimal_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, paper_dir = make_workspace(
                tmp,
                catalog=catalog_entry("t1"),
                ecsv_files={"catalog_tables/t1.ecsv": GOOD_ECSV},
            )
            selection = select(workspace, paper_dir)
            self.assertEqual(selection.status, STATUS_COMPLETE)
            self.assertEqual(selection.excluded, [])
            (selected,) = selection.selected
            self.assertEqual(selected.ecsv_path, "catalog_tables/t1.ecsv")
            self.assertEqual(selected.source_tex_path, "main.tex")
            self.assertEqual(selected.source_tex_start_line, 3)
            self.assertEqual(selected.source_tex_end_line, 5)
            self.assertEqual(selected.label, "tab:x")

    def test_no_catalog_extraction_is_unavailable_without_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, paper_dir = make_workspace(tmp, catalog=None, ecsv_files={})
            selection = select(workspace, paper_dir)
            self.assertEqual(selection.status, STATUS_UNAVAILABLE)
            self.assertEqual(selection.selected, [])

    def test_exclusion_reasons_per_table(self) -> None:
        cases = {
            "table_not_success": catalog_entry("t1", table_status="failed"),
            "mapping_missing": catalog_entry("t1", with_file=False),
            "mapped_tex_outside_manuscript_graph": catalog_entry(
                "t1", source_path=f"literature/{ARXIV_ID}/arxiv_source/draft.tex"
            ),
            "mapped_range_invalid": catalog_entry("t1", start_line=5, end_line=3),
            "mapped_range_invalid_out_of_bounds": catalog_entry("t1", start_line=3, end_line=99),
            "ecsv_missing": catalog_entry(
                "t1", ecsv_path=f"literature/{ARXIV_ID}/catalog_tables/absent.ecsv"
            ),
        }
        for name, catalog in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                workspace, paper_dir = make_workspace(
                    tmp, catalog=catalog, ecsv_files={"catalog_tables/t1.ecsv": GOOD_ECSV}
                )
                selection = select(workspace, paper_dir)
                self.assertEqual(selection.status, STATUS_UNAVAILABLE)
                self.assertEqual(len(selection.excluded), 1)
                expected = name.replace("_out_of_bounds", "")
                self.assertTrue(
                    selection.excluded[0]["reason"].startswith(expected),
                    selection.excluded[0]["reason"],
                )

    def test_invalid_ecsv_structure_is_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, paper_dir = make_workspace(
                tmp,
                catalog=catalog_entry("t1"),
                ecsv_files={"catalog_tables/t1.ecsv": "not an ecsv\n"},
            )
            selection = select(workspace, paper_dir)
            self.assertEqual(selection.status, STATUS_UNAVAILABLE)
            self.assertTrue(selection.excluded[0]["reason"].startswith("ecsv_invalid_structure"))

    def test_partial_when_some_tables_excluded(self) -> None:
        catalog = catalog_entry("t1")
        second = catalog_entry("t2", table_status="failed")
        catalog["files"].extend(second["files"])
        catalog["tables"].extend(second["tables"])
        with tempfile.TemporaryDirectory() as tmp:
            workspace, paper_dir = make_workspace(
                tmp,
                catalog=catalog,
                ecsv_files={"catalog_tables/t1.ecsv": GOOD_ECSV},
            )
            selection = select(workspace, paper_dir)
            self.assertEqual(selection.status, STATUS_PARTIAL)
            self.assertEqual(len(selection.selected), 1)
            self.assertEqual(selection.excluded[0]["reason"], "table_not_success")

    def test_rejects_parent_absolute_prefix_and_symlink_escapes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, paper_dir = make_workspace(tmp, catalog=None, ecsv_files={})
            outside = workspace / "outside.ecsv"
            outside.write_text(GOOD_ECSV, encoding="utf-8")
            sibling = workspace / "literature" / f"{ARXIV_ID}-evil"
            sibling.mkdir()
            (sibling / "t.ecsv").write_text(GOOD_ECSV, encoding="utf-8")
            (paper_dir / "catalog_tables").mkdir()
            (paper_dir / "catalog_tables" / "escape.ecsv").symlink_to(outside)
            (paper_dir / "inside-via-parent.ecsv").write_text(
                GOOD_ECSV, encoding="utf-8"
            )

            cases = {
                "parent": (
                    f"literature/{ARXIV_ID}/catalog_tables/../inside-via-parent.ecsv"
                ),
                "absolute": str(outside),
                "prefix": f"literature/{ARXIV_ID}-evil/t.ecsv",
                "symlink": (
                    f"literature/{ARXIV_ID}/catalog_tables/escape.ecsv"
                ),
            }
            for name, path in cases.items():
                with self.subTest(name=name):
                    catalog = catalog_entry("t1", ecsv_path=path)
                    (paper_dir / "catalog_extraction.json").write_text(
                        json.dumps(catalog), encoding="utf-8"
                    )
                    selection = select(workspace, paper_dir)
                    self.assertEqual(selection.status, STATUS_UNAVAILABLE)
                    self.assertEqual(len(selection.selected), 0)
                    self.assertTrue(
                        selection.excluded[0]["reason"].startswith("ecsv_missing")
                    )


if __name__ == "__main__":
    unittest.main()
