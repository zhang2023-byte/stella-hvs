from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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
            args.output, ROOT / "benchmark" / "manifest" / "sampling_manifest.json"
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
            args.manifest, ROOT / "benchmark" / "manifest" / "sampling_manifest.json"
        )


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
        self.assertEqual(args.runs_dir, ROOT / "benchmark" / "runs")
        self.assertEqual(args.max_repair_rounds, 2)
        self.assertFalse(args.dry_run)

    def test_pilot_and_arxiv_id_are_exclusive(self) -> None:
        with self.assertRaises(SystemExit):
            self.cli.build_parser().parse_args(
                ["--pilot", "--arxiv-id", "1804.09677"]
            )


class BuildReviewWorkbenchCliTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cli = load_script("build_review_workbench")

    def test_defaults(self) -> None:
        args = self.cli.build_parser().parse_args([])
        self.assertEqual(args.arxiv_id, [])
        self.assertFalse(args.all_verification)
        self.assertFalse(args.allow_unsampled)
        self.assertEqual(args.output_dir, ROOT / "benchmark" / "workbench")
        self.assertEqual(args.literature_dir, ROOT / "literature")

    def test_repeatable_arxiv_id(self) -> None:
        args = self.cli.build_parser().parse_args(
            ["--arxiv-id", "1804.09677", "--arxiv-id", "2012.09338"]
        )
        self.assertEqual(args.arxiv_id, ["1804.09677", "2012.09338"])


if __name__ == "__main__":
    unittest.main()
