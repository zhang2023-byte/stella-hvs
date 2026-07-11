from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from stella.benchmark.run_contract import (
    build_method_fingerprint,
    build_run_config,
    ensure_run_config,
    prepare_paper_retry,
    seal_run,
)
from stella.schema_registry import schema_ref


class FakeValidator:
    def validate_hvs_candidates_report(self, payload, *, workspace, require_complete):
        return type("Report", (), {"errors": [], "warnings": []})()


class RunContractTest(unittest.TestCase):
    def method(self) -> dict:
        return {
            "pipeline": {"name": "method-b", "version": "1"},
            "models": {"extractor": "model-a", "reviewer": None},
            "providers": {"extractor": ["p"]},
            "versions": {
                "prompt": "p1",
                "skill": "s1",
                "validator": "v1",
                "context_packer": "c1",
            },
        }

    def config(self) -> dict:
        return build_run_config(
            run_id="r1",
            method=self.method(),
            expected_papers=["x"],
            code={"commit": "abc", "dirty": True},
        )

    def test_fingerprint_is_canonical(self) -> None:
        first = self.method()
        second = dict(reversed(list(first.items())))
        self.assertEqual(build_method_fingerprint(first), build_method_fingerprint(second))

    def test_run_id_must_be_one_safe_path_segment(self) -> None:
        for run_id in ("../escape", "nested/run", "nested\\run", ".", "", " run "):
            with self.subTest(run_id=run_id):
                with self.assertRaisesRegex(ValueError, "run id"):
                    build_run_config(
                        run_id=run_id,
                        method=self.method(),
                        expected_papers=["x"],
                        code={"commit": "abc", "dirty": True},
                    )

    def test_formal_run_rejects_dirty_tree(self) -> None:
        campaign = {
            "campaign_id": "c",
            "papers": [{"arxiv_id": "x", "split": "dev"}],
        }
        with self.assertRaisesRegex(ValueError, "clean worktree"):
            build_run_config(
                run_id="r1",
                method=self.method(),
                expected_papers=["x"],
                code={"commit": "abc", "dirty": True},
                campaign=campaign,
                split="dev",
            )

    def test_formal_reviewed_method_requires_distinct_models(self) -> None:
        campaign = {
            "campaign_id": "c",
            "papers": [{"arxiv_id": "x", "split": "dev"}],
        }
        method = self.method()
        method["models"] = {"extractor": "same", "reviewer": "same"}
        with self.assertRaisesRegex(ValueError, "distinct"):
            build_run_config(
                run_id="r1",
                method=method,
                expected_papers=["x"],
                code={"commit": "abc", "dirty": False},
                campaign=campaign,
                split="dev",
            )

    def test_config_drift_and_sealed_write_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "r"
            config = self.config()
            ensure_run_config(run_dir, config)
            drift = {**config, "method_fingerprint": "different"}
            with self.assertRaisesRegex(ValueError, "drift"):
                ensure_run_config(run_dir, drift)
            (run_dir / "run_manifest.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "sealed"):
                ensure_run_config(run_dir, config)

    def test_retry_archives_failed_but_refuses_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            failed = run_dir / "x"
            failed.mkdir()
            (failed / "report.json").write_text('{"status":"transport_error"}')
            archived = prepare_paper_retry(run_dir, "x")
            self.assertTrue((archived / "report.json").is_file())
            success = run_dir / "y"
            success.mkdir()
            (success / "report.json").write_text('{"status":"ok"}')
            with self.assertRaisesRegex(ValueError, "successful"):
                prepare_paper_retry(run_dir, "y")

    def test_seal_lists_valid_invalid_missing_and_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "r"
            config = self.config()
            ensure_run_config(run_dir, config)
            paper = run_dir / "x"
            paper.mkdir()
            document = {
                "extraction": {
                    "provenance": {
                        "parameters": {
                            "method_fingerprint": config["method_fingerprint"]
                        }
                    }
                }
            }
            (paper / "literature_hvs_candidates.json").write_text(json.dumps(document))
            (paper / "report.json").write_text('{"status":"ok"}')
            (paper / "context_manifest.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "leakage audit"):
                seal_run(run_dir, workspace=root, validator_module=FakeValidator())
            audit_path = run_dir / "leakage_audit.json"
            audit_path.write_text(
                json.dumps(
                    {
                        "schema": {"name": "benchmark.leakage_audit", "version": 1},
                        "run_dir": str(run_dir.resolve()),
                        "files_scanned": 3,
                        "markers_scanned": 2,
                        "hits": [],
                        "status": "clean",
                    }
                )
            )
            manifest = seal_run(run_dir, workspace=root, validator_module=FakeValidator())
            self.assertEqual(manifest["papers"]["valid"], ["x"])
            self.assertEqual(manifest["leakage_audit"]["status"], "clean")
            self.assertEqual(manifest["leakage_audit"]["path"], "leakage_audit.json")
            self.assertEqual(len(manifest["leakage_audit"]["sha256"]), 64)
            with self.assertRaisesRegex(ValueError, "already sealed"):
                seal_run(run_dir, workspace=root, validator_module=FakeValidator())

    def test_contaminated_audit_can_seal_but_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "r"
            ensure_run_config(run_dir, self.config())
            (run_dir / "leakage_audit.json").write_text(
                json.dumps(
                    {
                        "schema": {"name": "benchmark.leakage_audit", "version": 1},
                        "run_dir": str(run_dir.resolve()),
                        "files_scanned": 1,
                        "markers_scanned": 2,
                        "hits": [{"marker": "synthetic"}],
                        "status": "contaminated",
                    }
                )
            )
            manifest = seal_run(run_dir, workspace=root, validator_module=FakeValidator())
            self.assertEqual(manifest["leakage_audit"]["status"], "contaminated")


if __name__ == "__main__":
    unittest.main()
