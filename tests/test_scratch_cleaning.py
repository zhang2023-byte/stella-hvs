"""Minimal TeX cleaning contract tests (D006)."""

from __future__ import annotations

import unittest

from stella.benchmark.scratch.cleaning import (
    render_file_block,
    render_manuscript_view,
    strip_tex_comments,
)


class StripTexCommentsTest(unittest.TestCase):
    def test_strips_unescaped_comment_and_preserves_line_count(self) -> None:
        text = "first % gone\nsecond\n% whole line\nfourth \\% kept\n"
        cleaned = strip_tex_comments(text)
        self.assertEqual(
            cleaned, "first \nsecond\n\nfourth \\% kept\n"
        )
        self.assertEqual(len(cleaned.split("\n")), len(text.split("\n")))

    def test_escaped_percent_and_double_backslash(self) -> None:
        self.assertEqual(strip_tex_comments("100\\% sure % cut"), "100\\% sure ")
        # An even number of preceding backslashes means the % is a comment.
        self.assertEqual(strip_tex_comments("\\\\% cut"), "\\\\")

    def test_verbatim_environment_is_not_stripped(self) -> None:
        text = (
            "before % cut\n"
            "\\begin{verbatim}\n"
            "100 % literal\n"
            "\\end{verbatim}\n"
            "after % cut\n"
        )
        self.assertEqual(
            strip_tex_comments(text),
            "before \n"
            "\\begin{verbatim}\n"
            "100 % literal\n"
            "\\end{verbatim}\n"
            "after \n",
        )

    def test_inline_verb_protects_percent(self) -> None:
        self.assertEqual(
            strip_tex_comments("use \\verb|%| here % cut"),
            "use \\verb|%| here ",
        )
        self.assertEqual(
            strip_tex_comments("use \\verb*|%| here % cut"),
            "use \\verb*|%| here ",
        )


class RenderViewTest(unittest.TestCase):
    def test_file_block_uses_named_markers_and_line_prefixes(self) -> None:
        block = render_file_block("main.tex", "alpha\n\nbeta\n")
        self.assertEqual(
            block,
            "===== BEGIN FILE: main.tex =====\n"
            "1|alpha\n"
            "2|\n"
            "3|beta\n"
            "===== END FILE: main.tex =====",
        )

    def test_manuscript_view_joins_blocks_in_order(self) -> None:
        view = render_manuscript_view(
            [("main.tex", "one\n"), ("sections/a.tex", "two\n")]
        )
        self.assertTrue(view.endswith("\n"))
        self.assertLess(view.index("BEGIN FILE: main.tex"), view.index("BEGIN FILE: sections/a.tex"))
        self.assertIn("1|one", view)
        self.assertIn("1|two", view)


if __name__ == "__main__":
    unittest.main()
