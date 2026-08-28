"""Benchmark planning: plan and run must demand the same authorities.

An ordinary extraction-only benchmark request must not demand Gold or
scoring authority; optional phases join only when explicitly requested.
"""

from __future__ import annotations

import unittest

from stella.workflows import (
    Authorities,
    BenchmarkRequest,
    DEFAULT_ROOT,
    GoldAnnotationRequest,
    LiteraturePipelineRequest,
)
from stella.workflow_runtime import effective_phases, plan_workflow
from stella.workflows import get_workflow


def _phase_ids(phases: list) -> list[str]:
    return [phase.id for phase in phases]


class BenchmarkPlanningTest(unittest.TestCase):
    def test_default_plan_excludes_optional_score_and_resume(self) -> None:
        request = BenchmarkRequest(authorities=Authorities(execute=True))
        phases = effective_phases(get_workflow("benchmark"), request)
        self.assertEqual(
            _phase_ids(phases), ["prepare", "freeze", "run", "finalize"]
        )

    def test_default_plan_needs_no_gold_or_scoring_authority(self) -> None:
        request = BenchmarkRequest(authorities=Authorities(execute=True))
        plan = plan_workflow(
            root=DEFAULT_ROOT, workflow_id="benchmark", request=request
        )
        self.assertIn("llm", plan["required_authorities"])
        self.assertIn("network", plan["required_authorities"])
        self.assertNotIn("gold_private", plan["required_authorities"])
        self.assertNotIn("scoring", plan["required_authorities"])

    def test_preparation_only_request_needs_no_llm_or_network(self) -> None:
        request = BenchmarkRequest(
            authorities=Authorities(execute=True),
            phases=["prepare", "freeze"],
        )
        plan = plan_workflow(
            root=DEFAULT_ROOT, workflow_id="benchmark", request=request
        )
        self.assertEqual(plan["required_authorities"], [])
        self.assertEqual(
            [phase["id"] for phase in plan["phases"]], ["prepare", "freeze"]
        )

    def test_score_phase_adds_gold_and_scoring_authorities(self) -> None:
        request = BenchmarkRequest(
            authorities=Authorities(execute=True), phases=["score"]
        )
        plan = plan_workflow(
            root=DEFAULT_ROOT, workflow_id="benchmark", request=request
        )
        self.assertIn("gold_private", plan["required_authorities"])
        self.assertIn("scoring", plan["required_authorities"])
        self.assertEqual(
            [phase["id"] for phase in plan["phases"]], ["score"]
        )

    def test_dev10_plan_resolves_papers_and_named_gold_selection(self) -> None:
        request = BenchmarkRequest(phases=["prepare", "freeze", "score"])

        plan = plan_workflow(
            root=DEFAULT_ROOT, workflow_id="benchmark", request=request
        )

        self.assertEqual(len(plan["papers"]), 10)
        self.assertEqual(
            plan["resolved_inputs"]["selection_id"],
            "contribution-dev-primary-v1",
        )
        selection_checks = [
            check
            for check in plan["preflight_checks"]
            if "gold_selections" in check["read"]
        ]
        self.assertEqual(len(selection_checks), 1)
        self.assertNotEqual(selection_checks[0]["status"], "unresolved")

    def test_explicit_phases_reject_unknown_ids(self) -> None:
        request = BenchmarkRequest(phases=["nonexistent"])
        with self.assertRaises(Exception) as ctx:
            plan_workflow(
                root=DEFAULT_ROOT, workflow_id="benchmark", request=request
            )
        self.assertIn("nonexistent", str(ctx.exception))


