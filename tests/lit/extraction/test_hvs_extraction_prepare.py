"""prepare_paper_context stage integration tests."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from stella.lit.extraction.method import HvsContextBudget
from stella.lit.extraction.prepare import (
    MODE_FIELD_TOO_LARGE,
    MODE_FULL,
    MODE_TEX_ONLY,
    STATUS_INPUT_PREPARATION_FAILURE,
    STATUS_INPUT_TOO_LARGE,
    STATUS_PREPARED,
    build_prepared_input,
    estimate_tokens,
    write_prepared_input,
)


ARXIV_ID = "2406.99999"
MAIN_TEX = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "The paper body cites \\cite{smith2024}. % a comment\n"
    "\\bibliography{references}\n"
    "\\end{document}\n"
)
GOOD_ECSV = (
    "# %ECSV 1.0\n"
    "# ---\n"
    "# datatype:\n"
    "# - {name: col_001, datatype: string}\n"
    "# schema: astropy-2.0\n"
    "col_001\n"
    "42\n"
)


def budget(limit: int, reserve: int = 0) -> HvsContextBudget:
    return HvsContextBudget(
        model_context_limit=limit,
        reserve_system_and_rules=reserve,
        reserve_tool_schema=0,
        reserve_candidate_suffix=0,
        reserve_output=0,
        reserve_provider_framing=0,
    )


GENEROUS = budget(1_000_000)


def make_paper(
    tmp: str,
    *,
    with_catalog: bool = True,
    table_labels: list[str] | None = None,
) -> tuple[Path, Path]:
    workspace = Path(tmp)
    paper_dir = workspace / "literature" / ARXIV_ID
    (paper_dir / "arxiv_source").mkdir(parents=True)
    (paper_dir / "arxiv_source" / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    (paper_dir / "arxiv_source" / "main.bbl").write_text(
        "\\begin{thebibliography}{1}\n\\bibitem{smith2024} x\n\\end{thebibliography}\n",
        encoding="utf-8",
    )
    (paper_dir / "arxiv_source" / "references.bib").write_text(
        "@article{smith2024, title={x}}\n", encoding="utf-8"
    )
    if with_catalog:
        labels = table_labels or ["tab:x"]
        (paper_dir / "catalog_extraction.json").write_text(
            json.dumps(
                {
                    "files": [
                        {
                            "id": f"t{index}",
                            "status": "written",
                            "source_ref": {
                                "path": f"literature/{ARXIV_ID}/arxiv_source/main.tex",
                                "start_line": 3,
                                "end_line": 3,
                                "label": label,
                            },
                        }
                        for index, label in enumerate(labels, start=1)
                    ],
                    "tables": [
                        {
                            "id": f"t{index}",
                            "status": "success",
                            "ecsv_path": (
                                f"literature/{ARXIV_ID}/catalog_tables/t{index}.ecsv"
                            ),
                            "label": label,
                        }
                        for index, label in enumerate(labels, start=1)
                    ],
                }
            ),
            encoding="utf-8",
        )
        (paper_dir / "catalog_tables").mkdir()
        for index in range(1, len(labels) + 1):
            (paper_dir / "catalog_tables" / f"t{index}.ecsv").write_text(
                GOOD_ECSV, encoding="utf-8"
            )
    return workspace, paper_dir


class BuildPreparedInputTest(unittest.TestCase):
    def test_prepared_artifact_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, _ = make_paper(tmp)
            artifact = build_prepared_input(
                workspace, ARXIV_ID, roster_budget=GENEROUS, field_budget=GENEROUS
            )
            self.assertEqual(artifact["status"], STATUS_PREPARED)
            self.assertIsNone(artifact["failure"])
            self.assertEqual(
                artifact["schema"],
                {"name": "hvs_extraction.prepared_input", "version": 1},
            )
            manuscript = artifact["manuscript"]
            self.assertEqual(manuscript["root"], "main.tex")
            self.assertEqual(manuscript["included"], ["main.tex"])
            self.assertEqual(manuscript["excluded"], [])
            view = manuscript["view"]
            self.assertIn("===== BEGIN FILE: main.tex =====", view)
            self.assertIn("3|The paper body cites \\cite{smith2024}. ", view)
            self.assertNotIn("a comment", view)
            self.assertEqual(
                manuscript["view_sha256"], hashlib.sha256(view.encode("utf-8")).hexdigest()
            )
            self.assertEqual(artifact["ecsv"]["status"], "complete")
            (selected,) = artifact["ecsv"]["selected"]
            self.assertEqual(selected["ecsv_path"], "catalog_tables/t1.ecsv")
            self.assertEqual(selected["columns"], ["col_001"])
            kinds = [item["kind"] for item in artifact["bibliography"]]
            self.assertEqual(kinds, ["bbl", "bib"])
            context = artifact["context"]
            self.assertTrue(context["roster_fit"])
            self.assertEqual(context["field_context_mode"], MODE_FULL)
            self.assertEqual(context["field_ecsv_context_status"], "complete")

    def test_graph_failure_produces_structured_input_preparation_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, paper_dir = make_paper(tmp)
            (paper_dir / "arxiv_source" / "second.tex").write_text(MAIN_TEX, encoding="utf-8")
            artifact = build_prepared_input(
                workspace, ARXIV_ID, roster_budget=GENEROUS, field_budget=GENEROUS
            )
            self.assertEqual(artifact["status"], STATUS_INPUT_PREPARATION_FAILURE)
            self.assertEqual(
                artifact["failure"]["code"], "multiple_root_tex_candidates"
            )

    def test_reviewed_root_resolves_multiple_manuscripts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, paper_dir = make_paper(tmp)
            (paper_dir / "arxiv_source" / "second.tex").write_text(MAIN_TEX, encoding="utf-8")
            (paper_dir / "catalog_review.json").write_text(
                json.dumps({"source": {"tex_root": f"literature/{ARXIV_ID}/arxiv_source/main.tex"}}),
                encoding="utf-8",
            )
            artifact = build_prepared_input(
                workspace, ARXIV_ID, roster_budget=GENEROUS, field_budget=GENEROUS
            )
            self.assertEqual(artifact["status"], STATUS_PREPARED)
            self.assertEqual(artifact["manuscript"]["root"], "main.tex")
            self.assertIn("selected reviewed TeX root", artifact["manuscript"]["diagnostics"][0])

    def test_roster_oversize_is_input_too_large_without_model_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, _ = make_paper(tmp)
            artifact = build_prepared_input(
                workspace, ARXIV_ID, roster_budget=budget(10), field_budget=GENEROUS
            )
            self.assertEqual(artifact["status"], STATUS_INPUT_TOO_LARGE)
            self.assertEqual(artifact["failure"]["code"], STATUS_INPUT_TOO_LARGE)
            self.assertEqual(artifact["context"]["field_context_mode"], MODE_FIELD_TOO_LARGE)

    def test_field_mode_falls_back_to_tex_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, _ = make_paper(tmp)
            artifact = build_prepared_input(
                workspace,
                ARXIV_ID,
                roster_budget=GENEROUS,
                field_budget=budget(estimate_tokens(MAIN_TEX) + 40),
            )
            context = artifact["context"]
            self.assertEqual(artifact["status"], STATUS_PREPARED)
            self.assertEqual(context["field_context_mode"], MODE_TEX_ONLY)
            self.assertEqual(context["field_ecsv_context_status"], "unavailable")
            self.assertEqual(
                context["field_ecsv_exclusion_reason"], "context_budget_exceeded"
            )

    def test_field_input_too_large_when_manuscript_alone_exceeds_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, _ = make_paper(tmp)
            artifact = build_prepared_input(
                workspace, ARXIV_ID, roster_budget=GENEROUS, field_budget=budget(5)
            )
            self.assertEqual(artifact["status"], STATUS_PREPARED)
            self.assertEqual(artifact["context"]["field_context_mode"], MODE_FIELD_TOO_LARGE)

    def test_write_prepared_input_roundtrip_under_run_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace, _ = make_paper(tmp)
            artifact = build_prepared_input(
                workspace, ARXIV_ID, roster_budget=GENEROUS, field_budget=GENEROUS
            )
            path = write_prepared_input(workspace, "run-test", artifact)
            self.assertEqual(
                path.relative_to(workspace).as_posix(),
                f"benchmark/campaigns/hvs-extraction-v6/runs/run-test/prepared_inputs/{ARXIV_ID}.json",
            )
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["manuscript"]["view"], artifact["manuscript"]["view"])


class MultiTablePreparedInputTest(unittest.TestCase):
    """Exercise the former real-paper path without ignored local assets."""

    def test_five_table_prepared_end_to_end(self) -> None:
        labels = [
            "tab:selections",
            "tab:source_table",
            "tab:obs",
            "tab:obs_results",
            "tab:external",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            workspace, _ = make_paper(tmp, table_labels=labels)
            artifact = build_prepared_input(
                workspace,
                ARXIV_ID,
                roster_budget=GENEROUS,
                field_budget=GENEROUS,
            )
            self.assertEqual(artifact["status"], STATUS_PREPARED)
            manuscript = artifact["manuscript"]
            self.assertEqual(manuscript["root"], "main.tex")
            self.assertEqual(manuscript["included"], ["main.tex"])
            self.assertEqual(manuscript["excluded"], [])
            self.assertEqual(artifact["ecsv"]["status"], "complete")
            self.assertEqual(len(artifact["ecsv"]["selected"]), 5)
            first = artifact["ecsv"]["selected"][0]
            self.assertEqual(first["source_tex_path"], "main.tex")
            self.assertEqual(first["label"], "tab:selections")
            kinds = [item["kind"] for item in artifact["bibliography"]]
            self.assertEqual(kinds, ["bbl", "bib"])
            self.assertEqual(
                artifact["context"]["field_context_mode"], MODE_FULL
            )
            repeat = build_prepared_input(
                workspace,
                ARXIV_ID,
                roster_budget=GENEROUS,
                field_budget=GENEROUS,
            )
            self.assertEqual(
                artifact["manuscript"]["view_sha256"],
                repeat["manuscript"]["view_sha256"],
            )
            self.assertEqual(
                artifact["context"]["field_shared_prefix_sha256"],
                repeat["context"]["field_shared_prefix_sha256"],
            )


if __name__ == "__main__":
    unittest.main()
