"""Mechanical truth checks for the two workflow catalogs.

The catalogs are executable contracts: every callable, model, validator,
contract path, and test path they declare must resolve or exist in this
repository, and no retired execution surface may be referenced. A broken
declaration fails here before it can mislead an agent at run time.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from pydantic import BaseModel

from stella.workflows import (
    DEFAULT_ROOT,
    load_operation_catalog,
    load_workflow_catalog,
    resolve_reference,
)

RETIRED_FRAGMENTS = (
    "scripts/",
    "skills/",
    "hvs_extraction",
    "hvs_contribution_extraction",
    "workflows/definitions",
)


def _resolve_or_none(reference: str) -> object | None:
    try:
        return resolve_reference(reference)
    except Exception:  # noqa: BLE001 - collected as a broken reference
        return None


class OperationCatalogIntegrityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_operation_catalog(DEFAULT_ROOT)
        cls.workflows = load_workflow_catalog(DEFAULT_ROOT)
        cls.root = Path(DEFAULT_ROOT)

    def test_every_callable_resolves_to_a_callable(self) -> None:
        broken: list[str] = []
        for operation in self.catalog.operations:
            obj = _resolve_or_none(operation.callable)
            if obj is None:
                broken.append(f"{operation.id}: {operation.callable} (unresolvable)")
            elif not callable(obj):
                broken.append(f"{operation.id}: {operation.callable} (not callable)")
        self.assertEqual([], broken)

    def test_every_model_reference_resolves_to_a_pydantic_model(self) -> None:
        broken: list[str] = []
        for operation in self.catalog.operations:
            for field in ("input_model", "output_model"):
                reference = getattr(operation, field)
                if reference is None:
                    broken.append(f"{operation.id}: {field} is not declared")
                    continue
                obj = _resolve_or_none(reference)
                if obj is None:
                    broken.append(f"{operation.id}: {field} {reference} (unresolvable)")
                elif not (isinstance(obj, type) and issubclass(obj, BaseModel)):
                    broken.append(
                        f"{operation.id}: {field} {reference} (not a pydantic model)"
                    )
        self.assertEqual([], broken)

    def test_every_validator_resolves_to_a_callable(self) -> None:
        broken: list[str] = []
        for operation in self.catalog.operations:
            if not operation.validators:
                broken.append(f"{operation.id}: declares no validator")
                continue
            for reference in operation.validators:
                obj = _resolve_or_none(reference)
                if obj is None:
                    broken.append(f"{operation.id}: {reference} (unresolvable)")
                elif not callable(obj):
                    broken.append(f"{operation.id}: {reference} (not callable)")
        self.assertEqual([], broken)

    def test_every_declared_contract_path_exists(self) -> None:
        broken: list[str] = []
        for operation in self.catalog.operations:
            for contract in operation.contracts:
                if not (self.root / contract).exists():
                    broken.append(f"{operation.id}: {contract}")
        self.assertEqual([], broken)

    def test_every_declared_test_path_exists(self) -> None:
        broken: list[str] = []
        for operation in self.catalog.operations:
            for test in operation.tests:
                if not (self.root / test).exists():
                    broken.append(f"{operation.id}: {test}")
        self.assertEqual([], broken)

    def test_workflow_operation_ids_exist_and_are_unique(self) -> None:
        by_id = self.catalog.by_id
        broken: list[str] = []
        for workflow in self.workflows.workflows:
            seen: set[str] = set()
            for operation_id in workflow.operation_ids:
                if operation_id not in by_id:
                    broken.append(f"{workflow.id}: unknown operation {operation_id}")
                if operation_id in seen:
                    broken.append(
                        f"{workflow.id}: operation {operation_id} declared twice"
                    )
                seen.add(operation_id)
        self.assertEqual([], broken)

    def test_no_retired_execution_surface_is_referenced(self) -> None:
        texts = [
            (self.root / "workflows" / "operations.yaml").read_text(encoding="utf-8"),
            (self.root / "workflows" / "stella_workflows.yaml").read_text(
                encoding="utf-8"
            ),
        ]
        for operation in self.catalog.operations:
            for field in (
                operation.callable,
                operation.input_model,
                operation.output_model,
                *operation.validators,
                *operation.contracts,
                *operation.tests,
                *operation.reads,
                *operation.writes,
            ):
                if field and any(fragment in field for fragment in RETIRED_FRAGMENTS):
                    texts.append(f"{operation.id}: {field}")
        broken = [line for line in texts if any(f in line for f in RETIRED_FRAGMENTS)]
        self.assertEqual([], broken)


if __name__ == "__main__":
    unittest.main()
