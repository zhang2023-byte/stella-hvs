"""Fail-closed TeX manuscript graph resolution tests (D004, D005)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stella.hvs_extraction.tex_graph import (
    CYCLIC_INCLUDE,
    INCLUDE_OUTSIDE,
    MISSING_INCLUDED,
    MISSING_ROOT,
    MULTIPLE_ROOTS,
    UNDECODABLE,
    UNSUPPORTED_DIRECTIVE,
    TexGraphError,
    resolve_tex_graph,
)


ROOT_TEX = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "body\n"
    "\\end{document}\n"
)


def make_source(tmp: str, files: dict[str, str]) -> Path:
    source = Path(tmp) / "arxiv_source"
    for relative, text in files.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return source


def assert_error_code(test: unittest.TestCase, code: str, source: Path) -> TexGraphError:
    with test.assertRaises(TexGraphError) as caught:
        resolve_tex_graph(source)
    test.assertEqual(caught.exception.code, code)
    return caught.exception


class TexGraphResolutionTest(unittest.TestCase):
    def test_single_root_without_includes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            graph = resolve_tex_graph(make_source(tmp, {"main.tex": ROOT_TEX}))
            self.assertEqual(graph.root, "main.tex")
            self.assertEqual(graph.included, ["main.tex"])
            self.assertEqual(graph.excluded, [])
            self.assertEqual(graph.files["main.tex"].line_count, 4)
            self.assertEqual(graph.files["main.tex"].encoding, "utf-8")

    def test_includes_followed_in_reading_order(self) -> None:
        main = (
            "\\documentclass{article}\n"
            "\\begin{document}\n"
            "\\input{sections/intro}\n"
            "\\input{sections/methods.tex}\n"
            "\\end{document}\n"
        )
        intro = "intro\n\\input{appendix}\n"
        with tempfile.TemporaryDirectory() as tmp:
            graph = resolve_tex_graph(
                make_source(
                    tmp,
                    {
                        "main.tex": main,
                        "sections/intro.tex": intro,
                        "sections/methods.tex": "methods\n",
                        "sections/appendix.tex": "appendix\n",
                        "draft.tex": "\\documentclass{x}\nno begin document\n",
                    },
                )
            )
            self.assertEqual(
                graph.included,
                ["main.tex", "sections/intro.tex", "sections/appendix.tex", "sections/methods.tex"],
            )
            self.assertEqual(
                graph.edges,
                {
                    "main.tex": ["sections/intro.tex", "sections/methods.tex"],
                    "sections/intro.tex": ["sections/appendix.tex"],
                },
            )
            self.assertEqual(graph.excluded, ["draft.tex"])

    def test_commented_out_include_is_ignored(self) -> None:
        main = ROOT_TEX.replace("body\n", "% \\input{ghost}\nbody\n")
        with tempfile.TemporaryDirectory() as tmp:
            graph = resolve_tex_graph(make_source(tmp, {"main.tex": main}))
            self.assertEqual(graph.included, ["main.tex"])

    def test_missing_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = make_source(tmp, {"main.tex": "no document structure\n"})
            assert_error_code(self, MISSING_ROOT, source)

    def test_multiple_roots_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = make_source(
                tmp, {"a.tex": ROOT_TEX, "nested/b.tex": ROOT_TEX}
            )
            error = assert_error_code(self, MULTIPLE_ROOTS, source)
            self.assertIn("a.tex", error.detail)
            self.assertIn("nested/b.tex", error.detail)

    def test_missing_included_tex(self) -> None:
        main = ROOT_TEX.replace("body\n", "\\input{nope}\n")
        with tempfile.TemporaryDirectory() as tmp:
            assert_error_code(self, MISSING_INCLUDED, make_source(tmp, {"main.tex": main}))

    def test_cyclic_include(self) -> None:
        main = ROOT_TEX.replace("body\n", "\\input{a}\n")
        with tempfile.TemporaryDirectory() as tmp:
            source = make_source(
                tmp,
                {"main.tex": main, "a.tex": "\\input{b}\n", "b.tex": "\\input{a}\n"},
            )
            error = assert_error_code(self, CYCLIC_INCLUDE, source)
            self.assertIn("a.tex", error.detail)

    def test_include_outside_paper_directory(self) -> None:
        main = ROOT_TEX.replace("body\n", "\\input{../escape}\n")
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "escape.tex").write_text("outside\n", encoding="utf-8")
            assert_error_code(self, INCLUDE_OUTSIDE, make_source(tmp, {"main.tex": main}))

    def test_undecodable_tex_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "arxiv_source"
            source.mkdir()
            (source / "main.tex").write_bytes(ROOT_TEX.encode("utf-8") + b"\x00\x01")
            assert_error_code(self, UNDECODABLE, source)

    def test_latin1_fallback_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "arxiv_source"
            source.mkdir()
            (source / "main.tex").write_bytes(
                ROOT_TEX.replace("body", "caf\xe9").encode("latin-1")
            )
            graph = resolve_tex_graph(source)
            self.assertEqual(graph.files["main.tex"].encoding, "latin-1")
            self.assertTrue(any("latin-1" in item for item in graph.diagnostics))

    def test_unsupported_include_directive_fails_closed(self) -> None:
        main = ROOT_TEX.replace("body\n", "\\subfile{chapter}\n")
        with tempfile.TemporaryDirectory() as tmp:
            source = make_source(tmp, {"main.tex": main, "chapter.tex": "x\n"})
            assert_error_code(self, UNSUPPORTED_DIRECTIVE, source)

    def test_duplicate_include_is_included_once(self) -> None:
        main = ROOT_TEX.replace("body\n", "\\input{a}\n\\input{a}\n")
        with tempfile.TemporaryDirectory() as tmp:
            graph = resolve_tex_graph(
                make_source(tmp, {"main.tex": main, "a.tex": "shared\n"})
            )
            self.assertEqual(graph.included, ["main.tex", "a.tex"])
            self.assertTrue(any("duplicate include" in item for item in graph.diagnostics))

    def test_non_tex_include_is_reported_not_followed(self) -> None:
        main = ROOT_TEX.replace("body\n", "\\input{main.bbl}\nbody\n")
        with tempfile.TemporaryDirectory() as tmp:
            graph = resolve_tex_graph(
                make_source(tmp, {"main.tex": main, "main.bbl": "\\begin{thebibliography}\n"})
            )
            self.assertEqual(graph.included, ["main.tex"])
            self.assertEqual(graph.non_tex_includes, [("main.tex", "main.bbl")])


if __name__ == "__main__":
    unittest.main()
