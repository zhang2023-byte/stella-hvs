"""Tests for the neutral scientific contracts under ``contracts/``.

Pydantic models are the structural source of the generated JSON Schema
views; the YAML files under ``contracts/`` own the scientific rules. The
contribution rule profile is served from ``contracts/hvs-contributions``
only, while candidate-only rules stay in the legacy skills directory until
their execution surface is removed.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
CONTRIBUTION_RULES = CONTRACTS / "hvs-contributions" / "rules"
GENERATED = CONTRACTS / "generated"
SKILLS_RULES = ROOT / "skills" / "hvs-candidates-extraction" / "rules"


class ContributionRulesLocationTest(unittest.TestCase):
    def test_contribution_rule_modules_live_in_contracts(self) -> None:
        for name in (
            "paper-claims.yaml",
            "hvs-contributions-roster.yaml",
            "hvs-contributions-quantities.yaml",
            "profiles.yaml",
        ):
            self.assertTrue(
                (CONTRIBUTION_RULES / name).is_file(), f"missing {name}"
            )

    def test_contribution_profiles_declare_only_the_contribution_profile(self) -> None:
        payload = yaml.safe_load(
            (CONTRIBUTION_RULES / "profiles.yaml").read_text(encoding="utf-8")
        )
        self.assertEqual(set(payload["profiles"]), {"hvs_contribution_v1"})

    def test_contribution_catalog_excludes_candidate_rules(self) -> None:
        from stella.lit.extraction_rules import load_contribution_rule_catalog

        catalog = load_contribution_rule_catalog(ROOT)
        rule_ids = list(catalog.rules)
        self.assertIn("hvs.contrib.paper_boundness", rule_ids)
        self.assertIn("hvs.contrib.deterministic_range_groups", rule_ids)
        self.assertIn("hvs.contrib.structured_quantity_scope", rule_ids)
        self.assertNotIn("hvs.contrib.paper_local_boundary", rule_ids)
        self.assertNotIn("hvs.contrib.nineteen_quantities", rule_ids)
        roster_rules = [
            rule for rule in catalog.rules.values()
            if rule.module_id == "hvs_contribution_roster"
        ]
        self.assertEqual(len(roster_rules), 13)
        profile = catalog.profile_rules("hvs_contribution_v1")
        for rule in profile:
            self.assertFalse(
                rule.id.startswith(("hvs.roster.", "hvs.field.")),
                f"contribution profile leaks V6 rule {rule.id}",
            )

    def test_hvs_class_anchor_requires_definition_and_application(self) -> None:
        from stella.lit.extraction_rules import load_contribution_rule_catalog

        catalog = load_contribution_rule_catalog(ROOT)
        rule = " ".join(
            catalog.rules["hvs.contrib.no_proxy_anchor"].text.split()
        )
        self.assertIn("meaning varies across papers", rule)
        self.assertIn(
            "explicitly defines that class as unbound from or escaping the Milky Way",
            rule,
        )
        self.assertIn("clearly applies that defined classification", rule)
        self.assertIn("Proper names, catalogue or sample membership", rule)
        self.assertIn("remain insufficient by themselves", rule)
        group_rule = " ".join(
            catalog.rules["hvs.contrib.group_level_anchor"].text.split()
        )
        self.assertIn(
            "HVS-labelled headings or tables by themselves do not propagate an anchor",
            group_rule,
        )


class GeneratedSchemaViewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from stella import schema_registry

        cls.registry = schema_registry
        cls.artifacts = schema_registry.MODELLED_ARTIFACTS

    def test_modelled_artifacts_cover_the_contribution_contract(self) -> None:
        by_name = {name for name, _version in self.artifacts}
        self.assertIn("literature_hvs_contributions", by_name)
        self.assertIn("article_data_assets.review", by_name)
        self.assertIn("literature.catalog_assessment", by_name)
        self.assertIn("benchmark.hvs_contribution_annotation", by_name)

    def test_generated_views_match_pydantic_models(self) -> None:
        for name, version in self.artifacts:
            with self.subTest(artifact=f"{name}.v{version}"):
                path = GENERATED / f"{name}.v{version}.schema.json"
                self.assertTrue(path.is_file(), f"missing generated view {path}")
                payload = json.loads(path.read_text(encoding="utf-8"))
                model = self.registry.model_for(name, version)
                expected = model.model_json_schema()
                for key in ("$schema", "title", "type", "properties", "required", "$defs"):
                    if key in expected:
                        self.assertEqual(
                            payload[key],
                            expected[key],
                            f"generated view {path.name} drifted on {key}",
                        )

    def test_generated_views_carry_regeneration_header(self) -> None:
        path = GENERATED / "literature_hvs_contributions.v1.schema.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        header = payload["_stella_generated"]
        self.assertIn("python -m stella schema generate", header["regenerate"])
        self.assertIn("stella.lit.hvs_contribution_models", header["source_model"])

    def test_gold_quantity_schema_exposes_the_nineteen_allowed_paths(self) -> None:
        from stella.lit.schema_specs import HVS_CONTRIBUTION_QUANTITIES

        path = GENERATED / "benchmark.hvs_contribution_annotation.v1.schema.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        quantity = payload["$defs"]["GoldQuantityGroup"]["properties"]["quantity"]
        self.assertEqual(quantity["enum"], list(HVS_CONTRIBUTION_QUANTITIES))

    def test_check_views_reports_no_drift_for_committed_views(self) -> None:
        result = self.registry.check_views(ROOT)
        self.assertEqual(result["drift"], [])

    def test_check_views_detects_drift_and_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp) / "contracts"
            shutil.copytree(CONTRACTS, copied)
            target = copied / "generated" / "literature_hvs_contributions.v1.schema.json"
            before = target.read_bytes()
            payload = json.loads(target.read_text(encoding="utf-8"))
            payload["properties"]["generated_at"]["type"] = "integer"
            target.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            result = self.registry.check_views(Path(tmp), contracts_dir=copied)
            self.assertIn(
                "contracts/generated/literature_hvs_contributions.v1.schema.json",
                result["drift"],
            )
            self.assertEqual(target.read_bytes()[:0], before[:0])
            self.assertNotEqual(target.read_bytes(), before)


class DynamicsRulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload = yaml.safe_load(
            (CONTRACTS / "hvs-dynamics" / "calculation-rules.yaml").read_text(
                encoding="utf-8"
            )
        )

    def test_solar_parameters_match_implementation(self) -> None:
        from stella.dyn.dynamics import SOLAR_PROVENANCE

        solar = self.payload["solar_parameters"]
        self.assertEqual(
            solar["galcen_distance_kpc"], SOLAR_PROVENANCE["galcen_distance_kpc"]
        )
        self.assertEqual(solar["z_sun_kpc"], SOLAR_PROVENANCE["z_sun_kpc"])
        self.assertEqual(
            solar["galcen_v_sun_kms"], SOLAR_PROVENANCE["galcen_v_sun_kms"]
        )

    def test_defaults_match_implementation(self) -> None:
        from stella.dyn import dynamics

        defaults = self.payload["defaults"]
        self.assertEqual(defaults["mcmc_samples"], dynamics.DEFAULT_MCMC_SAMPLES)
        self.assertEqual(defaults["hp_level"], dynamics.DEFAULT_HP_LEVEL)

    def test_potential_policy_is_declared(self) -> None:
        from stella.dyn.dynamics import (
            MCMILLAN17_RO_KPC,
            MCMILLAN17_VO_KMS,
            POTENTIAL_PROVENANCE,
        )

        potential = self.payload["potential"]
        self.assertEqual(potential["name"], POTENTIAL_PROVENANCE["name"])
        self.assertEqual(potential["implementation"], POTENTIAL_PROVENANCE["implementation"])
        self.assertEqual(potential["ro_kpc"], MCMILLAN17_RO_KPC)
        self.assertEqual(potential["vo_kms"], MCMILLAN17_VO_KMS)

    def test_selection_policy_is_fail_closed(self) -> None:
        policy = self.payload["input_selection"]
        self.assertTrue(policy["requires_human_approved_snapshot"])
        self.assertIn("never-automatic", policy["mode"])


class SchemaViewsCliTest(unittest.TestCase):
    def test_cli_schema_check_passes(self) -> None:
        from tests.test_cli import run_cli

        code, payload = run_cli("schema", "check", "--json")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["data"]["drift"], [])

    def test_cli_schema_generate_is_idempotent(self) -> None:
        from tests.test_cli import run_cli

        code, payload = run_cli("schema", "generate", "--json")
        self.assertEqual(code, 0, payload)
        code, payload = run_cli("schema", "check", "--json")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["data"]["drift"], [])


if __name__ == "__main__":
    unittest.main()
