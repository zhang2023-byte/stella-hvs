from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
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


if __name__ == "__main__":
    unittest.main()
