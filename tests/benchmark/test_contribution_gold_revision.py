"""Fail-closed revision of already-migrated contribution Gold."""

from __future__ import annotations

import hashlib
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
    contribution_history_object_path,
    load_selected_contribution_annotation,
    revision_lock_path,
)
from stella.benchmark.gold_selection import prepare_selection
from stella.benchmark.hvs_contribution_gold import (
    HvsContributionGoldAnnotation,
    contribution_gold_json_document,
)
from stella.benchmark.hvs_contribution_gold_form import (
    annotation_json_path,
    load_draft,
    save_annotation,
    save_draft,
    save_expert_annotation,
    validate_save_gate,
)
from stella.schema_registry import schema_ref
from tests.benchmark.test_hvs_contribution_gold import fictional_annotation_payload


PAPER = "2601.00001"
EXPERT = "expert-a"
BASE_SELECTION_ID = "contribution-base-v1"


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
        self._write_base_selection()

        draft = fictional_annotation_payload()
        draft["guideline_version"] = "new-guideline"
        save_draft(draft, self.work_dir)

        self.legacy_archive_dir = (
            self.private_repo
            / "legacy-v6"
            / PAPER
        )
        self.legacy_archive_dir.mkdir(parents=True)
        (self.legacy_archive_dir / f"annotation_{EXPERT}_old.json").write_bytes(
            b"legacy-v6-json-must-not-change\n"
        )
        (self.legacy_archive_dir / f"annotation_{EXPERT}_old.yaml").write_bytes(
            b"legacy-v6-yaml-must-not-change\n"
        )
        self.legacy_before = self._legacy_archive_snapshot()

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
    def selection_path(self) -> Path:
        return (
            self.workspace
            / "benchmark"
            / "gold_selections"
            / f"{BASE_SELECTION_ID}.json"
        )

    def _write_base_selection(self, **entry_updates: object) -> None:
        entry = {
            "arxiv_id": PAPER,
            "selected_expert": EXPERT,
            "annotation_file": f"annotation_{EXPERT}.json",
            "sha256": self.old_sha,
        }
        entry.update(entry_updates)
        payload = {
            "schema": schema_ref("benchmark.hvs_contribution_gold_selection"),
            "selection_id": BASE_SELECTION_ID,
            "target_schema": schema_ref("benchmark.hvs_contribution_annotation"),
            "papers": [entry],
        }
        self.selection_path.parent.mkdir(parents=True, exist_ok=True)
        self.selection_path.write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )

    def _request(self, **updates: object) -> dict:
        request: dict[str, object] = {
            "expert": EXPERT,
            "papers": [PAPER],
            "expert_approved": True,
            "retain_migration_work": True,
            "base_selection_id": BASE_SELECTION_ID,
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

    def _revision_receipt(self) -> dict[str, str]:
        from stella.benchmark import contribution_gold_revision as revision

        draft = load_draft(self.work_dir, PAPER, EXPERT)
        annotation = HvsContributionGoldAnnotation.model_validate(draft)
        replacement = (
            json.dumps(
                contribution_gold_json_document(annotation),
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        ).encode("utf-8")
        return revision._receipt_document(
            paper_id=PAPER,
            annotator=EXPERT,
            base_selection_id=BASE_SELECTION_ID,
            previous_sha256=self.old_sha,
            replacement_sha256=hashlib.sha256(replacement).hexdigest(),
        )

    def _failing_lock_exit(self):
        from stella.benchmark import contribution_gold_revision as revision

        real_lock = revision._held_revision_lock

        @contextmanager
        def fail_after_release(**kwargs):
            with real_lock(**kwargs) as lock:
                yield lock
            raise RuntimeError("synthetic lock release failure")

        return fail_after_release

    def test_revision_requires_gold_approval_supersede_and_both_pins(self) -> None:
        cases = (
            ({"authorities": {"gold_private": False, "supersede": True}}, "gold_private"),
            ({"expert_approved": False}, "expert approval"),
            ({"authorities": {"gold_private": True, "supersede": False}}, "supersede"),
            ({"base_selection_id": None}, "base selection"),
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
                rendered = json.dumps(result)
                self.assertIn(expected, rendered)
                self.assertEqual(self.active.read_bytes(), self.old_bytes)

    def test_revision_requires_retained_migration_work_before_history(self) -> None:
        result = save_annotation(
            self._request(retain_migration_work=False),
            root=self.workspace,
            paper_id=PAPER,
        )

        self.assertEqual(result["status"], "failed")
        self.assertIn("retain", json.dumps(result))
        self.assertEqual(self.active.read_bytes(), self.old_bytes)
        self.assertFalse(
            contribution_history_object_path(self.gold_dir, self.old_sha).exists()
        )

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
        self.assertFalse(
            contribution_history_object_path(self.gold_dir, self.old_sha).exists()
        )

    def test_selection_identity_and_sha_mismatches_fail_before_history(self) -> None:
        cases = (
            ({"selected_expert": "other-expert"}, self.old_sha),
            ({"annotation_file": "annotation_other.json"}, self.old_sha),
            ({"sha256": "1" * 64}, self.old_sha),
            ({}, "2" * 64),
        )
        for entry_updates, expected_sha in cases:
            with self.subTest(entry_updates=entry_updates, expected_sha=expected_sha):
                self._write_base_selection(**entry_updates)
                result = save_annotation(
                    self._request(expected_current_sha256=expected_sha),
                    root=self.workspace,
                    paper_id=PAPER,
                )
                self.assertEqual(result["status"], "failed")
                self.assertEqual(self.active.read_bytes(), self.old_bytes)
                self.assertFalse(
                    contribution_history_object_path(
                        self.gold_dir, self.old_sha
                    ).exists()
                )

    def test_success_preserves_history_receipt_archive_and_inventory_isolation(self) -> None:
        result = save_annotation(
            self._request(), root=self.workspace, paper_id=PAPER
        )

        self.assertEqual(result["status"], "complete", result)
        self.assertEqual(
            (result.get("detail") or {}).get("superseded_previous_sha256"),
            self.old_sha,
        )
        self.assertNotEqual(self.active.read_bytes(), self.old_bytes)
        history = contribution_history_object_path(self.gold_dir, self.old_sha)
        self.assertEqual(history.read_bytes(), self.old_bytes)
        receipts = list(
            (self.private_repo / "contribution-history" / "receipts").glob("*.json")
        )
        self.assertEqual(len(receipts), 1)
        receipt_bytes = receipts[0].read_bytes()
        self.assertEqual(receipts[0].stem, hashlib.sha256(receipt_bytes).hexdigest())
        receipt = json.loads(receipt_bytes)
        self.assertEqual(
            set(receipt),
            {
                "operation",
                "paper_id",
                "annotator",
                "base_selection_id",
                "previous_sha256",
                "replacement_sha256",
                "active_annotation_file",
            },
        )
        self.assertEqual(self._legacy_archive_snapshot(), self.legacy_before)
        save_detail = result["detail"]["save"]
        self.assertEqual(save_detail["deleted_temporary_artifacts"], [])
        self.assertEqual(
            save_detail["retained_migration_artifacts"],
            [
                str(
                    (
                        self.work_dir
                        / PAPER
                        / f"draft_{EXPERT}.json"
                    ).resolve()
                )
            ],
        )
        self.assertFalse((self.gold_dir / "contribution-history").exists())
        self.assertNotEqual(
            _git(
                self.private_repo,
                "check-ignore",
                "-q",
                "--",
                history.relative_to(self.private_repo.resolve()).as_posix(),
            ).returncode,
            0,
        )
        self.assertNotEqual(
            _git(
                self.private_repo,
                "check-ignore",
                "-q",
                "--",
                receipts[0].resolve().relative_to(self.private_repo.resolve()).as_posix(),
            ).returncode,
            0,
        )
        private_status = _git(
            self.private_repo, "status", "--short", "--untracked-files=all"
        ).stdout
        self.assertIn("contribution-history/objects/", private_status)
        self.assertIn("contribution-history/receipts/", private_status)

        prepared = prepare_selection(
            {
                "expert": EXPERT,
                "papers": [PAPER],
                "selection_id": "post-revision-v1",
            },
            root=self.workspace,
        )
        self.assertEqual(prepared["status"], "complete", prepared)
        entries = (prepared.get("detail") or {})["selection"]["papers"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["arxiv_id"], PAPER)

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

    def test_existing_lock_fails_closed(self) -> None:
        lock = revision_lock_path(self.work_dir, PAPER, EXPERT)
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("held\n", encoding="utf-8")

        result = save_annotation(
            self._request(), root=self.workspace, paper_id=PAPER
        )

        self.assertEqual(result["status"], "failed")
        self.assertIn("lock", json.dumps(result))
        self.assertEqual(self.active.read_bytes(), self.old_bytes)

    def test_concurrent_sha_drift_is_caught_by_second_check(self) -> None:
        from stella.benchmark import contribution_gold_revision as revision

        real_write = revision._write_history_object_once

        def drift_after_history(*args, **kwargs):
            outcome = real_write(*args, **kwargs)
            self.active.write_bytes(b"concurrent-change\n")
            return outcome

        with patch.object(
            revision, "_write_history_object_once", side_effect=drift_after_history
        ):
            result = save_annotation(
                self._request(), root=self.workspace, paper_id=PAPER
            )

        self.assertEqual(result["status"], "failed")
        self.assertIn("drift", json.dumps(result))
        self.assertEqual(self.active.read_bytes(), b"concurrent-change\n")
        self.assertEqual(
            contribution_history_object_path(
                self.gold_dir, self.old_sha
            ).read_bytes(),
            self.old_bytes,
        )

    def test_receipt_failure_rolls_canonical_bytes_back(self) -> None:
        with patch(
            "stella.benchmark.contribution_gold_revision._write_receipt_once",
            side_effect=RuntimeError("synthetic receipt failure"),
        ):
            result = save_annotation(
                self._request(), root=self.workspace, paper_id=PAPER
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.active.read_bytes(), self.old_bytes)
        self.assertEqual(self._legacy_archive_snapshot(), self.legacy_before)

    def test_lint_failure_precedes_history_receipt_and_replacement(self) -> None:
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
        self.assertFalse(
            contribution_history_object_path(self.gold_dir, self.old_sha).exists()
        )
        receipt_dir = self.private_repo / "contribution-history" / "receipts"
        self.assertEqual(list(receipt_dir.glob("*.json")), [])

    def test_lock_release_failure_rolls_back_and_removes_new_receipt(self) -> None:
        from stella.benchmark import contribution_gold_revision as revision

        real_fsync = revision._fsync_directory
        receipt_dir = self.private_repo / "contribution-history" / "receipts"
        with patch.object(
            revision, "_fsync_directory", wraps=real_fsync
        ) as fsync_directory, patch.object(
            revision,
            "_held_revision_lock",
            side_effect=self._failing_lock_exit(),
        ):
            result = save_annotation(
                self._request(), root=self.workspace, paper_id=PAPER
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.active.read_bytes(), self.old_bytes)
        self.assertEqual(
            contribution_history_object_path(
                self.gold_dir, self.old_sha
            ).read_bytes(),
            self.old_bytes,
        )
        self.assertEqual(list(receipt_dir.glob("*.json")), [])
        receipt_fsyncs = [
            call
            for call in fsync_directory.call_args_list
            if call.args[0] == receipt_dir.resolve()
        ]
        self.assertEqual(len(receipt_fsyncs), 2)

    def test_lock_release_failure_keeps_preexisting_same_receipt(self) -> None:
        from stella.benchmark import contribution_gold_revision as revision

        receipt = self._revision_receipt()
        receipt_path, created = revision._write_receipt_once(
            self.gold_dir, receipt
        )
        self.assertTrue(created)
        receipt_before = receipt_path.read_bytes()

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
        self.assertEqual(receipt_path.read_bytes(), receipt_before)

    def test_receipt_is_idempotent_for_same_content_and_rejects_collision(self) -> None:
        from stella.benchmark import contribution_gold_revision as revision

        receipt = revision._receipt_document(
            paper_id=PAPER,
            annotator=EXPERT,
            base_selection_id=BASE_SELECTION_ID,
            previous_sha256=self.old_sha,
            replacement_sha256="3" * 64,
        )
        first, first_created = revision._write_receipt_once(
            self.gold_dir, receipt
        )
        second, second_created = revision._write_receipt_once(
            self.gold_dir, receipt
        )
        self.assertEqual(first, second)
        self.assertTrue(first_created)
        self.assertFalse(second_created)
        first.write_text("{}\n", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "collision"):
            revision._write_receipt_once(self.gold_dir, receipt)

    def test_content_addressed_fsync_failure_removes_new_link(self) -> None:
        from stella.benchmark import contribution_gold_revision as revision

        target = self.private_repo / "contribution-history" / "objects" / "new.json"
        with patch.object(
            revision,
            "_fsync_directory",
            side_effect=OSError("synthetic directory fsync failure"),
        ):
            with self.assertRaisesRegex(OSError, "directory fsync failure"):
                revision._write_content_addressed_once(target, b"new payload\n")

        self.assertFalse(target.exists())

    def test_content_addressed_fsync_failure_does_not_remove_existing_link(self) -> None:
        from stella.benchmark import contribution_gold_revision as revision

        payload = b"concurrent payload\n"
        target = (
            self.private_repo
            / "contribution-history"
            / "objects"
            / "concurrent.json"
        )

        def concurrent_link(_source, destination) -> None:
            Path(destination).write_bytes(payload)
            raise FileExistsError("synthetic concurrent target")

        with patch.object(
            revision.os, "link", side_effect=concurrent_link
        ), patch.object(
            revision,
            "_fsync_directory",
            side_effect=OSError("synthetic directory fsync failure"),
        ):
            with self.assertRaisesRegex(OSError, "directory fsync failure"):
                revision._write_content_addressed_once(target, payload)

        self.assertEqual(target.read_bytes(), payload)

    def test_content_addressed_temp_cleanup_failure_removes_new_link(self) -> None:
        from stella.benchmark import contribution_gold_revision as revision

        target = (
            self.private_repo
            / "contribution-history"
            / "objects"
            / "cleanup.json"
        )
        real_unlink = Path.unlink

        def fail_temporary_unlink(path: Path, *args, **kwargs) -> None:
            if path.name.startswith(".cleanup.json.") and path.name.endswith(".tmp"):
                raise OSError("synthetic temporary cleanup failure")
            real_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", new=fail_temporary_unlink):
            with self.assertRaisesRegex(OSError, "temporary cleanup failure"):
                revision._write_content_addressed_once(target, b"new payload\n")

        self.assertFalse(target.exists())

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

    def test_old_selection_resolves_history_after_active_revision(self) -> None:
        entry = json.loads(self.selection_path.read_text(encoding="utf-8"))["papers"][0]
        result = save_annotation(
            self._request(), root=self.workspace, paper_id=PAPER
        )
        self.assertEqual(result["status"], "complete", result)

        selected = load_selected_contribution_annotation(self.gold_dir, entry)

        self.assertEqual(
            json.dumps(selected, sort_keys=True),
            json.dumps(json.loads(self.old_bytes), sort_keys=True),
        )


if __name__ == "__main__":
    unittest.main()
