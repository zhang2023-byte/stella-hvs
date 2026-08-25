"""Mechanical architecture enforcement: dependency graph, package topology,
workflow routing, retired-surface absence, and the offline network tripwire
contract for end-to-end tests."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "stella"

BUSINESS_PACKAGES = ("benchmark", "dyn", "lit", "web")
ROOT_INFRASTRUCTURE_FILES = {
    "__init__.py",
    "__main__.py",
    "cli.py",
    "schema_registry.py",
    "workflow_runtime.py",
    "workflows.py",
}

# Allowed business dependency direction (plan section 2.2):
#   benchmark -> lit ; dyn -> lit ; web -> lit ; web -> dyn
ALLOWED_CROSS_PACKAGE_IMPORTS = {
    "benchmark": {"lit"},
    "dyn": {"lit"},
    "web": {"lit", "dyn"},
    "lit": set(),
}


def _import_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.level == 0:
                roots.add(node.module)
    return roots


class BusinessDependencyGraphTest(unittest.TestCase):
    def test_business_packages_follow_the_approved_direction(self) -> None:
        for package in BUSINESS_PACKAGES:
            allowed = ALLOWED_CROSS_PACKAGE_IMPORTS[package]
            for path in sorted((SRC / package).rglob("*.py")):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for root in _import_roots(tree):
                    if not root.startswith("stella"):
                        continue
                    parts = root.split(".")
                    if len(parts) < 2 or parts[1] not in BUSINESS_PACKAGES:
                        continue
                    target = parts[1]
                    if target == package:
                        continue
                    self.assertIn(
                        target,
                        allowed,
                        f"{path.relative_to(ROOT)} imports stella.{target}; "
                        f"{package} may only depend on {sorted(allowed) or 'nothing'}",
                    )

    def test_retired_extraction_packages_are_never_imported(self) -> None:
        for path in sorted(SRC.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for root in _import_roots(tree):
                self.assertFalse(
                    root.startswith("stella.hvs_extraction"),
                    f"{path}: retired import {root}",
                )
                self.assertFalse(
                    root.startswith("stella.hvs_contribution_extraction"),
                    f"{path}: retired import {root}",
                )


class SourceTopologyTest(unittest.TestCase):
    def test_only_four_business_packages_and_root_infrastructure_exist(self) -> None:
        entries = {
            entry.name
            for entry in SRC.iterdir()
            if entry.name != "__pycache__"
        }
        directories = {
            name for name in entries if (SRC / name).is_dir()
        }
        files = entries - directories
        self.assertEqual(
            directories, set(BUSINESS_PACKAGES), f"unexpected directories: {directories}"
        )
        self.assertEqual(
            files,
            ROOT_INFRASTRUCTURE_FILES,
            f"unexpected root files: {files ^ ROOT_INFRASTRUCTURE_FILES}",
        )


class WorkflowRoutingTest(unittest.TestCase):
    def test_workflows_directory_has_exactly_two_catalogs(self) -> None:
        entries = sorted(
            path.name for path in (ROOT / "workflows").iterdir()
        )
        self.assertEqual(entries, ["operations.yaml", "stella_workflows.yaml"])


class RetiredSurfaceAbsenceTest(unittest.TestCase):
    def test_retired_directories_are_absent(self) -> None:
        for relative in ("scripts", "skills", "workflows/definitions"):
            self.assertFalse(
                (ROOT / relative).exists(),
                f"retired surface still exists: {relative}",
            )

    def test_public_catalog_has_no_batch_workflows(self) -> None:
        from stella.workflows import load_workflow_catalog

        catalog = load_workflow_catalog(ROOT)
        for spec in catalog.workflows:
            self.assertNotIn("_batch", spec.id)

    def test_active_gold_form_writes_no_yaml_twin(self) -> None:
        # The approved storage contract is one JSON annotation per paper
        # and expert; the active save path must never write YAML.
        source = (
            ROOT
            / "src/stella/benchmark/hvs_contribution_gold_form.py"
        ).read_text(encoding="utf-8")
        save_start = source.index("def save_expert_annotation(")
        save_end = source.index("\n\ndef ", save_start)
        save_body = source[save_start:save_end]
        self.assertNotIn(
            ".yaml", save_body, "the active gold save must be JSON-only"
        )

    def test_no_compat_shims_or_retired_terms_in_active_routing(self) -> None:
        from stella.workflows import load_workflow_catalog

        catalog_text = "\n".join(
            spec.id for spec in load_workflow_catalog(ROOT).workflows
        )
        for term in (
            "hvs_candidate_extraction",
            "stella_refresh",
            "LangGraph",
            "coding_agent_baseline",
            "network_debug",
        ):
            self.assertNotIn(term, catalog_text)


if __name__ == "__main__":
    unittest.main()
