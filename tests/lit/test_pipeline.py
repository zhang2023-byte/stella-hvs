"""Unit tests for the literature pipeline operation adapters."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from stella.lit.catalog_assessment import assess
from stella.lit.catalog_extraction import extract
from stella.lit.catalog_review import review
from stella.lit.extraction.runner import (
    canonical_path,
    publish_canonical_document,
    run_paper,
    supersede_guard,
)
from stella.lit.hvs_contribution_catalog import build_timelines
from stella.lit.hvs_contributions_index import build
from stella.lit.pipeline import archive_assets, fetch

ROOT = Path(__file__).resolve().parents[2]


def _make_paper(root: Path, paper_id: str, *, with_catalog: bool = False) -> None:
    paper_dir = root / "literature" / paper_id
    (paper_dir / "assets").mkdir(parents=True, exist_ok=True)
    (paper_dir / "assets" / "main.tex").write_text("x\n", encoding="utf-8")
    if with_catalog:
        for name, artifact in (
            (
                "catalog_assessment.json",
                {"schema": {"name": "literature.title_triage", "version": 1}},
            ),
            (
                "catalog_review.json",
                {"schema": {"name": "article_data_assets.review", "version": 1}},
            ),
            (
                "catalog_extraction.json",
                {"schema": {"name": "article_data_assets.extraction", "version": 1}},
            ),
        ):
            (paper_dir / name).write_text(
                json.dumps(artifact), encoding="utf-8"
            )


class FetchAdapterTest(unittest.TestCase):
    def test_fetch_without_months_is_an_offline_no_op(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = fetch({}, root=Path(tmp))
            self.assertEqual(result["status"], "complete")
            self.assertIn("no fetch", result["detail"]["note"])


class ArchiveAdapterTest(unittest.TestCase):
    def test_archive_reports_present_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_paper(root, "2601.00001")
            result = archive_assets(
                {"papers": ["2601.00001"]}, root=root
            )
            self.assertEqual(result["status"], "complete")

    def test_archive_fails_closed_when_assets_missing_without_network(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_paper(root, "2601.00001")
            (root / "literature" / "2601.00001" / "assets" / "main.tex").unlink()
            (root / "literature" / "2601.00001" / "assets").rmdir()
            result = archive_assets({"papers": ["2601.00001"]}, root=root)
            self.assertEqual(result["status"], "failed")


class CatalogAdapterTest(unittest.TestCase):
    def test_catalog_operations_pass_validated_existing_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_paper(root, "2601.00001", with_catalog=True)
            payload = {"papers": ["2601.00001"]}
            self.assertEqual(
                assess(payload, root=root, paper_id="2601.00001")["status"],
                "complete",
            )
            self.assertEqual(
                review(payload, root=root, paper_id="2601.00001")["status"],
                "complete",
            )
            self.assertEqual(
                extract(payload, root=root, paper_id="2601.00001")["status"],
                "complete",
            )

    def test_catalog_operations_fail_closed_without_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_paper(root, "2601.00001")
            payload = {"papers": ["2601.00001"]}
            for adapter in (assess, review, extract):
                result = adapter(payload, root=root, paper_id="2601.00001")
                self.assertEqual(result["status"], "failed")
                self.assertTrue(result.get("next_action"))


class SupersedeGuardTest(unittest.TestCase):
    def test_missing_authority_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paper_id = "2601.00001"
            _make_paper(root, paper_id)
            target = canonical_path(root, paper_id)
            target.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(PermissionError, "supersede"):
                supersede_guard(root, paper_id, {"authorities": {"supersede": False}})

    def test_granted_authority_returns_previous_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paper_id = "2601.00001"
            _make_paper(root, paper_id)
            target = canonical_path(root, paper_id)
            payload = {"schema": {"name": "literature_hvs_contributions", "version": 1}}
            target.write_text(json.dumps(payload), encoding="utf-8")
            previous = supersede_guard(
                root, paper_id, {"authorities": {"supersede": True}}
            )
            self.assertIsNotNone(previous)
            self.assertEqual(len(previous), 64)

    def test_absent_target_needs_no_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_paper(root, "2601.00001")
            self.assertIsNone(supersede_guard(root, "2601.00001", {}))


class PublishAndRunPaperTest(unittest.TestCase):
    def test_run_paper_requires_llm_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_paper(
                {"papers": ["2601.00001"], "authorities": {}},
                root=Path(tmp),
                paper_id="2601.00001",
            )
            self.assertEqual(result["status"], "failed")
            self.assertIn("llm", result["blockers"])

    def test_publish_writes_atomically_and_rejects_without_supersede(
        self,
    ) -> None:
        import os
        import shutil

        from tests.hvs_contribution_fixtures import (
            MEASUREMENT_ARXIV_ID,
            MEASUREMENT_ROSTER_SUBMISSION,
            MEASUREMENT_SUBMISSION,
            frozen_contribution_config,
            make_measurement_workspace,
        )

        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as tmp2:
            root = Path(tmp)
            staged = Path(tmp2)
            make_measurement_workspace(str(staged))
            shutil.copytree(
                staged / "contracts", root / "contracts", dirs_exist_ok=True
            )
            shutil.copytree(
                staged / "literature", root / "literature", dirs_exist_ok=True
            )
            config_path = root / "config.json"
            transcript_path = root / "transcript.json"
            config_path.write_text(
                json.dumps(
                    frozen_contribution_config().model_dump(mode="json", by_alias=True)
                ),
                encoding="utf-8",
            )
            transcript_path.write_text(
                json.dumps(
                    {
                        "responses": [
                            {
                                "tool_name": "submit_contribution_roster",
                                "arguments": MEASUREMENT_ROSTER_SUBMISSION,
                            },
                            {
                                "tool_name": "submit_object_quantities",
                                "arguments": MEASUREMENT_SUBMISSION,
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            environment = {
                "STELLA_WORKER_METHOD_CONFIG": str(config_path),
                "STELLA_WORKER_TRANSCRIPT": str(transcript_path),
            }
            old_env = {key: os.environ.get(key) for key in environment}
            os.environ.update(environment)
            try:
                first = run_paper(
                    {
                        "papers": [MEASUREMENT_ARXIV_ID],
                        "authorities": {"llm": True},
                    },
                    root=root,
                    paper_id=MEASUREMENT_ARXIV_ID,
                )
                self.assertEqual(first["status"], "complete")
                self.assertTrue(
                    first["artifacts"][0].endswith(
                        "literature_hvs_contributions.json"
                    )
                )
                published = json.loads(
                    Path(first["artifacts"][0]).read_text(encoding="utf-8")
                )
                self.assertEqual(
                    published["extraction"]["roster_status"],
                    "contributions_found",
                )
                second = run_paper(
                    {
                        "papers": [MEASUREMENT_ARXIV_ID],
                        "authorities": {"llm": True},
                    },
                    root=root,
                    paper_id=MEASUREMENT_ARXIV_ID,
                )
                self.assertEqual(second["status"], "failed")
                self.assertIn(
                    "supersede", second["blockers"]
                )
            finally:
                for key, value in old_env.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value


class IndexAdapterTest(unittest.TestCase):
    def test_build_and_timelines_report_missing_documents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(build({}, root=root)["status"], "failed")
            self.assertEqual(build_timelines({}, root=root)["status"], "failed")


if __name__ == "__main__":
    unittest.main()
