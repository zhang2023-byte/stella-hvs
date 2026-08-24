"""Offline end-to-end tests for the literature_pipeline workflow.

Fake transports and fixture literature replace every network or model call.
The tests prove: plan/preflight for one and many papers, one fresh worker
process per paper, independent paper failure yielding a partial run with
validated successes preserved, the explicit supersede authority with
previous-hash events, and the artifact chain through indexes and timelines.
No benchmark path or private gold location is read or written.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from stella import workflow_runtime
from stella.workflows import (
    Authorities,
    LiteraturePipelineRequest,
    load_workflow_catalog,
)
from tests.integration.netguard import guard
from tests.hvs_contribution_fixtures import (
    ARXIV_ID,
    FULL_SUBMISSION,
    MEASUREMENT_ARXIV_ID,
    MEASUREMENT_ROSTER_SUBMISSION,
    MEASUREMENT_SUBMISSION,
    frozen_contribution_config,
    make_measurement_workspace,
    make_workspace,
)

ROOT = Path(__file__).resolve().parents[2]


def _merge_workspace(root: Path, staged: Path) -> None:
    shutil.copytree(staged / "contracts", root / "contracts", dirs_exist_ok=True)
    shutil.copytree(staged / "literature", root / "literature", dirs_exist_ok=True)


def _write_catalog_artifacts(root: Path, paper_id: str) -> None:
    paper_dir = root / "literature" / paper_id
    paper_dir.mkdir(parents=True, exist_ok=True)
    (paper_dir / "assets").mkdir(exist_ok=True)
    for name, schema_name in (
        ("catalog_assessment.json", "literature.title_triage"),
        ("catalog_review.json", "article_data_assets.review"),
        ("catalog_extraction.json", "article_data_assets.extraction"),
    ):
        (paper_dir / name).write_text(
            json.dumps({"schema": {"name": schema_name, "version": 1}}),
            encoding="utf-8",
        )


def _write_worker_inputs(root: Path, responses: list[dict]) -> dict[str, str]:
    config_path = root / "worker" / "method_config.json"
    transcript_path = root / "worker" / "transcript.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            frozen_contribution_config().model_dump(mode="json", by_alias=True)
        ),
        encoding="utf-8",
    )
    transcript_path.write_text(
        json.dumps({"responses": responses}), encoding="utf-8"
    )
    return {
        "STELLA_WORKER_METHOD_CONFIG": str(config_path),
        "STELLA_WORKER_TRANSCRIPT": str(transcript_path),
    }


def _success_responses() -> list[dict]:
    return [
        {
            "tool_name": "submit_contribution_roster",
            "arguments": MEASUREMENT_ROSTER_SUBMISSION,
        },
        {
            "tool_name": "submit_object_quantities",
            "arguments": MEASUREMENT_SUBMISSION,
        },
    ]


class LiteraturePipelinePlanTest(unittest.TestCase):
    def test_plan_supports_one_and_many_papers(self) -> None:
        for papers in ([MEASUREMENT_ARXIV_ID], [MEASUREMENT_ARXIV_ID, ARXIV_ID]):
            with self.subTest(papers=papers):
                request = LiteraturePipelineRequest(papers=papers)
                plan = workflow_runtime.plan_workflow(
                    root=ROOT,
                    workflow_id="literature_pipeline",
                    request=request,
                )
                self.assertEqual(plan["status"], "planned")
                self.assertEqual(plan["papers"], papers)
                self.assertIn("llm", plan["required_authorities"])
                self.assertIn("network", plan["required_authorities"])

    def test_catalog_declares_exactly_three_products(self) -> None:
        catalog = load_workflow_catalog(ROOT)
        self.assertEqual(
            sorted(spec.id for spec in catalog.workflows),
            ["benchmark", "gold_annotation", "literature_pipeline"],
        )


class LiteraturePipelineExecutionTest(unittest.TestCase):
    def setUp(self) -> None:
        guard(self)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        with tempfile.TemporaryDirectory() as staged_measurement, tempfile.TemporaryDirectory() as staged_failure:
            make_measurement_workspace(staged_measurement)
            make_workspace(staged_failure)
            _merge_workspace(self.root, Path(staged_measurement))
            _merge_workspace(self.root, Path(staged_failure))
        for paper in (MEASUREMENT_ARXIV_ID, ARXIV_ID):
            _write_catalog_artifacts(self.root, paper)
        self.env = self._write_per_paper_transcripts()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_per_paper_transcripts(self) -> dict[str, str]:
        """The measurement paper succeeds; the roster paper gets no script."""

        transcripts = self.root / "worker" / "transcripts"
        transcripts.mkdir(parents=True, exist_ok=True)
        (transcripts / f"{MEASUREMENT_ARXIV_ID}.json").write_text(
            json.dumps({"responses": _success_responses()}), encoding="utf-8"
        )
        (transcripts / f"{ARXIV_ID}.json").write_text(
            json.dumps({"responses": []}), encoding="utf-8"
        )
        config_path = self.root / "worker" / "method_config.json"
        config_path.write_text(
            json.dumps(
                frozen_contribution_config().model_dump(mode="json", by_alias=True)
            ),
            encoding="utf-8",
        )
        return {
            "STELLA_WORKER_METHOD_CONFIG": str(config_path),
            "STELLA_WORKER_TRANSCRIPT": str(transcripts),
        }

    def _request(self, papers: list[str], **authority_kwargs) -> LiteraturePipelineRequest:
        return LiteraturePipelineRequest(
            papers=papers,
            authorities=Authorities(
                execute=True, llm=True, supersede=authority_kwargs.get("supersede", False)
            ),
        )

    def test_one_paper_execution_is_complete_with_worker_isolation(self) -> None:
        summary = workflow_runtime.run_workflow(
            root=self.root,
            workflow_id="literature_pipeline",
            request=self._request([MEASUREMENT_ARXIV_ID]),
            run_id="e2e-one",
            env_extra=self.env,
        )
        self.assertEqual(summary["status"], "complete")
        canonical = self.root / "literature" / MEASUREMENT_ARXIV_ID / "literature_hvs_contributions.json"
        self.assertTrue(canonical.is_file())
        events = self._events("e2e-one")
        self.assertEqual(events[0]["event"], "run_created")
        self.assertIn("run_finished", [item["event"] for item in events])
        # Fresh worker process per paper: worker pid differs from this process.
        attempt_dirs = sorted(
            (self.root / "runs" / "literature_pipeline" / "e2e-one" / "papers")
            .glob("*/attempts/*")
        )
        self.assertTrue(attempt_dirs)
        for attempt in attempt_dirs:
            telemetry = json.loads(
                (attempt / "telemetry.json").read_text(encoding="utf-8")
            )
            self.assertNotEqual(telemetry["worker_pid"], os.getpid())
            result = json.loads(
                (attempt / "result.json").read_text(encoding="utf-8")
            )
            self.assertEqual(result.get("worker_pid"), telemetry["worker_pid"])

    def test_independent_paper_failure_yields_partial_run(self) -> None:
        # The failing paper's transcript is empty: its first model call
        # exhausts the scripted transport, while the other paper succeeds.
        summary = workflow_runtime.run_workflow(
            root=self.root,
            workflow_id="literature_pipeline",
            request=self._request([MEASUREMENT_ARXIV_ID, ARXIV_ID]),
            run_id="e2e-partial",
            env_extra=self.env,
        )
        self.assertEqual(summary["status"], "partial")
        statuses = {
            item["paper_id"]: item["status"] for item in summary["papers"]
        }
        self.assertEqual(statuses[MEASUREMENT_ARXIV_ID], "complete")
        self.assertEqual(statuses[ARXIV_ID], "failed")
        # Validated success preserved.
        canonical = self.root / "literature" / MEASUREMENT_ARXIV_ID / "literature_hvs_contributions.json"
        self.assertTrue(canonical.is_file())
        # The failing paper has no canonical write.
        self.assertFalse(
            (self.root / "literature" / ARXIV_ID / "literature_hvs_contributions.json").exists()
        )

    def test_second_run_requires_supersede_and_records_previous_hash(self) -> None:
        first = workflow_runtime.run_workflow(
            root=self.root,
            workflow_id="literature_pipeline",
            request=self._request([MEASUREMENT_ARXIV_ID]),
            run_id="e2e-first",
            env_extra=self.env,
        )
        self.assertEqual(first["status"], "complete")
        blocked = workflow_runtime.run_workflow(
            root=self.root,
            workflow_id="literature_pipeline",
            request=self._request([MEASUREMENT_ARXIV_ID]),
            run_id="e2e-blocked",
            env_extra=self.env,
        )
        # The single paper cannot be replaced without supersede authority,
        # so its contribution operation fails closed and the run fails.
        self.assertEqual(blocked["status"], "failed")
        # Supersede granted: replacement succeeds and records the previous hash.
        previous_bytes = (
            self.root / "literature" / MEASUREMENT_ARXIV_ID / "literature_hvs_contributions.json"
        ).read_bytes()
        import hashlib

        previous_sha = hashlib.sha256(previous_bytes).hexdigest()
        superseding = workflow_runtime.run_workflow(
            root=self.root,
            workflow_id="literature_pipeline",
            request=self._request([MEASUREMENT_ARXIV_ID], supersede=True),
            run_id="e2e-supersede",
            env_extra=self.env,
        )
        self.assertEqual(superseding["status"], "complete")
        self.assertTrue(superseding["superseded"])
        self.assertEqual(
            superseding["superseded"][0]["previous_sha256"], previous_sha
        )
        events = self._events("e2e-supersede")
        self.assertIn("superseded", [item["event"] for item in events])

    def test_artifact_chain_reaches_indexes_and_timelines(self) -> None:
        summary = workflow_runtime.run_workflow(
            root=self.root,
            workflow_id="literature_pipeline",
            request=self._request([MEASUREMENT_ARXIV_ID]),
            run_id="e2e-chain",
            env_extra=self.env,
        )
        self.assertEqual(summary["status"], "complete")
        literature = self.root / "literature"
        self.assertTrue(
            (literature / "01_literature_hvs_contributions_index.json").is_file()
        )
        catalog_dir = literature / "hvs_contribution_catalog"
        self.assertTrue(catalog_dir.is_dir())
        self.assertTrue(list(catalog_dir.glob("*.json")))

    def test_run_directory_stays_outside_benchmark_paths(self) -> None:
        workflow_runtime.run_workflow(
            root=self.root,
            workflow_id="literature_pipeline",
            request=self._request([MEASUREMENT_ARXIV_ID]),
            run_id="e2e-isolation",
            env_extra=self.env,
        )
        runs = self.root / "runs" / "literature_pipeline"
        self.assertTrue(runs.is_dir())
        self.assertFalse((self.root / "benchmark").exists())
        self.assertFalse((self.root / "runs" / "benchmark").exists())
        events_text = "\n".join(
            path.read_text(encoding="utf-8") for path in runs.rglob("events.jsonl")
        )
        self.assertNotIn("STELLA_GOLD_DIR", events_text)
        self.assertNotIn("gold", events_text.lower())

    def _events(self, run_id: str) -> list[dict]:
        path = self.root / "runs" / "literature_pipeline" / run_id / "events.jsonl"
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


if __name__ == "__main__":
    unittest.main()
