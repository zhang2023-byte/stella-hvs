"""Fail-closed TeX manuscript graph resolution tests."""

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
    resolve_frozen_tex_graph,
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


class FrozenTexGraphTest(unittest.TestCase):
    """The immutable-context re-resolution must honor the frozen root."""

    @staticmethod
    def manuscript(graph) -> dict:
        return {
            "root": graph.root,
            "included": graph.included,
            "files": {
                name: {"sha256": item.sha256}
                for name, item in graph.files.items()
            },
        }

    def test_frozen_root_disambiguates_multi_root_source(self) -> None:
        # Regression shape of the 2509.24010/1912.10125 false context_mutation:
        # preparation selected a reviewed root, but a plain re-resolution
        # without the frozen root fails closed with MULTIPLE_ROOTS.
        with tempfile.TemporaryDirectory() as tmp:
            source = make_source(
                tmp, {"main.tex": ROOT_TEX, "style_doc.tex": ROOT_TEX}
            )
            with self.assertRaises(TexGraphError) as caught:
                resolve_tex_graph(source)
            self.assertEqual(caught.exception.code, MULTIPLE_ROOTS)
            graph = resolve_tex_graph(source, reviewed_root="main.tex")
            frozen = resolve_frozen_tex_graph(source, self.manuscript(graph))
            self.assertEqual(frozen.root, "main.tex")
            self.assertEqual(frozen.included, ["main.tex"])

    def test_frozen_graph_detects_content_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = make_source(tmp, {"main.tex": ROOT_TEX})
            manuscript = self.manuscript(resolve_tex_graph(source))
            (source / "main.tex").write_text(
                ROOT_TEX.replace("body", "mutated"), encoding="utf-8"
            )
            with self.assertRaisesRegex(
                ValueError, "main.tex changed after preparation"
            ):
                resolve_frozen_tex_graph(source, manuscript)

    def test_frozen_graph_detects_include_graph_mutation(self) -> None:
        main = ROOT_TEX.replace("body\n", "\\input{part}\nbody\n")
        with tempfile.TemporaryDirectory() as tmp:
            source = make_source(tmp, {"main.tex": main, "part.tex": "part\n"})
            manuscript = self.manuscript(resolve_tex_graph(source))
            (source / "main.tex").write_text(ROOT_TEX, encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError, "included TeX graph changed after preparation"
            ):
                resolve_frozen_tex_graph(source, manuscript)

    def test_frozen_graph_rejects_invalid_manifest_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = make_source(tmp, {"main.tex": ROOT_TEX})
            with self.assertRaisesRegex(ValueError, "root is missing"):
                resolve_frozen_tex_graph(source, {"root": "", "included": [], "files": {}})
            with self.assertRaisesRegex(ValueError, "included-file list is invalid"):
                resolve_frozen_tex_graph(
                    source, {"root": "main.tex", "included": "main.tex", "files": {}}
                )
            with self.assertRaisesRegex(ValueError, "file map is invalid"):
                resolve_frozen_tex_graph(
                    source, {"root": "main.tex", "included": ["main.tex"], "files": []}
                )

    def test_frozen_root_must_still_be_a_real_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = make_source(
                tmp, {"main.tex": ROOT_TEX, "other.tex": ROOT_TEX}
            )
            manuscript = {
                "root": "other.tex",
                "included": ["other.tex"],
                "files": {"other.tex": {"sha256": "0" * 64}},
            }
            # A stale root that vanished from the source fails closed rather
            # than silently re-inferring a different manuscript.
            (source / "other.tex").unlink()
            with self.assertRaisesRegex(
                ValueError, "prepared root 'other.tex' resolved as 'main.tex'"
            ):
                resolve_frozen_tex_graph(source, manuscript)


if __name__ == "__main__":
    unittest.main()
