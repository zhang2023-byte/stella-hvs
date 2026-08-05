"""Guard the extraction engineering baseline: registry entries, config gate, Git boundary."""

from __future__ import annotations

import unittest
from pathlib import Path

from stella.schema_registry import REGISTRY, schema_ref
from stella.hvs_extraction.method_config import (
    HvsComponentHashes,
    HvsContextBudget,
    HvsExtractionMethodConfig,
    HvsModelRoute,
    default_hvs_extraction_method_config,
    new_hvs_extraction_method_config,
    override_model_routes,
)
from stella.hvs_extraction.roster_stage import _route_kwargs


ROOT = Path(__file__).resolve().parents[1]

HVS_EXTRACTION_SCHEMAS = (
    "hvs_extraction.method_config",
    "hvs_extraction.prepared_input",
    "hvs_extraction.roster_proposal",
    "hvs_extraction.roster_final",
    "hvs_extraction.candidate_fields",
    "hvs_extraction.paper_result",
    "hvs_extraction.run_summary",
)


def frozen_route(**overrides: object) -> HvsModelRoute:
    values = {
        "provider": "deepseek",
        "model": "deepseek-v4-pro",
        "structured_output_mode": "tool_submission",
        "temperature": 0.2,
        "top_p": 1.0,
        "seed_honored": True,
    }
    values.update(overrides)
    return HvsModelRoute(**values)


def frozen_budget() -> HvsContextBudget:
    return HvsContextBudget(
        model_context_limit=128000,
        reserve_system_and_rules=8000,
        reserve_tool_schema=4000,
        reserve_candidate_suffix=2000,
        reserve_output=8000,
        reserve_provider_framing=1000,
    )


def frozen_config() -> HvsExtractionMethodConfig:
    return HvsExtractionMethodConfig(
        roster_model=frozen_route(),
        core_field_model=frozen_route(),
        roster_context_budget=frozen_budget(),
        field_context_budget=frozen_budget(),
        components=HvsComponentHashes(
            rule_profile_sha256={"hvs_candidate_roster": "a" * 64},
            prompt_template_sha256={"roster_model": "b" * 64},
            submission_schema_sha256={"submit_candidate_roster": "c" * 64},
        ),
    )


class HvsExtractionSchemaRegistryTest(unittest.TestCase):
    def test_operational_schemas_are_registered(self) -> None:
        for name in HVS_EXTRACTION_SCHEMAS:
            with self.subTest(name=name):
                entry = REGISTRY[name]
                self.assertEqual(entry.current_version, 1)
                self.assertEqual(entry.readable_versions, (1,))
                self.assertEqual(entry.lifecycle, "transient")
                self.assertEqual(
                    schema_ref(name), {"name": name, "version": 1}
                )
                self.assertEqual(
                    schema_ref(name, 1), {"name": name, "version": 1}
                )


class HvsExtractionMethodConfigTest(unittest.TestCase):
    def test_placeholder_config_cannot_freeze(self) -> None:
        config = new_hvs_extraction_method_config()
        missing = config.unfrozen_fields()
        self.assertIn("roster_model.model", missing)
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
            update={"roster_model": frozen_route(temperature=0.3)}
        )
        self.assertNotEqual(config.method_fingerprint(), changed.method_fingerprint())

    def test_context_budget_math_and_gate(self) -> None:
        budget = frozen_budget()
        self.assertEqual(budget.input_budget(), 128000 - (8000 + 4000 + 2000 + 8000 + 1000))
        with self.assertRaisesRegex(ValueError, "not fully populated"):
            HvsContextBudget().input_budget()


class HvsExtractionGitBoundaryTest(unittest.TestCase):
    def test_campaign_runs_are_git_ignored(self) -> None:
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("benchmark/campaigns/*/runs/*", gitignore.splitlines())
        self.assertIn("benchmark/campaigns/*/locks/", gitignore.splitlines())


