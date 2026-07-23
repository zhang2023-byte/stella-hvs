"""Guard the scratch engineering baseline: registry entries, config gate, Git boundary."""

from __future__ import annotations

import unittest
from pathlib import Path

from stella.schema_registry import REGISTRY, schema_ref
from stella.benchmark.scratch.method_config import (
    ScratchComponentHashes,
    ScratchContextBudget,
    ScratchMethodConfig,
    ScratchModelRoute,
    new_scratch_method_config,
)


ROOT = Path(__file__).resolve().parents[1]

SCRATCH_SCHEMAS = (
    "benchmark.hvs_extraction_scratch.run_config",
    "benchmark.hvs_extraction_scratch.prepared_input",
    "benchmark.hvs_extraction_scratch.roster_proposal",
    "benchmark.hvs_extraction_scratch.roster_final",
    "benchmark.hvs_extraction_scratch.candidate_fields",
    "benchmark.hvs_extraction_scratch.paper_result",
    "benchmark.hvs_extraction_scratch.run_summary",
)


def frozen_route(**overrides: object) -> ScratchModelRoute:
    values = {
        "provider": "deepseek",
        "model": "deepseek-v4-pro",
        "structured_output_mode": "tool_submission",
        "temperature": 0.2,
        "top_p": 1.0,
        "seed_honored": True,
    }
    values.update(overrides)
    return ScratchModelRoute(**values)


def frozen_budget() -> ScratchContextBudget:
    return ScratchContextBudget(
        model_context_limit=128000,
        reserve_system_and_rules=8000,
        reserve_tool_schema=4000,
        reserve_candidate_suffix=2000,
        reserve_output=8000,
        reserve_provider_framing=1000,
    )


def frozen_config() -> ScratchMethodConfig:
    return ScratchMethodConfig(
        roster_extractor=frozen_route(),
        roster_adjudicator=frozen_route(provider="bigmodel", model="glm-5.2", temperature=0.0),
        field_extractor=frozen_route(),
        roster_extractor_seeds=(101, 202, 303),
        roster_context_budget=frozen_budget(),
        field_context_budget=frozen_budget(),
        components=ScratchComponentHashes(
            rule_profile_sha256={"hvs_roster_scratch": "a" * 64},
            prompt_template_sha256={"roster_extractor": "b" * 64},
            submission_schema_sha256={"submit_candidate_roster": "c" * 64},
        ),
    )


class ScratchSchemaRegistryTest(unittest.TestCase):
    def test_scratch_schemas_are_registered_transient_v1(self) -> None:
        for name in SCRATCH_SCHEMAS:
            with self.subTest(name=name):
                entry = REGISTRY[name]
                self.assertEqual(entry.current_version, 1)
                self.assertEqual(entry.readable_versions, (1,))
                self.assertEqual(entry.lifecycle, "transient")
                self.assertEqual(schema_ref(name), {"name": name, "version": 1})


class ScratchMethodConfigTest(unittest.TestCase):
    def test_placeholder_config_cannot_freeze(self) -> None:
        config = new_scratch_method_config()
        missing = config.unfrozen_fields()
        self.assertIn("roster_extractor.model", missing)
        self.assertIn("roster_context_budget", missing)
        self.assertIn("components.rule_profile_sha256", missing)
        with self.assertRaisesRegex(ValueError, "not frozen"):
            config.assert_frozen()

    def test_frozen_config_passes_and_fingerprint_is_stable(self) -> None:
        config = frozen_config()
        config.assert_frozen()
        self.assertEqual(config.unfrozen_fields(), [])
        self.assertEqual(config.method_fingerprint(), frozen_config().method_fingerprint())
        changed = frozen_config().model_copy(
            update={"roster_extractor": frozen_route(temperature=0.3)}
        )
        self.assertNotEqual(config.method_fingerprint(), changed.method_fingerprint())

    def test_seedless_provider_route_can_still_freeze(self) -> None:
        config = frozen_config().model_copy(
            update={
                "roster_extractor": frozen_route(seed_honored=False),
                "roster_extractor_seeds": None,
            }
        )
        config.assert_frozen()

    def test_seed_honored_route_requires_three_distinct_seeds(self) -> None:
        config = frozen_config().model_copy(update={"roster_extractor_seeds": None})
        self.assertIn("roster_extractor_seeds", config.unfrozen_fields())

    def test_context_budget_math_and_gate(self) -> None:
        budget = frozen_budget()
        self.assertEqual(budget.input_budget(), 128000 - (8000 + 4000 + 2000 + 8000 + 1000))
        with self.assertRaisesRegex(ValueError, "not fully populated"):
            ScratchContextBudget().input_budget()


class ScratchGitBoundaryTest(unittest.TestCase):
    def test_benchmark_scratch_is_git_ignored(self) -> None:
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("benchmark/scratch/", gitignore.splitlines())


if __name__ == "__main__":
    unittest.main()
