from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
from stella.benchmark.paths import campaign_paths, require_external_path  # noqa: E402
from stella.schema_registry import ACTIVE_BENCHMARK_CAMPAIGN  # noqa: E402


def load_script(name: str):
    script = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BenchmarkPathSafetyTest(unittest.TestCase):
    def test_private_artifacts_must_stay_outside_workspace(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside"):
            require_external_path(
                ROOT / "benchmark" / "private-details",
                workspace=ROOT,
                label="private details",
            )
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                require_external_path(Path(tmp), workspace=ROOT, label="private details"),
                Path(tmp).resolve(),
            )


class BuildBenchmarkManifestCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cli = load_script("build_benchmark_manifest")

    def test_defaults(self) -> None:
        args = self.cli.build_parser().parse_args([])
        self.assertEqual(args.literature_dir, ROOT / "literature")
        self.assertEqual(
            args.output, campaign_paths(ROOT).sampling_manifest
        )
        self.assertEqual(args.seed, 20260611)
        self.assertFalse(args.skip_version_check)

    def test_overrides(self) -> None:
        args = self.cli.build_parser().parse_args(
            ["--seed", "7", "--skip-version-check", "--output", "/tmp/m.json"]
        )
        self.assertEqual(args.seed, 7)
        self.assertTrue(args.skip_version_check)
        self.assertEqual(args.output, Path("/tmp/m.json"))


class UpgradeGoldAnnotationCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cli = load_script("upgrade_gold_annotation")

    def test_defaults(self) -> None:
        args = self.cli.build_parser().parse_args(["gold/x/annotation_a.yaml"])
        self.assertEqual(args.annotation, Path("gold/x/annotation_a.yaml"))
        self.assertIsNone(args.output)
        self.assertEqual(
            args.manifest, campaign_paths(ROOT).sampling_manifest
        )


class BuildGoldSelectionCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cli = load_script("build_gold_selection")

    def test_required_selection_inputs_and_campaign_defaults(self) -> None:
        args = self.cli.build_parser().parse_args(
            [
                "--split",
                "dev",
                "--selection-id",
                "dev-primary-v1",
                "--annotator-map",
                "/tmp/annotators.json",
            ]
        )
        self.assertEqual(args.campaign, ACTIVE_BENCHMARK_CAMPAIGN)
        self.assertEqual(args.split, "dev")
        self.assertEqual(args.selection_id, "dev-primary-v1")
        self.assertEqual(args.annotator_map, Path("/tmp/annotators.json"))

    def test_annotator_map_must_be_string_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "map.json"
            path.write_text(json.dumps({"2401.00001": 7}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "JSON object"):
                self.cli.load_annotator_map(path)

    def test_assignment_profile_can_supply_primary_annotators(self) -> None:
        args = self.cli.build_parser().parse_args(
            [
                "--split",
                "test",
                "--selection-id",
                "test-primary-v1",
                "--gold-assignment-id",
                "primary-v1",
            ]
        )
        self.assertEqual(args.gold_assignment_id, "primary-v1")
        self.assertIsNone(args.annotator_map)


class BuildGoldAssignmentCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cli = load_script("build_gold_assignment")

    def test_required_inputs_and_campaign_default(self) -> None:
        args = self.cli.build_parser().parse_args(
            ["--assignment-id", "primary-v1", "--assignment-map", "/tmp/map.json"]
        )
        self.assertEqual(args.campaign, ACTIVE_BENCHMARK_CAMPAIGN)
        self.assertEqual(args.assignment_id, "primary-v1")
        self.assertEqual(args.assignment_map, Path("/tmp/map.json"))


class ListGoldAnnotationQueueCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cli = load_script("list_gold_annotation_queue")

    def test_defaults_to_new_queue_for_assignment_id(self) -> None:
        args = self.cli.build_parser().parse_args(
            ["--assignment-id", "primary-v1", "--annotator", "will"]
        )
        self.assertEqual(args.campaign, ACTIVE_BENCHMARK_CAMPAIGN)
        self.assertEqual(args.status, "new")
        self.assertEqual(args.assignment_id, "primary-v1")


class ScoreBenchmarkRunCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cli = load_script("score_benchmark_run")

    def test_gold_selection_is_required(self) -> None:
        with self.assertRaises(SystemExit):
            self.cli.build_parser().parse_args(["--split", "dev", "--run-dir", "/tmp/run"])

    def test_pricing_snapshot_is_required_and_parsed(self) -> None:
        args = self.cli.build_parser().parse_args(
            [
                "--split",
                "dev",
                "--run-dir",
                "/tmp/run",
                "--gold-selection-id",
                "dev-primary-v1",
                "--pricing-snapshot-id",
                "tokendance-2026-08-03-screenshots-v1",
            ]
        )
        self.assertEqual(
            args.pricing_snapshot_id, "tokendance-2026-08-03-screenshots-v1"
        )

    def test_selection_id_and_manifest_are_mutually_exclusive(self) -> None:
        with self.assertRaises(SystemExit):
            self.cli.build_parser().parse_args(
                [
                    "--split",
                    "dev",
                    "--run-dir",
                    "/tmp/run",
                    "--pricing-snapshot-id",
                    "tokendance-2026-08-03-screenshots-v1",
                    "--gold-selection-id",
                    "dev-primary-v1",
                    "--gold-selection-manifest",
                    "/tmp/selection.json",
                ]
            )


class BuildBenchmarkCampaignCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cli = load_script("build_benchmark_campaign")

    def test_defaults(self) -> None:
        args = self.cli.build_parser().parse_args([])
        self.assertEqual(
            args.sampling_manifest,
            campaign_paths(ROOT).sampling_manifest,
        )
        self.assertEqual(
            args.output, campaign_paths(ROOT).campaign_manifest
        )
        self.assertEqual(
            args.reference_manifest, campaign_paths(ROOT).campaign_manifest
        )
        self.assertIsNone(args.code_commit)

    def test_reference_manifest_supplies_stable_code_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reference = Path(tmp) / "campaign.json"
            reference.write_text(
                json.dumps(
                    {
                        "schema": {"name": "benchmark.campaign", "version": 1},
                        "campaign_id": ACTIVE_BENCHMARK_CAMPAIGN,
                        "code_commit": "a" * 40,
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                self.cli.resolve_code_commit(reference, None), "a" * 40
            )


class HistoricalCampaignMigrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cli = load_script("migrate_benchmark_campaign_layout")

    def test_v1_to_v2_migration_keeps_an_explicit_v2_target(self) -> None:
        self.assertEqual(self.cli.V2_CAMPAIGN_ID, "hvs-extraction-v2")
        self.assertEqual(
            self.cli.V2,
            ROOT / "benchmark" / "campaigns" / "hvs-extraction-v2",
        )


class ReleaseBenchmarkTestCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cli = load_script("release_benchmark_test")

    def test_campaign_selector_is_supported(self) -> None:
        args = self.cli.build_parser().parse_args(
            ["--campaign", ACTIVE_BENCHMARK_CAMPAIGN, "--run-dir", "/tmp/run"]
        )
        self.assertEqual(args.campaign, ACTIVE_BENCHMARK_CAMPAIGN)
        self.assertIsNone(args.campaign_manifest)
        self.assertIsNone(args.releases_root)

    def test_campaign_selector_resolves_scoped_paths(self) -> None:
        release = {
            "campaign": {"campaign_id": ACTIVE_BENCHMARK_CAMPAIGN},
            "run": {"run_id": "run-1"},
        }
        with mock.patch.object(
            sys,
            "argv",
            [
                "release_benchmark_test.py",
                "--campaign",
                ACTIVE_BENCHMARK_CAMPAIGN,
                "--run-dir",
                "/tmp/run-1",
            ],
        ), mock.patch.object(
            self.cli, "build_test_release", return_value=release
        ) as build, mock.patch.object(
            self.cli,
            "write_test_release",
            return_value=Path("/tmp/releases/run-1.json"),
        ) as write:
            self.assertEqual(self.cli.main(), 0)
        paths = campaign_paths(ROOT)
        self.assertEqual(
            build.call_args.kwargs["campaign_path"], paths.campaign_manifest.resolve()
        )
        self.assertEqual(write.call_args.kwargs["releases_root"], paths.releases)


class ServeGoldAnnotationCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cli = load_script("serve_gold_annotation")

    def test_defaults(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("STELLA_GOLD_DIR", None)
            args = self.cli.build_parser().parse_args([])
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 8765)
        self.assertEqual(args.arxiv_id, "")
        self.assertEqual(
            args.manifest, campaign_paths(ROOT).sampling_manifest
        )
        # Gold lives in the external private repository; without
        # STELLA_GOLD_DIR there is no default and main() must refuse to run.
        self.assertIsNone(args.gold_dir)
        self.assertFalse(args.no_open)

    def test_gold_dir_env_default(self) -> None:
        with mock.patch.dict(os.environ, {"STELLA_GOLD_DIR": "/tmp/private-gold"}):
            args = self.cli.build_parser().parse_args([])
        self.assertEqual(args.gold_dir, Path("/tmp/private-gold"))

    def test_overrides(self) -> None:
        args = self.cli.build_parser().parse_args(
            [
                "--arxiv-id",
                "1902.05061",
                "--annotator",
                "will",
                "--port",
                "8766",
                "--manifest",
                "/tmp/manifest.json",
                "--gold-dir",
                "/tmp/gold",
                "--no-open",
            ]
        )
        self.assertEqual(args.arxiv_id, "1902.05061")
        self.assertEqual(args.annotator, "will")
        self.assertEqual(args.port, 8766)
        self.assertEqual(args.manifest, Path("/tmp/manifest.json"))
        self.assertEqual(args.gold_dir, Path("/tmp/gold"))
        self.assertTrue(args.no_open)


class CheckLlmEndpointCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cli = load_script("check_llm_endpoint")

    def test_defaults(self) -> None:
        args = self.cli.build_parser().parse_args([])
        self.assertIsNone(args.model)
        self.assertFalse(args.skip_chat)
        self.assertEqual(args.timeout, 120.0)

    def test_cjk_detector(self) -> None:
        self.assertTrue(self.cli.CJK_RE.search("ENDPOINT OK 词元跳动"))
        self.assertFalse(self.cli.CJK_RE.search("ENDPOINT OK. DeepSeek V4 Pro"))

    def test_structured_probe_summary_never_returns_prompt_or_arguments(self) -> None:
        reply = {
            "model": "glm-5.2",
            "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "submit_synthetic_roster",
                                    "arguments": json.dumps(
                                        {
                                            "candidates": [],
                                            "reviewed_exclusions": [],
                                            "range_groups": [],
                                        }
                                    ),
                                },
                            }
                        ],
                    }
                }
            ],
        }
        with mock.patch.object(self.cli, "chat_completion_raw", return_value=reply) as call:
            result = self.cli.structured_probe_once(
                base_url="https://example.invalid/v1",
                api_key="secret",
                model="glm-5.2",
                provider="bigmodel",
                timeout=120,
                long_context_chars=120_000,
            )
        self.assertNotIn("messages", result)
        self.assertNotIn("arguments", result)
        sent = call.call_args.kwargs
        self.assertGreaterEqual(len(sent["messages"][1]["content"]), 120_000)
        self.assertNotIn("secret", json.dumps(result))

    def test_json_object_probe_merges_overrides_in_roster_stage_order(self) -> None:
        reply = {
            "model": "deepseek-v4-pro",
            "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "candidates": [],
                                "reviewed_exclusions": [],
                                "range_groups": [],
                            }
                        )
                    }
                }
            ],
        }
        with mock.patch.object(self.cli, "chat_completion_raw", return_value=reply) as call:
            result = self.cli.structured_probe_once(
                base_url="https://example.invalid/v1",
                api_key="secret",
                model="deepseek-v4-pro",
                provider="deepseek",
                timeout=120,
                long_context_chars=0,
                mode="json_object",
                thinking="enabled",
                reasoning_effort="max",
                stream=True,
                max_tokens=8000,
            )
        sent = call.call_args.kwargs
        self.assertEqual(
            sent["extra_body"]["response_format"], {"type": "json_object"}
        )
        self.assertNotIn("tools", sent["extra_body"])
        self.assertNotIn("tool_choice", sent["extra_body"])
        self.assertEqual(sent["extra_body"]["thinking"], {"type": "enabled"})
        self.assertEqual(sent["extra_body"]["reasoning_effort"], "max")
        self.assertTrue(sent["stream"])
        self.assertEqual(sent["max_tokens"], 8000)
        self.assertIn("no_candidates", sent["messages"][1]["content"])
        self.assertEqual(result["mode"], "json_object")
        self.assertEqual(result["thinking"], "enabled")
        self.assertEqual(result["reasoning_effort"], "max")
        self.assertTrue(result["stream"])
        self.assertNotIn("secret", json.dumps(result))

    def test_probe_thinking_conflicts_with_declared_contract(self) -> None:
        with self.assertRaisesRegex(ValueError, "conflicts with the declared contract"):
            self.cli.structured_probe_once(
                base_url="https://example.invalid/v1",
                api_key="secret",
                model="deepseek-v4-pro",
                provider="deepseek",
                timeout=120,
                long_context_chars=0,
                thinking="enabled",
            )

    def test_probe_reasoning_effort_requires_thinking_enabled(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires --thinking enabled"):
            self.cli.structured_probe_once(
                base_url="https://example.invalid/v1",
                api_key="secret",
                model="glm-5.2",
                provider="bigmodel",
                timeout=120,
                long_context_chars=0,
                reasoning_effort="max",
            )
