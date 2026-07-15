from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from stella.benchmark.agentic_run import (
    build_agentic_system_prompt,
)
from stella.benchmark.extraction_review import (
    build_agentic_reviewer_system_prompt,
    build_workflow_reviewer_system_prompt,
    review_task_prompt,
)
from stella.benchmark.extraction_run import build_system_prompt
from stella.benchmark.task_surfaces import (
    CORE_PROV,
    ENRICHMENT_FIELDS,
    FULL,
    TASK_SURFACE_IDS,
    get_task_surface,
    hydrate_surface_document,
    task_surface_schema_view,
    task_surface_sha256,
    validate_surface_document,
)
from stella.benchmark.run_contract import build_method_fingerprint
from stella.lit.schema_docs import generated_schema_docs
from stella.lit.schema_templates import empty_candidate_enrichment
from tests.test_hvs_candidates_validation import valid_payload, validate_cli


ROOT = Path(__file__).resolve().parents[1]


class ExtractionTaskSurfaceTest(unittest.TestCase):
    def test_registry_ids_fields_defaults_and_hashes_are_stable(self) -> None:
        self.assertEqual(TASK_SURFACE_IDS, (FULL, CORE_PROV))
        self.assertEqual(tuple(empty_candidate_enrichment()), ENRICHMENT_FIELDS)
        self.assertTrue(set(ENRICHMENT_FIELDS).issubset(get_task_surface(FULL).candidate_fields))
        self.assertTrue(set(ENRICHMENT_FIELDS).isdisjoint(get_task_surface(CORE_PROV).candidate_fields))
        first = task_surface_sha256(ROOT, CORE_PROV)
        self.assertEqual(first, task_surface_sha256(ROOT, CORE_PROV))
        self.assertNotEqual(first, task_surface_sha256(ROOT, FULL))

    def test_core_schema_is_generated_shorter_and_omits_enrichment_types(self) -> None:
        generated = generated_schema_docs()
        path = Path(
            "skills/hvs-candidates-extraction/references/schema-core-provenance.md"
        )
        self.assertIn(path, generated)
        core = task_surface_schema_view(ROOT, CORE_PROV)
        full = task_surface_schema_view(ROOT, FULL)
        self.assertLess(len(core), len(full) * 0.75)
        for model_name in (
            "PhotometryRecord",
            "SpectroscopyRecord",
            "StellarParameters",
            "AbundanceRecord",
            "QualityFlagRecord",
            "OrbitRecord",
            "AstrophysicalOrigin",
        ):
            self.assertNotIn(model_name, core)

    def test_default_prompts_equal_explicit_full_and_core_is_shorter(self) -> None:
        self.assertEqual(build_system_prompt(ROOT), build_system_prompt(ROOT, FULL))
        self.assertEqual(
            build_agentic_system_prompt(ROOT),
            build_agentic_system_prompt(ROOT, FULL),
        )
        self.assertLess(
            len(build_system_prompt(ROOT, CORE_PROV)),
            len(build_system_prompt(ROOT, FULL)),
        )
        self.assertLess(
            len(build_agentic_system_prompt(ROOT, CORE_PROV)),
            len(build_agentic_system_prompt(ROOT, FULL)),
        )

    def test_surface_changes_fingerprint_but_repeats_do_not(self) -> None:
        full_method = {"parameters": {"task_surface": FULL, "task_surface_sha256": task_surface_sha256(ROOT, FULL)}}
        core_method = {"parameters": {"task_surface": CORE_PROV, "task_surface_sha256": task_surface_sha256(ROOT, CORE_PROV)}}
        self.assertNotEqual(
            build_method_fingerprint(full_method),
            build_method_fingerprint(core_method),
        )
        self.assertEqual(
            build_method_fingerprint(core_method),
            build_method_fingerprint(copy.deepcopy(core_method)),
        )

    def test_core_reviewer_does_not_treat_enrichment_as_missing(self) -> None:
        task = review_task_prompt({"candidates": []}, CORE_PROV)
        for system in (
            build_workflow_reviewer_system_prompt(ROOT, CORE_PROV),
            build_agentic_reviewer_system_prompt(ROOT, CORE_PROV),
        ):
            self.assertIn("Do not challenge their absence", system)
        self.assertIn("absence is not an error", task)

    def test_hydrated_core_passes_surface_and_frozen_complete_validator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            document = valid_payload(workspace)
            candidate = document["candidates"][0]
            for field in ENRICHMENT_FIELDS:
                candidate.pop(field)
            hydrate_surface_document(document, CORE_PROV)
            self.assertEqual(validate_surface_document(document, CORE_PROV), [])
            report = validate_cli.validate_hvs_candidates_report(
                document, workspace=workspace, require_complete=True
            )
            self.assertEqual(report.errors, [])

    def test_nonempty_core_enrichment_is_rejected_but_full_is_noop(self) -> None:
        document = {"candidates": [copy.deepcopy(empty_candidate_enrichment())]}
        document["candidates"][0]["photometry"] = [{"synthetic": True}]
        self.assertTrue(validate_surface_document(document, CORE_PROV))
        self.assertEqual(validate_surface_document(document, FULL), [])


if __name__ == "__main__":
    unittest.main()