class RouteRequestOverridesTest(unittest.TestCase):
    def test_default_config_thinking_overrides(self) -> None:
        config = default_hvs_extraction_method_config(ROOT)
        self.assertEqual(
            config.roster_model.request_overrides,
            {"thinking": {"type": "enabled"}},
        )
        self.assertEqual(config.core_field_model.request_overrides, {})

    def test_default_routes_match_approved_roles(self) -> None:
        config = default_hvs_extraction_method_config(ROOT)
        roster = config.roster_model
        self.assertEqual((roster.provider, roster.model), ("bigmodel", "glm-5.2"))
        self.assertEqual(roster.temperature, 0.0)
        self.assertEqual(roster.structured_output_mode, "tool_submission")
        field = config.core_field_model
        self.assertEqual((field.provider, field.model), ("deepseek", "deepseek-v4-pro"))
        self.assertEqual(field.temperature, 0.0)

    def test_role_local_route_override_changes_fingerprint(self) -> None:
        config = default_hvs_extraction_method_config(ROOT)
        changed = override_model_routes(
            config,
            roster_provider="fixture",
            roster_model="alternate-roster",
        )
        self.assertEqual(
            (changed.roster_model.provider, changed.roster_model.model),
            ("fixture", "alternate-roster"),
        )
        self.assertEqual(changed.roster_model.request_overrides, {})
        self.assertEqual(changed.core_field_model, config.core_field_model)
        self.assertNotEqual(
            changed.method_fingerprint(), config.method_fingerprint()
        )

    def test_roster_thinking_controls_change_fingerprint(self) -> None:
        config = default_hvs_extraction_method_config(ROOT)
        disabled = override_model_routes(
            config,
            roster_thinking="disabled",
        )
        high = override_model_routes(
            config,
            roster_thinking="enabled",
            roster_reasoning_effort="high",
        )
        self.assertEqual(
            disabled.roster_model.request_overrides,
            {"thinking": {"type": "disabled"}},
        )
        self.assertEqual(
            high.roster_model.request_overrides,
            {
                "thinking": {"type": "enabled"},
                "reasoning_effort": "high",
            },
        )
        self.assertEqual(disabled.core_field_model, config.core_field_model)
        self.assertNotEqual(
            disabled.method_fingerprint(), config.method_fingerprint()
        )
        self.assertNotEqual(
            high.method_fingerprint(), config.method_fingerprint()
        )

    def test_roster_reasoning_effort_requires_enabled_thinking(self) -> None:
        config = default_hvs_extraction_method_config(ROOT)
        with self.assertRaisesRegex(ValueError, "requires roster thinking enabled"):
            override_model_routes(
                config,
                roster_thinking="disabled",
                roster_reasoning_effort="high",
            )

    def test_core_field_reasoning_effort_changes_fingerprint(self) -> None:
        config = default_hvs_extraction_method_config(ROOT)
        changed = override_model_routes(
            config,
            core_field_provider="deepseek",
            core_field_model="deepseek-v4-flash-0731",
            core_field_reasoning_effort="low",
        )
        self.assertEqual(
            (changed.core_field_model.provider, changed.core_field_model.model),
            ("deepseek", "deepseek-v4-flash-0731"),
        )
        self.assertEqual(
            changed.core_field_model.request_overrides,
            {"reasoning_effort": "low"},
        )
        self.assertEqual(changed.roster_model, config.roster_model)
        self.assertNotEqual(
            changed.method_fingerprint(), config.method_fingerprint()
        )

    def test_core_field_thinking_controls_change_fingerprint(self) -> None:
        config = default_hvs_extraction_method_config(ROOT)
        disabled = override_model_routes(
            config,
            core_field_thinking="disabled",
        )
        enabled = override_model_routes(
            config,
            core_field_thinking="enabled",
            core_field_reasoning_effort="low",
        )
        self.assertEqual(
            disabled.core_field_model.request_overrides,
            {"thinking": {"type": "disabled"}},
        )
        self.assertEqual(
            enabled.core_field_model.request_overrides,
            {
                "thinking": {"type": "enabled"},
                "reasoning_effort": "low",
            },
        )
        self.assertEqual(disabled.roster_model, config.roster_model)
        self.assertNotEqual(
            disabled.method_fingerprint(), config.method_fingerprint()
        )
        self.assertNotEqual(
            enabled.method_fingerprint(), config.method_fingerprint()
        )

    def test_core_field_thinking_disabled_clears_previous_effort(self) -> None:
        config = default_hvs_extraction_method_config(ROOT)
        effort = override_model_routes(config, core_field_reasoning_effort="low")
        disabled = override_model_routes(effort, core_field_thinking="disabled")
        self.assertEqual(
            disabled.core_field_model.request_overrides,
            {"thinking": {"type": "disabled"}},
        )

    def test_core_field_reasoning_effort_rejects_disabled_thinking(self) -> None:
        config = default_hvs_extraction_method_config(ROOT)
        with self.assertRaisesRegex(
            ValueError, "requires core-field thinking enabled"
        ):
            override_model_routes(
                config,
                core_field_thinking="disabled",
                core_field_reasoning_effort="low",
            )

    def test_route_overrides_merge_into_extra_body(self) -> None:
        route = frozen_route(
            provider="bigmodel",
            model="glm-5.2",
            temperature=0.0,
            request_overrides={"thinking": {"type": "disabled"}},
        )
        kwargs = _route_kwargs(
            route,
            tool_name="submit_final_candidate_roster",
            schema={"type": "object"},
            api_key="key",
            base_url="https://example.invalid",
            seed=None,
            max_tokens=8,
        )
        self.assertEqual(
            kwargs["extra_body"]["thinking"], {"type": "disabled"}
        )

    def test_reasoning_effort_merges_into_extra_body(self) -> None:
        route = frozen_route(
            provider="bigmodel",
            model="glm-5.2",
            temperature=0.0,
            request_overrides={
                "thinking": {"type": "enabled"},
                "reasoning_effort": "high",
            },
        )
        kwargs = _route_kwargs(
            route,
            tool_name="submit_final_candidate_roster",
            schema={"type": "object"},
            api_key="key",
            base_url="https://example.invalid",
            seed=None,
            max_tokens=8,
        )
        self.assertEqual(kwargs["extra_body"]["reasoning_effort"], "high")

    def test_conflicting_override_is_rejected(self) -> None:
        route = frozen_route(request_overrides={"tools": []})
        with self.assertRaisesRegex(ValueError, "conflicts"):
            _route_kwargs(
                route,
                tool_name="submit_candidate_roster",
                schema={"type": "object"},
                api_key="key",
                base_url="https://example.invalid",
                seed=None,
                max_tokens=8,
            )

    def test_stream_route_sets_stream_and_longer_timeout(self) -> None:
        route = frozen_route(stream=True)
        kwargs = _route_kwargs(
            route,
            tool_name="submit_candidate_roster",
            schema={"type": "object"},
            api_key="key",
            base_url="https://example.invalid",
            seed=None,
            max_tokens=8,
        )
        self.assertTrue(kwargs["stream"])
        self.assertEqual(kwargs["timeout_seconds"], 1800)

    def test_default_config_only_roster_streams(self) -> None:
        config = default_hvs_extraction_method_config(ROOT)
        self.assertTrue(config.roster_model.stream)
        self.assertFalse(config.core_field_model.stream)


if __name__ == "__main__":
    unittest.main()
