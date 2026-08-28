"""Fail-closed Git-backed revision of already-migrated contribution Gold."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from stella.benchmark.campaign import sha256_file
from stella.benchmark.contribution_gold_revision import (
    load_selected_contribution_annotation,
    revision_backup_path,
    revision_lock_path,
)
from stella.benchmark.gold_selection import prepare_selection
from stella.benchmark.hvs_contribution_gold import (
    HvsContributionGoldAnnotation,
    contribution_gold_json_document,
)
from stella.benchmark.hvs_contribution_gold_form import (
    annotation_json_path,
    save_annotation,
    save_draft,
    save_expert_annotation,
    validate_save_gate,
)
from tests.benchmark.test_hvs_contribution_gold import fictional_annotation_payload


PAPER = "2601.00001"
EXPERT = "expert-a"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )


class ContributionGoldRevisionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.workspace = root / "workspace"
        self.private_repo = root / "private-repo"
        self.gold_dir = self.private_repo / "gold"
        self.work_dir = self.private_repo / "migration-work"
        self.workspace.mkdir()
        self.gold_dir.mkdir(parents=True)
        self.work_dir.mkdir()
        (self.private_repo / ".gitignore").write_text(
            "migration-work/\n", encoding="utf-8"
        )
        self.assertEqual(_git(self.private_repo, "init", "-q").returncode, 0)

        old = fictional_annotation_payload()
        old["guideline_version"] = "old-guideline"
        save_expert_annotation(old, self.gold_dir, expert_approved=True)
        self.active = annotation_json_path(self.gold_dir, PAPER, EXPERT)
        self.old_bytes = self.active.read_bytes()
        self.old_sha = sha256_file(self.active)

        draft = fictional_annotation_payload()
        draft["guideline_version"] = "new-guideline"
        save_draft(draft, self.work_dir)

        self.legacy_archive_dir = self.private_repo / "legacy-v6" / PAPER
        self.legacy_archive_dir.mkdir(parents=True)
        (self.legacy_archive_dir / f"annotation_{EXPERT}_old.json").write_bytes(
            b"legacy-v6-json-must-not-change\n"
        )
        (self.legacy_archive_dir / f"annotation_{EXPERT}_old.yaml").write_bytes(
            b"legacy-v6-yaml-must-not-change\n"
        )
        self.legacy_before = self._legacy_archive_snapshot()
        self.assertEqual(
            _git(
                self.private_repo,
                "add",
                ".gitignore",
                "gold",
                "legacy-v6",
            ).returncode,
            0,
        )
        committed = _git(
            self.private_repo,
            "-c",
            "user.name=Test User",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-q",
            "-m",
            "base Gold",
        )
        self.assertEqual(committed.returncode, 0, committed.stderr)
        self.base_commit = _git(self.private_repo, "rev-parse", "HEAD").stdout.strip()

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

    def _request(self, **updates: object) -> dict:
        request: dict[str, object] = {
            "expert": EXPERT,
            "papers": [PAPER],
            "expert_approved": True,
            "retain_migration_work": True,
            "expected_current_sha256": self.old_sha,
            "authorities": {"gold_private": True, "supersede": True},
        }
        request.update(updates)
        return request

    def _legacy_archive_snapshot(self) -> dict[str, bytes]:
        return {
            path.name: path.read_bytes()
            for path in sorted(self.legacy_archive_dir.iterdir())
            if path.is_file()
        }

    def _failing_lock_exit(self):
        from stella.benchmark import contribution_gold_revision as revision

        real_lock = revision._held_revision_lock

        @contextmanager
        def fail_after_release(**kwargs):
            with real_lock(**kwargs) as lock:
                yield lock
            raise RuntimeError("synthetic lock release failure")

        return fail_after_release

    def _current_entry(self) -> dict[str, str]:
        return {
            "arxiv_id": PAPER,
            "selected_expert": EXPERT,
            "annotation_file": f"annotation_{EXPERT}.json",
            "sha256": sha256_file(self.active),
        }

    def test_revision_requires_gold_approval_supersede_and_current_sha(self) -> None:
        cases = (
            ({"authorities": {"gold_private": False, "supersede": True}}, "gold_private"),
            ({"expert_approved": False}, "expert approval"),
            ({"authorities": {"gold_private": True, "supersede": False}}, "supersede"),
            ({"expected_current_sha256": None}, "current SHA"),
        )
        for updates, expected in cases:
            with self.subTest(expected=expected):
                result = save_annotation(
                    self._request(**updates),
                    root=self.workspace,
                    paper_id=PAPER,
                )
                self.assertEqual(result["status"], "failed")
                self.assertIn(expected, json.dumps(result))
                self.assertEqual(self.active.read_bytes(), self.old_bytes)

    def test_revision_requires_retained_migration_work(self) -> None:
        result = save_annotation(
            self._request(retain_migration_work=False),
            root=self.workspace,
            paper_id=PAPER,
        )

        self.assertEqual(result["status"], "failed")
        self.assertIn("retain", json.dumps(result))
        self.assertEqual(self.active.read_bytes(), self.old_bytes)

    def test_retained_artifact_listing_failure_precedes_replacement(self) -> None:
        with patch(
            "stella.benchmark.hvs_contribution_gold_form.existing_migration_artifacts",
            side_effect=OSError("synthetic retained-list failure"),
        ):
            result = save_annotation(
                self._request(), root=self.workspace, paper_id=PAPER
            )

        self.assertEqual(result["status"], "failed")
        self.assertIn("retained-list failure", json.dumps(result))
        self.assertEqual(self.active.read_bytes(), self.old_bytes)

    def test_revision_requires_the_active_gold_to_match_private_head(self) -> None:
        uncommitted = fictional_annotation_payload()
        uncommitted["guideline_version"] = "uncommitted-guideline"
        document = contribution_gold_json_document(
            HvsContributionGoldAnnotation.model_validate(uncommitted)
        )
        self.active.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        uncommitted_bytes = self.active.read_bytes()

        result = save_annotation(
            self._request(expected_current_sha256=sha256_file(self.active)),
            root=self.workspace,
            paper_id=PAPER,
        )

        self.assertEqual(result["status"], "failed")
        self.assertIn("Git HEAD", json.dumps(result))
        self.assertEqual(self.active.read_bytes(), uncommitted_bytes)

    def test_expected_sha_mismatch_fails_before_replacement(self) -> None:
        result = save_annotation(
            self._request(expected_current_sha256="2" * 64),
            root=self.workspace,
            paper_id=PAPER,
        )

        self.assertEqual(result["status"], "failed")
        self.assertIn("drifted", json.dumps(result))
        self.assertEqual(self.active.read_bytes(), self.old_bytes)

    def test_success_uses_git_history_and_leaves_no_permanent_sidecar(self) -> None:
        result = save_annotation(
            self._request(), root=self.workspace, paper_id=PAPER
        )

        self.assertEqual(result["status"], "complete", result)
        self.assertNotEqual(self.active.read_bytes(), self.old_bytes)
        self.assertEqual(self._legacy_archive_snapshot(), self.legacy_before)
        self.assertFalse((self.private_repo / "contribution-history").exists())
        self.assertFalse(revision_lock_path(self.work_dir, PAPER, EXPERT).exists())
        self.assertFalse(revision_backup_path(self.work_dir, PAPER, EXPERT).exists())
        save_detail = result["detail"]["save"]
        self.assertEqual(save_detail["previous_git_commit"], self.base_commit)
        self.assertNotIn("history_object", save_detail)
        self.assertNotIn("receipt", save_detail)
        self.assertEqual(save_detail["deleted_temporary_artifacts"], [])
        self.assertEqual(len(save_detail["retained_migration_artifacts"]), 1)

        selected = load_selected_contribution_annotation(
            self.gold_dir, self._current_entry()
        )
        self.assertEqual(selected["guideline_version"], "new-guideline")
        prepared = prepare_selection(
            {
                "expert": EXPERT,
                "papers": [PAPER],
                "selection_id": "post-revision-v1",
            },
            root=self.workspace,
        )
        self.assertEqual(prepared["status"], "complete", prepared)

        validation_result = dict(result)
        validation_result["paper_id"] = PAPER
        with patch(
            "stella.benchmark.hvs_contribution_gold_form.existing_migration_artifacts",
            side_effect=AssertionError("revision gate must use the retained snapshot"),
        ):
            self.assertEqual(
                validate_save_gate(
                    self._request(), validation_result, root=self.workspace
                ),
                [],
            )

    def test_nonignored_lock_directory_fails_closed(self) -> None:
        unignored = self.private_repo / "unignored-work"
        unignored.mkdir()
        os.environ["STELLA_GOLD_WORK_DIR"] = str(unignored)
        save_draft(fictional_annotation_payload(), unignored)

        result = save_annotation(
            self._request(), root=self.workspace, paper_id=PAPER
        )

        self.assertEqual(result["status"], "failed")
        self.assertIn("ignored", json.dumps(result))
        self.assertEqual(self.active.read_bytes(), self.old_bytes)

    def test_existing_lock_or_backup_fails_closed(self) -> None:
        paths = (
            revision_lock_path(self.work_dir, PAPER, EXPERT),
            revision_backup_path(self.work_dir, PAPER, EXPERT),
        )
        for path in paths:
            with self.subTest(path=path.name):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("held\n", encoding="utf-8")
                result = save_annotation(
                    self._request(), root=self.workspace, paper_id=PAPER
                )
                self.assertEqual(result["status"], "failed")
                self.assertEqual(self.active.read_bytes(), self.old_bytes)
                path.unlink()

    def test_concurrent_sha_drift_is_caught_after_backup(self) -> None:
        from stella.benchmark import contribution_gold_revision as revision

        real_write = revision._write_revision_backup_once

        def drift_after_backup(*args, **kwargs):
            real_write(*args, **kwargs)
            self.active.write_bytes(b"concurrent-change\n")

        with patch.object(
            revision, "_write_revision_backup_once", side_effect=drift_after_backup
        ):
            result = save_annotation(
                self._request(), root=self.workspace, paper_id=PAPER
            )

        self.assertEqual(result["status"], "failed")
        self.assertIn("drift", json.dumps(result))
        self.assertEqual(self.active.read_bytes(), b"concurrent-change\n")
        self.assertFalse(revision_backup_path(self.work_dir, PAPER, EXPERT).exists())

    def test_lint_failure_precedes_backup_and_replacement(self) -> None:
        from stella.benchmark import contribution_gold_revision as revision

        with patch.object(
            revision,
            "lint_contribution_annotation",
            side_effect=RuntimeError("synthetic lint failure"),
        ):
            result = save_annotation(
                self._request(), root=self.workspace, paper_id=PAPER
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.active.read_bytes(), self.old_bytes)
        self.assertFalse(revision_backup_path(self.work_dir, PAPER, EXPERT).exists())

    def test_lock_release_failure_rolls_canonical_bytes_back(self) -> None:
        from stella.benchmark import contribution_gold_revision as revision

        with patch.object(
            revision,
            "_held_revision_lock",
            side_effect=self._failing_lock_exit(),
        ):
            result = save_annotation(
                self._request(), root=self.workspace, paper_id=PAPER
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.active.read_bytes(), self.old_bytes)
        self.assertFalse(revision_backup_path(self.work_dir, PAPER, EXPERT).exists())

    def test_backup_cleanup_failure_rolls_back_from_memory(self) -> None:
        from stella.benchmark import contribution_gold_revision as revision

        real_remove = revision._remove_revision_backup

        def fail_after_removal(path: Path) -> None:
            real_remove(path)
            raise OSError("synthetic backup cleanup failure")

        with patch.object(
            revision, "_remove_revision_backup", side_effect=fail_after_removal
        ):
            result = save_annotation(
                self._request(), root=self.workspace, paper_id=PAPER
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.active.read_bytes(), self.old_bytes)
        self.assertFalse(revision_backup_path(self.work_dir, PAPER, EXPERT).exists())

    def test_post_replace_failure_rolls_canonical_bytes_back(self) -> None:
        from stella.benchmark import contribution_gold_revision as revision

        real_replace = revision._atomic_replace_bytes
        calls = 0

        def fail_after_first_replace(path: Path, payload: bytes) -> None:
            nonlocal calls
            calls += 1
            real_replace(path, payload)
            if calls == 1:
                raise RuntimeError("synthetic post-replace failure")

        with patch.object(
            revision, "_atomic_replace_bytes", side_effect=fail_after_first_replace
        ):
            result = save_annotation(
                self._request(), root=self.workspace, paper_id=PAPER
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.active.read_bytes(), self.old_bytes)
        self.assertGreaterEqual(calls, 2)
        self.assertFalse(revision_backup_path(self.work_dir, PAPER, EXPERT).exists())

    def test_old_selection_does_not_fall_back_after_active_revision(self) -> None:
        old_entry = self._current_entry()
        result = save_annotation(
            self._request(), root=self.workspace, paper_id=PAPER
        )
        self.assertEqual(result["status"], "complete", result)

        with self.assertRaisesRegex(ValueError, "active canonical"):
            load_selected_contribution_annotation(self.gold_dir, old_entry)

if __name__ == "__main__":
    unittest.main()
