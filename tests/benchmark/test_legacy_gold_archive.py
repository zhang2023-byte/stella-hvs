"""Transactional archival tests for same-expert V6 contribution migration."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from stella.benchmark.campaign import sha256_file
from stella.benchmark.gold import upgrade_annotation
from stella.benchmark.gold_selection import build_gold_selection
from stella.benchmark.hvs_contribution_gold_form import save_annotation, save_draft
from stella.schema_registry import ACTIVE_BENCHMARK_CAMPAIGN, schema_ref
from tests.benchmark.test_hvs_contribution_gold import fictional_annotation_payload


PAPER = "2601.00001"
EXPERT = "expert-a"
SELECTION_ID = "evaluation-dev-primary-v1"
PRESERVATION_REF = "v6-baseline"


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _legacy_annotation() -> dict:
    return {
        "schema": schema_ref("benchmark.gold_annotation"),
        "arxiv_id": PAPER,
        "annotator": EXPERT,
        "annotated_at": "2026-08-02",
        "guideline_version": "legacy-fixture",
        "evidence_basis": "pdf",
        "status": "no_candidates",
        "candidates": [],
        "notes": "Synthetic legacy fixture.",
    }


class LegacyGoldArchiveTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.workspace = root / "workspace"
        self.private_repo = root / "private-gold-repo"
        self.gold_dir = self.private_repo / "gold"
        self.work_dir = self.private_repo / "migration-work"
        self.workspace.mkdir()
        self.gold_dir.mkdir(parents=True)
        self.work_dir.mkdir()
        self._seed_public_selection_and_private_legacy()
        self._preserve_legacy_in_git()
        save_draft(fictional_annotation_payload(), self.work_dir)
        self._old_env = {
            "STELLA_GOLD_DIR": os.environ.get("STELLA_GOLD_DIR"),
            "STELLA_GOLD_WORK_DIR": os.environ.get("STELLA_GOLD_WORK_DIR"),
        }
        os.environ["STELLA_GOLD_DIR"] = str(self.gold_dir)
        os.environ["STELLA_GOLD_WORK_DIR"] = str(self.work_dir)

    def tearDown(self) -> None:
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    @property
    def legacy_yaml(self) -> Path:
        return self.gold_dir / PAPER / f"annotation_{EXPERT}.yaml"

    @property
    def legacy_json(self) -> Path:
        return self.gold_dir / PAPER / f"annotation_{EXPERT}.json"

    @property
    def archive_dir(self) -> Path:
        return self.private_repo / "legacy-v6" / PAPER

    def _seed_public_selection_and_private_legacy(self) -> None:
        paper_dir = self.gold_dir / PAPER
        paper_dir.mkdir()
        payload = _legacy_annotation()
        self.legacy_yaml.write_text(
            yaml.safe_dump(payload, sort_keys=False), encoding="utf-8"
        )
        self.legacy_json.write_text(
            json.dumps(upgrade_annotation(payload), ensure_ascii=False),
            encoding="utf-8",
        )
        records = [
            {
                "arxiv_id": PAPER,
                "file": path.relative_to(self.gold_dir).as_posix(),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
            for path in (self.legacy_json, self.legacy_yaml)
        ]
        manifest_dir = (
            self.workspace
            / "benchmark"
            / "campaigns"
            / ACTIVE_BENCHMARK_CAMPAIGN
            / "manifest"
        )
        manifest_dir.mkdir(parents=True)
        campaign_path = manifest_dir / "campaign_manifest.json"
        campaign_path.write_text(
            json.dumps(
                {
                    "schema": schema_ref("benchmark.campaign"),
                    "campaign_id": ACTIVE_BENCHMARK_CAMPAIGN,
                    "papers": [{"arxiv_id": PAPER, "split": "dev"}],
                }
            ),
            encoding="utf-8",
        )
        gold_manifest_path = manifest_dir / "gold_manifest.json"
        gold_manifest_path.write_text(
            json.dumps(
                {
                    "schema": schema_ref("benchmark.gold_manifest"),
                    "files": sorted(records, key=lambda item: item["file"]),
                }
            ),
            encoding="utf-8",
        )
        selection = build_gold_selection(
            campaign_path=campaign_path,
            gold_manifest_path=gold_manifest_path,
            gold_dir=self.gold_dir,
            split="dev",
            selection_id=SELECTION_ID,
            annotator_map={PAPER: EXPERT},
        )
        selection_dir = manifest_dir / "gold_selections"
        selection_dir.mkdir()
        (selection_dir / f"{SELECTION_ID}.json").write_text(
            json.dumps(selection), encoding="utf-8"
        )

    def _preserve_legacy_in_git(self) -> None:
        _run_git(self.private_repo, "init", "-q")
        _run_git(self.private_repo, "add", "gold")
        _run_git(
            self.private_repo,
            "-c",
            "user.name=Stella Test",
            "-c",
            "user.email=stella@example.invalid",
            "commit",
            "-qm",
            "preserve v6",
        )
        _run_git(self.private_repo, "tag", PRESERVATION_REF)

    def _request(self, *, supersede: bool = True, ref: str = PRESERVATION_REF) -> dict:
        return {
            "expert": EXPERT,
            "papers": [PAPER],
            "expert_approved": True,
            "legacy_selection_id": SELECTION_ID,
            "legacy_preservation_ref": ref,
            "authorities": {
                "gold_private": True,
                "supersede": supersede,
            },
        }

    def test_existing_legacy_requires_explicit_supersede(self) -> None:
        yaml_before = self.legacy_yaml.read_bytes()
        json_before = self.legacy_json.read_bytes()

        result = save_annotation(
            self._request(supersede=False),
            root=self.workspace,
            paper_id=PAPER,
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.legacy_yaml.read_bytes(), yaml_before)
        self.assertEqual(self.legacy_json.read_bytes(), json_before)
        self.assertFalse(self.archive_dir.exists())

    def test_matching_selection_and_ref_archive_pair_before_json_only_save(self) -> None:
        yaml_before = self.legacy_yaml.read_bytes()
        json_before = self.legacy_json.read_bytes()

        result = save_annotation(
            self._request(), root=self.workspace, paper_id=PAPER
        )

        self.assertEqual(result["status"], "complete", result)
        self.assertFalse(self.legacy_yaml.exists())
        new_document = json.loads(self.legacy_json.read_text(encoding="utf-8"))
        self.assertEqual(
            new_document["schema"],
            schema_ref("benchmark.hvs_contribution_annotation"),
        )
        archived_yaml = self.archive_dir / f"annotation_{EXPERT}_old.yaml"
        archived_json = self.archive_dir / f"annotation_{EXPERT}_old.json"
        self.assertEqual(archived_yaml.read_bytes(), yaml_before)
        self.assertEqual(archived_json.read_bytes(), json_before)
        self.assertFalse((self.work_dir / PAPER).exists())
        detail = result["detail"]["save"]["legacy_archive"]
        self.assertEqual(detail["selection_id"], SELECTION_ID)
        self.assertEqual(detail["preservation_ref"], PRESERVATION_REF)

    def test_hash_mismatch_fails_without_moving_legacy(self) -> None:
        original_yaml = self.legacy_yaml.read_bytes()
        self.legacy_json.write_text("{}", encoding="utf-8")
        tampered_json = self.legacy_json.read_bytes()

        result = save_annotation(
            self._request(), root=self.workspace, paper_id=PAPER
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.legacy_yaml.read_bytes(), original_yaml)
        self.assertEqual(self.legacy_json.read_bytes(), tampered_json)
        self.assertFalse(self.archive_dir.exists())

    def test_publish_failure_rolls_legacy_pair_back(self) -> None:
        yaml_before = self.legacy_yaml.read_bytes()
        json_before = self.legacy_json.read_bytes()

        with patch(
            "stella.benchmark.hvs_contribution_gold_form._expert_save_annotation",
            side_effect=RuntimeError("synthetic publish failure"),
        ):
            result = save_annotation(
                self._request(), root=self.workspace, paper_id=PAPER
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.legacy_yaml.read_bytes(), yaml_before)
        self.assertEqual(self.legacy_json.read_bytes(), json_before)
        self.assertFalse(self.archive_dir.exists())

    def test_post_replace_failure_removes_new_json_and_restores_legacy(self) -> None:
        yaml_before = self.legacy_yaml.read_bytes()
        json_before = self.legacy_json.read_bytes()

        def fail_after_replace(*args, **kwargs):
            self.legacy_json.write_text('{"partial": true}', encoding="utf-8")
            raise RuntimeError("synthetic post-replace failure")

        with patch(
            "stella.benchmark.hvs_contribution_gold_form._expert_save_annotation",
            side_effect=fail_after_replace,
        ):
            result = save_annotation(
                self._request(), root=self.workspace, paper_id=PAPER
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.legacy_yaml.read_bytes(), yaml_before)
        self.assertEqual(self.legacy_json.read_bytes(), json_before)
        self.assertFalse(self.archive_dir.exists())

    def test_existing_archive_fails_without_moving_active_legacy(self) -> None:
        yaml_before = self.legacy_yaml.read_bytes()
        json_before = self.legacy_json.read_bytes()
        self.archive_dir.mkdir(parents=True)
        (self.archive_dir / f"annotation_{EXPERT}_old.json").write_text(
            "{}", encoding="utf-8"
        )

        result = save_annotation(
            self._request(), root=self.workspace, paper_id=PAPER
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.legacy_yaml.read_bytes(), yaml_before)
        self.assertEqual(self.legacy_json.read_bytes(), json_before)

    def test_missing_preservation_ref_fails_without_moving_legacy(self) -> None:
        result = save_annotation(
            self._request(ref="missing-ref"),
            root=self.workspace,
            paper_id=PAPER,
        )

        self.assertEqual(result["status"], "failed")
        self.assertTrue(self.legacy_yaml.is_file())
        self.assertTrue(self.legacy_json.is_file())
        self.assertFalse(self.archive_dir.exists())


if __name__ == "__main__":
    unittest.main()
