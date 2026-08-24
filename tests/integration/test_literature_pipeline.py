"""Offline end-to-end tests for the literature_pipeline workflow.

Everything starts from raw local paper assets plus one declared test
session (fake discovery, fake model decisions, scripted provider
responses). No stage output is pre-seeded: the workflow itself must
create and validate each artifact in phase order. Negative cases prove
that missing authority creates no run and makes no call, that a fake
network failure preserves completed artifacts as a typed network_failed
result, that an invalid review response blocks downstream stages, and
that one paper's failure never erases another paper's success. No real
network, provider, or private-gold access occurs.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from stella import workflow_runtime
from stella.workflows import (
    Authorities,
    LiteraturePipelineRequest,
    StellaError,
    load_workflow_catalog,
)
from tests.integration.netguard import guard
from tests.hvs_contribution_fixtures import (
    ARXIV_ID,
    MEASUREMENT_ARXIV_ID,
    MEASUREMENT_ROSTER_SUBMISSION,
    MEASUREMENT_SUBMISSION,
    frozen_contribution_config,
    make_measurement_workspace,
    measurement_manuscript_text,
)

ROOT = Path(__file__).resolve().parents[2]

TABLE_TEX = (
    "\n\\begin{table}\n"
    "\\caption{Hypervelocity star measurements}\n"
    "\\label{tab:hvs}\n"
    "\\begin{tabular}{lcc}\n"
    "ID & RV & PM \\\\\n"
    "J1234 & 500 & 2.0 \\\\\n"
    "J5678 & 600 & 3.0 \\\\\n"
    "\\end{tabular}\n"
    "\\end{table}\n"
)

REVIEW_DECISION = {
    "status": "reviewed",
    "summary": "one measurement table",
    "tables": [
        {
            "id": "t1",
            "asset_type": "object_catalog",
            "role_in_paper": "HVS measurements of J1234 and J5678",
            "evidence": "caption and columns",
            "comments": "",
            "columns": [
                {
                    "name": "ID",
                    "meaning": "star identifier",
                    "unit_text": "",
                    "source_of_definition": "table header",
                    "confidence": 1.0,
                },
                {
                    "name": "RV",
                    "meaning": "radial velocity",
                    "unit_text": "km/s",
                    "source_of_definition": "table header",
                    "confidence": 1.0,
                },
            ],
        }
    ],
    "resources": [],
    "rejections": [],
}

ASSESSMENT_DECISION = {
    "has_observational_catalog": True,
    "confidence": 0.9,
    "catalog_role": "new_catalog",
    "object_scope": "multiple_objects",
    "evidence": "measurement table of hypervelocity stars",
    "data_products": ["source_ids", "radial_velocities"],
}


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
                self.assertEqual(plan["papers"], list(papers))
                self.assertIn("llm", plan["required_authorities"])
                self.assertIn("network", plan["required_authorities"])
                catalog = load_workflow_catalog(ROOT)
                self.assertEqual(
                    sorted(w.id for w in catalog.workflows),
                    [
                        "benchmark",
                        "gold_annotation",
                        "literature_pipeline",
                    ],
                )


class LiteraturePipelineExecutionTest(unittest.TestCase):
    """Full chain from raw fixtures through one declared test session."""

    def setUp(self) -> None:
        guard(self)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        staged = Path(tempfile.mkdtemp())
        make_measurement_workspace(
            staged, tex=measurement_manuscript_text() + TABLE_TEX
        )
        shutil.copytree(
            staged / "contracts", self.root / "contracts", dirs_exist_ok=True
        )
        shutil.copytree(
            staged / "literature", self.root / "literature", dirs_exist_ok=True
        )
        shutil.rmtree(staged)
        self.session_path = self.root / "session.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_session(self, **overrides: object) -> None:
        session = {
            "method": frozen_contribution_config().model_dump(
                mode="json", by_alias=True
            ),
            "discovery": {
                "2026-01": [
                    {
                        "arxiv_id": MEASUREMENT_ARXIV_ID,
                        "title": "Hypervelocity star measurements of J1234",
                        "summary": "We measure hypervelocity stars.",
                        "published": "2026-01-15T00:00:00Z",
                    }
                ]
            },
            "assessments": {MEASUREMENT_ARXIV_ID: ASSESSMENT_DECISION},
            "review_responses": {MEASUREMENT_ARXIV_ID: REVIEW_DECISION},
            "model_responses": [
                {
                    "tool_name": "submit_contribution_roster",
                    "arguments": MEASUREMENT_ROSTER_SUBMISSION,
                },
                {
                    "tool_name": "submit_object_quantities",
                    "arguments": MEASUREMENT_SUBMISSION,
                },
            ],
        }
        session.update(overrides)
        self.session_path.write_text(
            json.dumps(session, ensure_ascii=False), encoding="utf-8"
        )

    def _request(
        self, papers: list[str], **authority_kwargs: bool
    ) -> LiteraturePipelineRequest:
        return LiteraturePipelineRequest(
            papers=papers,
            fetch_months=["2026-01"],
            authorities=Authorities(
                execute=True,
                llm=True,
                network=True,
                supersede=authority_kwargs.get("supersede", False),
            ),
        )

    def _run(self, papers: list[str], run_id: str, **kwargs: bool) -> dict:
        self._write_session()
        return workflow_runtime.run_workflow(
            root=self.root,
            workflow_id="literature_pipeline",
            request=self._request(papers, **kwargs),
            run_id=run_id,
            env_extra={"STELLA_SESSION_FILE": str(self.session_path)},
        )

    def _events(self, run_id: str) -> list[dict]:
        path = (
            self.root
            / "runs"
            / "literature_pipeline"
            / run_id
            / "events.jsonl"
        )
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def test_workflow_builds_every_artifact_from_raw_fixtures(self) -> None:
        summary = self._run([MEASUREMENT_ARXIV_ID], "e2e-full")
        self.assertEqual(summary["status"], "complete", summary)
        self.assertEqual(summary["operations_failed"], [])
        paper = self.root / "literature" / MEASUREMENT_ARXIV_ID
        expected = [
            self.root / "literature" / "00_literature_notes_index.json",
            paper / "catalog_assessment.json",
            paper / "catalog_review.json",
            paper / "catalog_extraction.json",
            paper / "catalog_tables" / "table-1.ecsv",
            paper / "literature_hvs_contributions.json",
            self.root / "literature" / "01_literature_hvs_contributions_index.json",
            self.root / "literature" / "hvs_contribution_catalog" / "index.json",
        ]
        for artifact in expected:
            self.assertTrue(
                artifact.is_file(), f"workflow did not build {artifact}"
            )
        review = json.loads(
            (paper / "catalog_review.json").read_text(encoding="utf-8")
        )
        self.assertEqual(review["review"]["status"], "reviewed")
        self.assertEqual(len(review["internal_tables"]), 1)
        events = self._events("e2e-full")
        self.assertEqual(events[0]["event"], "run_created")
        self.assertIn("run_finished", [item["event"] for item in events])

    def test_missing_authority_creates_no_run(self) -> None:
        request = LiteraturePipelineRequest(
            papers=[MEASUREMENT_ARXIV_ID],
            fetch_months=["2026-01"],
            authorities=Authorities(execute=True, llm=True),
        )
        with self.assertRaises(StellaError) as ctx:
            workflow_runtime.run_workflow(
                root=self.root,
                workflow_id="literature_pipeline",
                request=request,
                env_extra={"STELLA_SESSION_FILE": str(self.session_path)},
            )
        self.assertEqual(ctx.exception.code, "MISSING_AUTHORITY")
        self.assertFalse((self.root / "runs").exists())

    def test_transport_exhaustion_is_a_resumable_network_failure(self) -> None:
        # A scripted provider that runs dry mid-extraction models a quota
        # exhaustion: completed paper artifacts survive and the paper lands
        # in network_failed, never silently failed.
        self._write_session(model_responses=[])
        summary = workflow_runtime.run_workflow(
            root=self.root,
            workflow_id="literature_pipeline",
            request=self._request([MEASUREMENT_ARXIV_ID]),
            run_id="e2e-quota",
            env_extra={"STELLA_SESSION_FILE": str(self.session_path)},
        )
        self.assertEqual(summary["status"], "network_failed")
        paper_status = {
            item["paper_id"]: item["status"] for item in summary["papers"]
        }
        self.assertEqual(paper_status[MEASUREMENT_ARXIV_ID], "network_failed")
        paper = self.root / "literature" / MEASUREMENT_ARXIV_ID
        # Stages before the provider call completed and survived.
        self.assertTrue((paper / "catalog_assessment.json").is_file())
        self.assertTrue((paper / "catalog_review.json").is_file())
        self.assertFalse(
            (paper / "literature_hvs_contributions.json").is_file()
        )

    def test_invalid_review_response_blocks_downstream_stages(self) -> None:
        # A review model answering outside the declared JSON contract is a
        # validation failure: the extraction stage must never run.
        self._write_session(
            review_responses={MEASUREMENT_ARXIV_ID: "not json"}
        )
        summary = workflow_runtime.run_workflow(
            root=self.root,
            workflow_id="literature_pipeline",
            request=self._request([MEASUREMENT_ARXIV_ID]),
            run_id="e2e-bad-review",
            env_extra={"STELLA_SESSION_FILE": str(self.session_path)},
        )
        self.assertNotEqual(summary["status"], "complete")
        paper = self.root / "literature" / MEASUREMENT_ARXIV_ID
        self.assertFalse((paper / "catalog_review.json").is_file())
        self.assertFalse((paper / "catalog_extraction.json").is_file())
        self.assertFalse(
            (paper / "literature_hvs_contributions.json").is_file()
        )

    def test_one_paper_failure_preserves_the_other_paper(self) -> None:
        # The second paper has archived assets but no declared assessment
        # decision: it fails its assessment as a precondition while the
        # measurement paper still completes its whole chain.
        (self.root / "literature" / ARXIV_ID / "arxiv_source").mkdir(
            parents=True, exist_ok=True
        )
        (
            self.root / "literature" / ARXIV_ID / "arxiv_source" / "main.tex"
        ).write_text("empty", encoding="utf-8")
        session_discovery = {
            "2026-01": [
                {
                    "arxiv_id": MEASUREMENT_ARXIV_ID,
                    "title": "Hypervelocity star measurements of J1234",
                    "summary": "We measure hypervelocity stars.",
                    "published": "2026-01-15T00:00:00Z",
                },
                {
                    "arxiv_id": ARXIV_ID,
                    "title": "Hypervelocity star survey",
                    "summary": "A survey.",
                    "published": "2026-01-20T00:00:00Z",
                },
            ]
        }
        self._write_session(discovery=session_discovery)
        summary = workflow_runtime.run_workflow(
            root=self.root,
            workflow_id="literature_pipeline",
            request=self._request([MEASUREMENT_ARXIV_ID, ARXIV_ID]),
            run_id="e2e-two",
            env_extra={"STELLA_SESSION_FILE": str(self.session_path)},
        )
        self.assertEqual(summary["status"], "partial")
        statuses = {
            item["paper_id"]: item["status"] for item in summary["papers"]
        }
        self.assertEqual(statuses[MEASUREMENT_ARXIV_ID], "complete")
        self.assertEqual(statuses[ARXIV_ID], "failed")
        canonical = (
            self.root
            / "literature"
            / MEASUREMENT_ARXIV_ID
            / "literature_hvs_contributions.json"
        )
        self.assertTrue(canonical.is_file())

    def test_second_run_requires_supersede_and_records_previous_hash(self) -> None:
        first = self._run([MEASUREMENT_ARXIV_ID], "e2e-sup-1")
        self.assertEqual(first["status"], "complete")
        self.assertEqual(first["superseded"], [])
        blocked = workflow_runtime.run_workflow(
            root=self.root,
            workflow_id="literature_pipeline",
            request=self._request([MEASUREMENT_ARXIV_ID]),
            run_id="e2e-sup-2",
            env_extra={"STELLA_SESSION_FILE": str(self.session_path)},
        )
        self.assertNotEqual(blocked["status"], "complete")
        authorized = workflow_runtime.run_workflow(
            root=self.root,
            workflow_id="literature_pipeline",
            request=self._request([MEASUREMENT_ARXIV_ID], supersede=True),
            run_id="e2e-sup-3",
            env_extra={"STELLA_SESSION_FILE": str(self.session_path)},
        )
        self.assertEqual(authorized["status"], "complete")
        self.assertEqual(len(authorized["superseded"]), 1)
        self.assertEqual(
            authorized["superseded"][0]["operation"],
            "literature.extract_contributions",
        )
        events = self._events("e2e-sup-3")
        self.assertIn("superseded", [item["event"] for item in events])

    def test_run_directory_stays_outside_benchmark_paths(self) -> None:
        summary = self._run([MEASUREMENT_ARXIV_ID], "e2e-paths")
        run_dir = Path(summary["run_dir"])
        self.assertIn("runs/literature_pipeline", run_dir.as_posix())
        self.assertFalse((self.root / "benchmark").exists())


if __name__ == "__main__":
    unittest.main()
