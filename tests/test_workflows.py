"""Tests for the two-catalog workflow/operation registry."""

from __future__ import annotations

import importlib
import unittest
from pathlib import Path

from stella.workflows import (
    AUTHORITY_KINDS,
    load_operation_catalog,
    load_workflow_catalog,
)

ROOT = Path(__file__).resolve().parents[1]

PRODUCT_WORKFLOW_IDS = ["literature_pipeline", "gold_annotation", "benchmark"]

REQUIRED_OPERATION_IDS = {
    "literature.fetch",
    "literature.archive_assets",
    "literature.assess_catalog",
    "literature.review_catalog",
    "literature.extract_catalog",
    "literature.extract_contributions",
    "literature.build_contribution_index",
    "literature.build_object_timelines",
    "literature.repair_ads_metadata",
    "dynamics.validate_input_selection",
    "dynamics.calculate",
    "web.build_contribution_site",
    "gold.list_queue",
    "gold.open_annotation",
    "gold.validate_annotation",
    "gold.save_annotation",
    "gold.prepare_selection",
    "gold.migrate_original50_contributions",
    "benchmark.prepare_campaign",
    "benchmark.freeze_method",
    "benchmark.execute",
    "benchmark.resume",
    "benchmark.finalize",
    "benchmark.score",
    "benchmark.emit_scorecard",
}


class WorkflowCatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_workflow_catalog(ROOT)
        cls.operations = load_operation_catalog(ROOT)
        cls.by_id = {spec.id: spec for spec in cls.catalog.workflows}

    def test_catalog_contains_exactly_three_products(self) -> None:
        self.assertEqual(
            sorted(spec.id for spec in self.catalog.workflows),
            sorted(PRODUCT_WORKFLOW_IDS),
        )

    def test_no_batch_workflows_are_public(self) -> None:
        for spec in self.catalog.workflows:
            self.assertNotIn("_batch", spec.id)

    def test_every_workflow_declares_the_required_contract_fields(self) -> None:
        for spec in self.catalog.workflows:
            with self.subTest(workflow=spec.id):
                self.assertTrue(spec.human_intents)
                self.assertTrue(spec.phases)
                self.assertEqual(spec.default_behavior, "plan")
                self.assertTrue(spec.authority_gates)
                self.assertIn(spec.failure_policy, ("complete", "partial"))
                for gate in spec.authority_gates:
                    self.assertIn(gate, AUTHORITY_KINDS)
                for phase in spec.phases:
                    self.assertTrue(phase.operations)
                    for operation_id in phase.operations:
                        self.assertIn(operation_id, self.operations.by_id)

    def test_literature_pipeline_phase_order(self) -> None:
        spec = self.by_id["literature_pipeline"]
        phase_ids = [phase.id for phase in spec.phases]
        self.assertLess(phase_ids.index("discover_fetch"), phase_ids.index("archive"))
        self.assertLess(phase_ids.index("archive"), phase_ids.index("catalog"))
        self.assertLess(
            phase_ids.index("catalog"), phase_ids.index("contributions")
        )
        self.assertLess(
            phase_ids.index("contributions"), phase_ids.index("indexes")
        )
        self.assertLess(phase_ids.index("indexes"), phase_ids.index("dynamics"))
        self.assertLess(phase_ids.index("dynamics"), phase_ids.index("site"))

    def test_input_model_references_resolve_to_request_models(self) -> None:
        for spec in self.catalog.workflows:
            with self.subTest(workflow=spec.id):
                model = _resolve_reference(spec.input_model)
                self.assertTrue(hasattr(model, "model_validate"))

    def test_failure_policies(self) -> None:
        self.assertEqual(self.by_id["literature_pipeline"].failure_policy, "partial")
        self.assertEqual(self.by_id["gold_annotation"].failure_policy, "complete")
        self.assertEqual(self.by_id["benchmark"].failure_policy, "partial")

    def test_gold_migration_declares_conditional_supersede_gate(self) -> None:
        gates = self.by_id["gold_annotation"].authority_gates
        self.assertIn("gold_private", gates)
        self.assertIn("supersede", gates)


class OperationCatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_operation_catalog(ROOT)
        cls.by_id = {spec.id: spec for spec in cls.catalog.operations}

    def test_required_operation_ids_are_present(self) -> None:
        self.assertTrue(REQUIRED_OPERATION_IDS.issubset(self.by_id))

    def test_operation_callables_are_owner_scoped_references(self) -> None:
        for spec in self.catalog.operations:
            with self.subTest(operation=spec.id):
                module_name, _, attribute = spec.callable.partition(":")
                self.assertTrue(module_name and attribute)
                self.assertTrue(
                    module_name == spec.owner or module_name.startswith(spec.owner + "."),
                    f"{spec.id}: callable {spec.callable} escapes owner {spec.owner}",
                )
                for reference in (spec.input_model, spec.output_model):
                    if reference is not None:
                        ref_module, _, ref_attr = reference.partition(":")
                        self.assertTrue(ref_module and ref_attr)

    def test_operation_authorities_are_known_kinds(self) -> None:
        for spec in self.catalog.operations:
            for authority in spec.authorities:
                self.assertIn(authority, AUTHORITY_KINDS)

    def test_operations_declare_isolation_and_retry(self) -> None:
        for spec in self.catalog.operations:
            with self.subTest(operation=spec.id):
                self.assertIn(
                    spec.per_paper, ("worker_per_paper", "workflow_scoped")
                )
                self.assertIn(
                    spec.retry_classification, ("network_retryable", "terminal")
                )

    def test_per_paper_operations_declare_paper_scoped_paths(self) -> None:
        for spec in self.catalog.operations:
            if spec.per_paper == "worker_per_paper":
                with self.subTest(operation=spec.id):
                    self.assertTrue(spec.reads or spec.writes)

    def test_gold_save_catalog_declares_legacy_archive_transaction(self) -> None:
        operation = self.by_id["gold.save_annotation"]
        self.assertIn(
            "benchmark/campaigns/<campaign_id>/manifest/gold_selections/<selection_id>.json",
            operation.reads,
        )
        self.assertIn(
            "<private-gold-repo>/legacy-v6/<paper_id>/annotation_<expert>_old.json",
            operation.writes,
        )
        self.assertIn("supersede", operation.risk)

    def test_gold_save_catalog_declares_contribution_revision_transaction(self) -> None:
        operation = self.by_id["gold.save_annotation"]

        self.assertFalse(
            any("base_selection_id" in path for path in operation.reads)
        )
        self.assertFalse(
            any("contribution-history" in path for path in operation.writes)
        )
        self.assertIn(
            "<gold-work-root>/<paper_id>/locks/revision_<expert>.previous.json",
            operation.writes,
        )
        self.assertIn("retained migration audit", operation.risk)
        self.assertIn("expected current SHA", operation.risk)
        self.assertIn("private Git HEAD", operation.risk)

    def test_benchmark_score_catalog_keeps_private_details_beside_gold(self) -> None:
        operation = self.by_id["benchmark.score"]

        self.assertFalse(
            any("contribution-history" in path for path in operation.reads)
        )
        self.assertIn(
            "<private-gold-repo>/scoring-details/",
            operation.writes,
        )
        self.assertNotIn(
            "<private-gold-root>/scoring_details/",
            operation.writes,
        )


def _resolve_reference(reference: str):
    module_name, _, attribute = reference.partition(":")
    module = importlib.import_module(module_name)
    return getattr(module, attribute)


if __name__ == "__main__":
    unittest.main()
