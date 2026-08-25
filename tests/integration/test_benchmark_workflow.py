"""Offline two-paper benchmark lifecycle: freeze -> execute -> typed
failure -> resume -> finalize -> score.

Everything runs against temporary roots with a declared test session:
the frozen method carries real provider/model settings and hashes,
execution writes only under the single requested run id, transport
exhaustion is a resumable network failure while successful papers stay
immutable, finalization is persisted, and scoring reports delivery, L0,
L1, and L2 separately with no fused score and no gold values in the
public scorecard. No real network, provider, or private-gold access
occurs.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from stella import workflow_runtime
from stella.workflows import Authorities, BenchmarkRequest
from tests.integration.netguard import guard
from tests.hvs_contribution_fixtures import (
    MEASUREMENT_ARXIV_ID,
    MEASUREMENT_ROSTER_SUBMISSION,
    MEASUREMENT_SUBMISSION,
    frozen_contribution_config,
    make_measurement_workspace,
)
from tests.benchmark.test_hvs_contribution_gold import fictional_annotation_payload

ROOT = Path(__file__).resolve().parents[2]
PAPER_B = "2601.09999"
RUN_ID = "bench-e2e"


def _base_session() -> dict:
    return {
        "method": frozen_contribution_config().model_dump(
            mode="json", by_alias=True
        ),
        "model_responses_by_paper": {PAPER_B: []},
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


class BenchmarkWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        guard(self)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        staged = Path(tempfile.mkdtemp())
        make_measurement_workspace(staged)
        shutil.copytree(
            staged / "contracts", self.root / "contracts", dirs_exist_ok=True
        )
        shutil.copytree(
            staged / "literature", self.root / "literature", dirs_exist_ok=True
        )
        shutil.rmtree(staged)
        # Second paper: same manuscript shape, archived assets, and its
        # own (initially empty) scripted replay to model quota exhaustion.
        from tests.hvs_contribution_fixtures import measurement_manuscript_text

        for paper in (MEASUREMENT_ARXIV_ID, PAPER_B):
            source = self.root / "literature" / paper / "arxiv_source"
            if paper == PAPER_B:
                source.mkdir(parents=True, exist_ok=True)
                (source / "main.tex").write_text(
                    measurement_manuscript_text(), encoding="utf-8"
                )
            assets = self.root / "literature" / paper / "assets"
            assets.mkdir(parents=True, exist_ok=True)
            (assets / "paper.pdf").write_bytes(b"%PDF-1.4 fake")
        self.gold_dir = self.root / "private-gold"
        self.gold_dir.mkdir()
        self.session_path = self.root / "session.json"
        self._old_gold = os.environ.get("STELLA_GOLD_DIR")
        os.environ["STELLA_GOLD_DIR"] = str(self.gold_dir)

    def tearDown(self) -> None:
        if self._old_gold is None:
            os.environ.pop("STELLA_GOLD_DIR", None)
        else:
            os.environ["STELLA_GOLD_DIR"] = self._old_gold
        self._tmp.cleanup()

    def _request(
        self,
        papers: list[str],
        *,
        scoring_authorities: bool = False,
        **phases: object,
    ) -> BenchmarkRequest:
        authorities = dict(execute=True, llm=True, network=True)
        if scoring_authorities:
            authorities.update(gold_private=True, scoring=True)
        return BenchmarkRequest(
            papers=papers,
            authorities=Authorities(**authorities),  # type: ignore[arg-type]
            **phases,  # type: ignore[arg-type]
        )

    def _run(
        self,
        papers: list[str],
        *,
        session: dict | None = None,
        run_id: str = RUN_ID,
        phases: list[str] | None = None,
        supersede: bool = False,
    ) -> dict:
        self.session_path.write_text(
            json.dumps(session or _base_session()), encoding="utf-8"
        )
        request_args: dict = {}
        if phases is not None:
            request_args["phases"] = phases
        return workflow_runtime.run_workflow(
            root=self.root,
            workflow_id="benchmark",
            request=self._request(papers, **request_args),
            run_id=run_id,
            env_extra={"STELLA_SESSION_FILE": str(self.session_path)},
        )

    def test_freeze_execute_finalize_score_one_run_id(self) -> None:
        summary = self._run(
            [MEASUREMENT_ARXIV_ID],
            phases=["prepare", "freeze", "run", "finalize"],
        )
        self.assertEqual(summary["status"], "complete", summary)
        run_dir = self.root / "runs" / "benchmark" / RUN_ID
        self.assertTrue(run_dir.is_dir())
        # The frozen method carries real settings and a fingerprint.
        frozen = json.loads(
            (run_dir / "method_config.json").read_text(encoding="utf-8")
        )
        self.assertIn("method_fingerprint", frozen)
        method = frozen.get("method") or frozen
        self.assertIn("roster_model", json.dumps(method))
        self.assertFalse(
            list((self.root / "runs" / "benchmark").glob("brun*")),
            "no implicit side run may exist",
        )
        # Finalization is persisted under the same run id.
        finalized = json.loads(
            (run_dir / "finalized.json").read_text(encoding="utf-8")
        )
        self.assertEqual(finalized["final_status"], "complete")
        # Execution never wrote into the canonical literature tree.
        self.assertFalse(
            (
                self.root
                / "literature"
                / MEASUREMENT_ARXIV_ID
                / "literature_hvs_contributions.json"
            ).is_file()
        )

    def test_network_failure_is_resumable_and_success_is_immutable(self) -> None:
        # PAPER_B's scripted transport is empty: it exhausts on its first
        # call and must land in network_failed, not failed.
        session = _base_session()
        self._run(
            [MEASUREMENT_ARXIV_ID, PAPER_B],
            run_id="bench-resume",
            session=session,
            phases=["prepare", "freeze", "run"],
        )
        run_dir = self.root / "runs" / "benchmark" / "bench-resume"
        status_a = json.loads(
            (run_dir / "papers" / MEASUREMENT_ARXIV_ID / "status.json").read_text(
                encoding="utf-8"
            )
        )
        status_b = json.loads(
            (run_dir / "papers" / PAPER_B / "status.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(status_a["status"], "complete")
        self.assertEqual(status_b["status"], "network_failed")
        attempts_a = list(
            (run_dir / "papers" / MEASUREMENT_ARXIV_ID / "attempts").glob(
                "benchmark.execute-*"
            )
        )
        self.assertEqual(len(attempts_a), 1)
        # A second invocation resumes only the network-failed paper.
        session["model_responses_by_paper"] = {
            PAPER_B: [
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
        resumed = self._run(
            [MEASUREMENT_ARXIV_ID, PAPER_B],
            run_id="bench-resume",
            session=session,
            phases=["run"],
        )
        self.assertEqual(resumed["status"], "complete")
        attempts_a_after = list(
            (run_dir / "papers" / MEASUREMENT_ARXIV_ID / "attempts").glob(
                "benchmark.execute-*"
            )
        )
        self.assertEqual(
            len(attempts_a_after), 1, "successful papers are never retried"
        )
        status_b_after = json.loads(
            (run_dir / "papers" / PAPER_B / "status.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(status_b_after["status"], "complete")

    def test_zero_resolved_papers_fails_before_running(self) -> None:
        summary = self._run([], phases=["prepare", "freeze", "run"])
        self.assertEqual(summary["status"], "failed")

    def test_dev10_default_resolves_the_campaign_sample(self) -> None:
        # papers=None resolves the dev split of the frozen campaign.
        self.session_path.write_text(
            json.dumps(_base_session()), encoding="utf-8"
        )
        request = BenchmarkRequest(
            authorities=Authorities(execute=True, llm=True, network=True),
            phases=["prepare"],
        )
        summary = workflow_runtime.run_workflow(
            root=self.root,
            workflow_id="benchmark",
            request=request,
            run_id="bench-dev10",
            env_extra={"STELLA_SESSION_FILE": str(self.session_path)},
        )
        self.assertEqual(summary["status"], "complete")
        campaign = json.loads(
            (
                self.root
                / "runs"
                / "benchmark"
                / "bench-dev10"
                / "campaign.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(len(campaign["papers"]), 10)
        self.assertTrue(all(p["split"] == "dev" for p in campaign["papers"]))

    def test_full50_requires_explicit_authorization(self) -> None:
        self.session_path.write_text(
            json.dumps(_base_session()), encoding="utf-8"
        )
        request = BenchmarkRequest(
            profile="full50",
            authorities=Authorities(execute=True, llm=True, network=True),
            phases=["prepare"],
        )
        summary = workflow_runtime.run_workflow(
            root=self.root,
            workflow_id="benchmark",
            request=request,
            run_id="bench-full50",
            env_extra={"STELLA_SESSION_FILE": str(self.session_path)},
        )
        self.assertNotEqual(summary["status"], "complete")

    def _seed_gold(self, arxiv_id: str) -> None:
        payload = fictional_annotation_payload()
        payload["arxiv_id"] = arxiv_id
        document = json.loads(json.dumps(payload))
        target = self.gold_dir / arxiv_id
        target.mkdir(parents=True, exist_ok=True)
        (target / "annotation_expert-a.json").write_text(
            json.dumps(document), encoding="utf-8"
        )

    def test_score_reports_layers_without_fusing(self) -> None:
        self._run(
            [MEASUREMENT_ARXIV_ID],
            phases=["prepare", "freeze", "run", "finalize"],
        )
        self._seed_gold(MEASUREMENT_ARXIV_ID)
        import hashlib

        annotation = (
            self.gold_dir
            / MEASUREMENT_ARXIV_ID
            / "annotation_expert-a.json"
        )
        selection_dir = self.root / "benchmark"
        selection_dir.mkdir(parents=True, exist_ok=True)
        (selection_dir / "gold_selection.json").write_text(
            json.dumps(
                {
                    "papers": [
                        {
                            "arxiv_id": MEASUREMENT_ARXIV_ID,
                            "selected_expert": "expert-a",
                            "annotation_file": "annotation_expert-a.json",
                            "sha256": hashlib.sha256(
                                annotation.read_bytes()
                            ).hexdigest(),
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        self.session_path.write_text(
            json.dumps(_base_session()), encoding="utf-8"
        )
        scored = workflow_runtime.run_workflow(
            root=self.root,
            workflow_id="benchmark",
            request=self._request(
                [MEASUREMENT_ARXIV_ID],
                scoring_authorities=True,
                phases=["score"],
            ),
            run_id=RUN_ID,
            env_extra={"STELLA_SESSION_FILE": str(self.session_path)},
        )
        self.assertEqual(scored["status"], "complete", scored)
        run_dir = self.root / "runs" / "benchmark" / RUN_ID
        details_dir = self.gold_dir / "scoring_details"
        self.assertTrue(details_dir.is_dir())
        public_card = self.root / "benchmark" / "scorecards" / f"{RUN_ID}.json"
        self.assertTrue(public_card.is_file())
        card = json.loads(public_card.read_text(encoding="utf-8"))
        rendered = json.dumps(card)
        for fused in ("overall", "composite", '"pass"'):
            self.assertNotIn(fused, rendered)
        self.assertNotIn("object_contributions", rendered)
        self.assertNotIn("quantities", rendered)


if __name__ == "__main__":
    unittest.main()