class LiteraturePlanningTest(unittest.TestCase):
    def test_optional_dynamics_and_site_are_excluded_by_default(self) -> None:
        request = LiteraturePipelineRequest(papers=["2601.08888"])
        phases = effective_phases(get_workflow("literature_pipeline"), request)
        self.assertNotIn("dynamics", _phase_ids(phases))
        self.assertNotIn("site", _phase_ids(phases))

    def test_requested_optional_phases_join_the_plan(self) -> None:
        request = LiteraturePipelineRequest(
            papers=["2601.08888"], phases=["dynamics"]
        )
        phases = effective_phases(get_workflow("literature_pipeline"), request)
        self.assertEqual(_phase_ids(phases), ["dynamics"])


class GoldActionPlanningTest(unittest.TestCase):
    def test_queue_action_selects_only_the_queue_phase(self) -> None:
        request = GoldAnnotationRequest(
            expert="expert-a", papers=["2601.08888"], action="queue"
        )
        phases = effective_phases(get_workflow("gold_annotation"), request)
        self.assertEqual(_phase_ids(phases), ["queue"])

    def test_open_action_selects_only_the_annotate_phase(self) -> None:
        request = GoldAnnotationRequest(
            expert="expert-a", papers=["2601.08888"], action="open"
        )
        phases = effective_phases(get_workflow("gold_annotation"), request)
        self.assertEqual(_phase_ids(phases), ["annotate"])

    def test_save_action_selects_only_the_save_phase(self) -> None:
        request = GoldAnnotationRequest(
            expert="expert-a", papers=["2601.08888"], action="save"
        )
        phases = effective_phases(get_workflow("gold_annotation"), request)
        self.assertEqual(_phase_ids(phases), ["save"])

    def test_save_request_carries_exact_legacy_preservation_pins(self) -> None:
        request = GoldAnnotationRequest(
            expert="expert-a",
            papers=["2601.08888"],
            action="save",
            legacy_selection_id="evaluation-dev-primary-v1",
            legacy_preservation_ref="v6-baseline",
        )
        self.assertEqual(
            request.legacy_selection_id, "evaluation-dev-primary-v1"
        )
        self.assertEqual(request.legacy_preservation_ref, "v6-baseline")

    def test_save_request_carries_exact_contribution_revision_pins(self) -> None:
        request = GoldAnnotationRequest(
            expert="expert-a",
            papers=["2601.08888"],
            action="save",
            base_selection_id="contribution-dev-primary-v1",
            expected_current_sha256="a" * 64,
        )

        self.assertEqual(
            request.base_selection_id, "contribution-dev-primary-v1"
        )
        self.assertEqual(request.expected_current_sha256, "a" * 64)
        plan = plan_workflow(
            root=DEFAULT_ROOT,
            workflow_id="gold_annotation",
            request=request,
        )
        self.assertIn("supersede", plan["conditional_authorities"])
        self.assertEqual(
            plan["resolved_inputs"]["base_selection_id"],
            "contribution-dev-primary-v1",
        )
        base_checks = [
            check
            for check in plan["preflight_checks"]
            if "contribution-dev-primary-v1" in check["read"]
        ]
        self.assertEqual(len(base_checks), 1)
        self.assertIn(base_checks[0]["status"], {"present", "absent"})

    def test_save_request_carries_explicit_migration_work_retention(self) -> None:
        request = GoldAnnotationRequest(
            expert="expert-a",
            papers=["2601.08888"],
            action="save",
            retain_migration_work=True,
        )

        self.assertTrue(request.retain_migration_work)

    def test_selection_action_selects_only_the_selection_phase(self) -> None:
        request = GoldAnnotationRequest(
            expert="expert-a", papers=["2601.08888"], action="selection"
        )
        phases = effective_phases(get_workflow("gold_annotation"), request)
        self.assertEqual(_phase_ids(phases), ["selection"])

    def test_explicit_phases_override_the_action_default(self) -> None:
        request = GoldAnnotationRequest(
            expert="expert-a",
            papers=["2601.08888"],
            action="queue",
            phases=["validate"],
        )
        phases = effective_phases(get_workflow("gold_annotation"), request)
        self.assertEqual(_phase_ids(phases), ["validate"])


if __name__ == "__main__":
    unittest.main()
