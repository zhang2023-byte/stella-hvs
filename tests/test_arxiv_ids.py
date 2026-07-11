from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stella.lit.arxiv_ids import (
    parse_arxiv_id_list,
    validate_arxiv_id,
    validate_unversioned_arxiv_id,
)
from stella.lit.literature_assets import resolve_folder


class ArxivIdTest(unittest.TestCase):
    def test_accepts_modern_ids_and_optional_versions(self) -> None:
        self.assertEqual(validate_arxiv_id("2401.10635v2"), "2401.10635v2")
        self.assertEqual(validate_unversioned_arxiv_id("2401.10635"), "2401.10635")
        self.assertEqual(
            parse_arxiv_id_list("2401.10635,2507.07558v1"),
            ["2401.10635", "2507.07558v1"],
        )

    def test_rejects_path_segments_and_versions_where_forbidden(self) -> None:
        for value in ("../escape", "2401.10635/../../x", "", "astro-ph/1234"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_arxiv_id(value)
        with self.assertRaises(ValueError):
            validate_unversioned_arxiv_id("2401.10635v2")

    def test_literature_folder_resolution_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                resolve_folder(Path(tmp), "../escape")


if __name__ == "__main__":
    unittest.main()
