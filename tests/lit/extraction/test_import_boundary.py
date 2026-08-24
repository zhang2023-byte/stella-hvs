"""Import-boundary tests for the contribution extractor under lit.

The contribution extractor is a first-class ``lit`` citizen: it may import
the standard library, third-party libraries, other ``lit`` modules, and root
infrastructure -- never ``benchmark``, ``dyn``, ``web``, or either retired
top-level extraction package.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src" / "stella"
EXTRACTION = SRC / "lit" / "extraction"

FORBIDDEN_PREFIXES = (
    "stella.benchmark",
    "stella.dyn",
    "stella.web",
    "stella.hvs_extraction",
    "stella.hvs_contribution_extraction",
)


def _imported_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module)
    return roots


class LitExtractionBoundaryTest(unittest.TestCase):
    def test_extraction_package_exists(self) -> None:
        self.assertTrue(EXTRACTION.is_dir())
        modules = sorted(path.name for path in EXTRACTION.glob("*.py"))
        self.assertIn("roster_stage.py", modules)
        self.assertIn("quantity_stage.py", modules)

    def test_extraction_never_imports_business_neighbors(self) -> None:
        for path in sorted(EXTRACTION.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            roots = _imported_roots(tree)
            violations = sorted(
                root
                for root in roots
                for prefix in FORBIDDEN_PREFIXES
                if root == prefix or root.startswith(prefix + ".")
            )
            self.assertEqual(
                violations,
                [],
                f"{path.name} imports forbidden packages: {violations}",
            )

    def test_no_maintained_import_of_the_retired_contribution_package(self) -> None:
        offenders: list[str] = []
        for directory in (SRC, ROOT / "tests"):
            for path in sorted(directory.rglob("*.py")):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                roots = _imported_roots(tree)
                if any(
                    root == "stella.hvs_contribution_extraction"
                    or root.startswith("stella.hvs_contribution_extraction.")
                    for root in roots
                ):
                    offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
