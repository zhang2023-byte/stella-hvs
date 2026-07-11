from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
from stella.benchmark.paths import campaign_paths  # noqa: E402


def load_script(name: str):
    script = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


class RunBenchmarkExtractionCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cli = load_script("run_benchmark_extraction")

    def test_defaults(self) -> None:
        args = self.cli.build_parser().parse_args(["--pilot"])
        self.assertTrue(args.pilot)
        self.assertIsNone(args.model)
        self.assertIsNone(args.run_id)
        self.assertEqual(args.runs_dir, campaign_paths(ROOT).runs)
        self.assertEqual(args.max_repair_rounds, 3)
        self.assertFalse(args.dry_run)

    def test_pilot_and_arxiv_id_are_exclusive(self) -> None:
        with self.assertRaises(SystemExit):
            self.cli.build_parser().parse_args(
                ["--pilot", "--arxiv-id", "1804.09677"]
            )


if __name__ == "__main__":
    unittest.main()
