from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from stella.benchmark.agent_harness import (
    collect_bundle,
    launch_adapter,
    prepare_bundle,
)


def make_workspace(root: Path, arxiv_id: str = "9901.00001") -> None:
    paper = root / "literature" / arxiv_id
    source = paper / "arxiv_source"
    tables = paper / "catalog_tables"
    source.mkdir(parents=True)
    tables.mkdir()
    (paper / "catalog_review.json").write_text("{}", encoding="utf-8")
    (paper / "catalog_extraction.json").write_text(
        json.dumps(
            {
                "tables": [
                    {
                        "status": "success",
                        "ecsv_path": f"literature/{arxiv_id}/catalog_tables/table.ecsv",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (tables / "table.ecsv").write_text("# %ECSV 1.0\nname\nStarA\n", encoding="utf-8")
    (source / "paper.tex").write_text("\\title{Synthetic}\n", encoding="utf-8")
    (source / "refs.bib").write_text("@article{x,}\n", encoding="utf-8")
    skill = root / "skills" / "hvs-candidates-extraction" / "references"
    skill.mkdir(parents=True, exist_ok=True)
    (skill.parent / "SKILL.md").write_text("# Skill\n", encoding="utf-8")
    (skill / "schema.md").write_text("# Schema\n", encoding="utf-8")
    (root / "scripts").mkdir(exist_ok=True)
    (root / "scripts" / "validate_hvs_candidates.py").write_text("# frozen\n", encoding="utf-8")


class FakeValidator:
    def __init__(self, errors: list[str] | None = None) -> None:
        self.errors = errors or []

    def validate_hvs_candidates_report(self, payload, *, workspace, require_complete):
        return type("Report", (), {"errors": self.errors, "warnings": []})()


class AgentHarnessTest(unittest.TestCase):
    def config(self) -> dict:
        return {
            "run_id": "method-a",
            "expected_papers": ["9901.00001"],
            "method_fingerprint": "fingerprint",
            "method": {
                "producer": "stella-skill-agent-extraction",
                "runtime": {"name": "fake-agent", "release": "2.0"},
                "models": {"extractor": "fake-model", "reviewer": None},
                "provenance": {"stella_release": "0.2.0", "components": {"prompt": "prompt-v1"}},
            },
        }

    def test_prepare_whitelist_and_deterministic_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            make_workspace(root)
            make_workspace(root, "9901.00002")
            bundle = prepare_bundle(
                workspace=root,
                run_dir=Path(tmp) / "runs" / "method-a",
                bundle_root=Path(tmp) / "bundles",
                arxiv_id="9901.00001",
                run_config=self.config(),
            )
            paths = {
                path.relative_to(bundle.root).as_posix()
                for path in bundle.root.rglob("*")
                if path.is_file()
            }
            self.assertIn("inputs/catalog_review.json", paths)
            self.assertIn("inputs/catalog_tables/table.ecsv", paths)
            self.assertIn("skill/SKILL.md", paths)
            self.assertIn("validator/validate_hvs_candidates.py", paths)
            self.assertNotIn("inputs/9901.00002", "\n".join(paths))
            self.assertFalse(any("gold" in path.lower() for path in paths))
            self.assertFalse(any("scoring" in path.lower() or "runs" in path.lower() for path in paths))
            first = json.loads(bundle.input_manifest_path.read_text(encoding="utf-8"))
            self.assertTrue(first["files"])
            second = prepare_bundle(
                workspace=root,
                run_dir=Path(tmp) / "runs" / "method-a",
                bundle_root=Path(tmp) / "bundles-2",
                arxiv_id="9901.00001",
                run_config=self.config(),
            )
            self.assertEqual(
                first,
                json.loads(second.input_manifest_path.read_text(encoding="utf-8")),
            )

    def test_launch_uses_bundle_cwd_and_clears_gold_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            make_workspace(root)
            bundle = prepare_bundle(
                workspace=root,
                run_dir=Path(tmp) / "runs" / "method-a",
                bundle_root=Path(tmp) / "bundles",
                arxiv_id="9901.00001",
                run_config=self.config(),
            )
            adapter = Path(tmp) / "adapter.py"
            adapter.write_text(
                "import json, os, pathlib\n"
                "pathlib.Path('adapter-observation.json').write_text(json.dumps({'cwd': os.getcwd(), 'gold': os.environ.get('STELLA_GOLD_DIR'), 'task': os.environ.get('STELLA_BENCHMARK_TASK'), 'output': os.environ.get('STELLA_BENCHMARK_OUTPUT')}))\n",
                encoding="utf-8",
            )
            launch_adapter(
                bundle=bundle,
                argv=[os.environ.get("PYTHON", "python"), str(adapter)],
                base_env={"PATH": os.environ.get("PATH", ""), "STELLA_GOLD_DIR": "/private/gold"},
            )
            observed = json.loads((bundle.root / "adapter-observation.json").read_text())
            self.assertEqual(Path(observed["cwd"]).resolve(), bundle.root.resolve())
            self.assertIsNone(observed["gold"])
            self.assertEqual(observed["task"], str(bundle.task_path))
            self.assertEqual(observed["output"], str(bundle.output_path))

    def test_collect_detects_input_mutation_and_archives_valid_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            make_workspace(root)
            run_dir = Path(tmp) / "runs" / "method-a"
            bundle = prepare_bundle(
                workspace=root,
                run_dir=run_dir,
                bundle_root=Path(tmp) / "bundles",
                arxiv_id="9901.00001",
                run_config=self.config(),
            )
            document = {
                "extraction": {
                    "provenance": {
                        "runtime": "fake-agent/2.0",
                        "model_id": "fake-model",
                        "git_commit": "prompt-v1",
                        "parameters": {"method_fingerprint": "fingerprint"},
                    }
                }
            }
            bundle.output_path.write_text(json.dumps(document), encoding="utf-8")
            result = collect_bundle(
                workspace=root,
                run_dir=run_dir,
                bundle=bundle,
                run_config=self.config(),
                validator_module=FakeValidator(),
            )
            self.assertEqual(result["status"], "ok")
            self.assertTrue((run_dir / "9901.00001" / "literature_hvs_candidates.json").is_file())
            (bundle.root / "inputs" / "catalog_review.json").write_text("tampered", encoding="utf-8")
            result = collect_bundle(
                workspace=root,
                run_dir=run_dir,
                bundle=bundle,
                run_config=self.config(),
                validator_module=FakeValidator(),
            )
            self.assertEqual(result["status"], "input_mutated")

    def test_collect_diagnostic_only_on_invalid_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            make_workspace(root)
            run_dir = Path(tmp) / "runs" / "method-a"
            bundle = prepare_bundle(
                workspace=root,
                run_dir=run_dir,
                bundle_root=Path(tmp) / "bundles",
                arxiv_id="9901.00001",
                run_config=self.config(),
            )
            bundle.output_path.write_text("not-json", encoding="utf-8")
            result = collect_bundle(
                workspace=root,
                run_dir=run_dir,
                bundle=bundle,
                run_config=self.config(),
                validator_module=FakeValidator(),
            )
            paper_dir = run_dir / "9901.00001"
            self.assertEqual(result["status"], "invalid_json")
            self.assertTrue((paper_dir / "report.json").is_file())
            self.assertFalse((paper_dir / "literature_hvs_candidates.json").exists())


if __name__ == "__main__":
    unittest.main()
