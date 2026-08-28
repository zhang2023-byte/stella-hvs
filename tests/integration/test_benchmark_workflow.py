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

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from stella import workflow_runtime
from stella.benchmark.scoring import emit_scorecard, score
from stella.benchmark.gold_selection import contribution_selection_path
from stella.benchmark.contribution_gold_revision import (
    contribution_history_object_path,
)
from stella.benchmark.hvs_contribution_gold import (
    HvsContributionGoldAnnotation,
    contribution_gold_json_document,
)
from stella.schema_registry import schema_ref
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
        self.assertFalse(
            (self.root / "runs" / "hvs-contribution-extraction").exists(),
            "benchmark extraction must stay inside the selected benchmark run",
        )
        extraction_attempts = list(
            (run_dir / "extraction_attempts").glob("benchmark-*")
        )
        self.assertEqual(len(extraction_attempts), 1)
        canonical = json.loads(
            (run_dir / "papers" / MEASUREMENT_ARXIV_ID / "paper_result.json").read_text(
                encoding="utf-8"
            )
        )["canonical_path"]
        Path(canonical).resolve().relative_to(run_dir.resolve())
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
            phases=["resume"],
        )
        self.assertEqual(resumed["status"], "complete")
        self.assertEqual(
            resumed["papers"],
            [
                {"paper_id": MEASUREMENT_ARXIV_ID, "status": "complete"},
                {"paper_id": PAPER_B, "status": "complete"},
            ],
            "resume summaries must include persisted status for every selected paper",
        )
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
        self.assertEqual(
            len(
                list(
                    (
                        run_dir / "papers" / PAPER_B / "attempts"
                    ).glob("benchmark.resume-*")
                )
            ),
            1,
            "the public resume phase must execute a real retry attempt",
        )

    def test_existing_run_accepts_fresh_partial_finalization_authority(self) -> None:
        run_id = "bench-authorized-partial"
        self._run(
            [PAPER_B],
            run_id=run_id,
            session=_base_session(),
            phases=["prepare", "freeze", "run"],
        )
        summary = workflow_runtime.run_workflow(
            root=self.root,
            workflow_id="benchmark",
            request=self._request(
                [PAPER_B],
                phases=["finalize"],
                finalize_partial_explicitly_authorized=True,
            ),
            run_id=run_id,
            env_extra={"STELLA_SESSION_FILE": str(self.session_path)},
        )
        self.assertEqual(summary["status"], "partial")
        marker = json.loads(
            (
                self.root
                / "runs"
                / "benchmark"
                / run_id
                / "finalized.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(marker["final_status"], "partial")

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
        self.assertEqual(
            len(summary["papers"]),
            10,
            "the runtime must adopt the sample prepared during the same run",
        )

    def test_existing_run_id_is_selected_by_the_request(self) -> None:
        self.session_path.write_text(
            json.dumps(_base_session()), encoding="utf-8"
        )
        request = BenchmarkRequest(
            run_id="request-selected-run",
            papers=[MEASUREMENT_ARXIV_ID],
            phases=["prepare"],
            authorities=Authorities(execute=True, llm=True, network=True),
        )
        summary = workflow_runtime.run_workflow(
            root=self.root,
            workflow_id="benchmark",
            request=request,
            env_extra={"STELLA_SESSION_FILE": str(self.session_path)},
        )
        self.assertEqual(summary["run_id"], "request-selected-run")
        self.assertTrue(
            (
                self.root
                / "runs"
                / "benchmark"
                / "request-selected-run"
                / "run.json"
            ).is_file()
        )
        with self.assertRaisesRegex(Exception, "cannot repeat"):
            workflow_runtime.run_workflow(
                root=self.root,
                workflow_id="benchmark",
                request=BenchmarkRequest(
                    run_id="request-selected-run",
                    phases=["run"],
                    authorities=Authorities(
                        execute=True, llm=True, network=True
                    ),
                ),
                env_extra={"STELLA_SESSION_FILE": str(self.session_path)},
            )

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
        selection_path = contribution_selection_path(self.root, {})
        selection_path.parent.mkdir(parents=True, exist_ok=True)
        selection_path.write_text(
            json.dumps(
                {
                    "schema": schema_ref("benchmark.hvs_contribution_gold_selection"),
                    "selection_id": selection_path.stem,
                    "target_schema": schema_ref("benchmark.hvs_contribution_annotation"),
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
        retired_dir = self.gold_dir / "scoring_details"
        retired_dir.mkdir()
        retired_path = retired_dir / f"{RUN_ID}.json"
        retired_path.write_text("{}\n", encoding="utf-8")
        refused = score(
            {
                "run_id": RUN_ID,
                "authorities": {"gold_private": True, "scoring": True},
            },
            root=self.root,
        )
        self.assertEqual(refused["status"], "failed")
        self.assertIn("retired Gold-local path", refused["failure"]["detail"])
        retired_path.unlink()
        retired_dir.rmdir()
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
        details_path = self.gold_dir.parent / "scoring-details" / f"{RUN_ID}.json"
        self.assertTrue(details_path.is_file())
        self.assertFalse((self.gold_dir / "scoring_details").exists())
        public_card = self.root / "benchmark" / "scorecards" / f"{RUN_ID}.json"
        self.assertTrue(public_card.is_file())
        card = json.loads(public_card.read_text(encoding="utf-8"))
        rendered = json.dumps(card)
        for fused in ("overall", "composite", '"pass"'):
            self.assertNotIn(fused, rendered)
        self.assertNotIn("object_contributions", rendered)
        self.assertNotIn("quantities", rendered)
        repeated_score = score(
            {
                "run_id": RUN_ID,
                "authorities": {"gold_private": True, "scoring": True},
            },
            root=self.root,
        )
        self.assertEqual(repeated_score["status"], "failed")
        repeated_card = emit_scorecard(
            {"run_id": RUN_ID, "authorities": {"scoring": True}},
            root=self.root,
        )
        self.assertEqual(repeated_card["status"], "failed")

    def test_score_requires_finalization_and_exact_selected_gold_hash(self) -> None:
        self._run(
            [MEASUREMENT_ARXIV_ID],
            phases=["prepare", "freeze", "run"],
        )
        self._seed_gold(MEASUREMENT_ARXIV_ID)
        selection_path = contribution_selection_path(self.root, {})
        selection_path.parent.mkdir(parents=True, exist_ok=True)
        selection_path.write_text(
            json.dumps(
                {
                    "schema": schema_ref("benchmark.hvs_contribution_gold_selection"),
                    "selection_id": selection_path.stem,
                    "target_schema": schema_ref("benchmark.hvs_contribution_annotation"),
                    "papers": [
                        {
                            "arxiv_id": MEASUREMENT_ARXIV_ID,
                            "selected_expert": "expert-a",
                            "annotation_file": "annotation_expert-a.json",
                            "sha256": "0" * 64,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        authorities = {"gold_private": True, "scoring": True}
        unfinalized = score(
            {"run_id": RUN_ID, "authorities": authorities}, root=self.root
        )
        self.assertEqual(unfinalized["status"], "failed")
        self.assertIn("finalized", unfinalized["failure"]["detail"])
        from stella.benchmark.run import finalize

        finalized = finalize(
            {"run_id": RUN_ID, "papers": [MEASUREMENT_ARXIV_ID]},
            root=self.root,
        )
        self.assertEqual(finalized["status"], "complete")
        mismatched = score(
            {"run_id": RUN_ID, "authorities": authorities}, root=self.root
        )
        self.assertEqual(mismatched["status"], "failed")
        self.assertIn("hash mismatch", mismatched["failure"]["detail"])

    def test_score_resolves_an_old_contribution_selection_from_history(self) -> None:
        self._run(
            [MEASUREMENT_ARXIV_ID],
            phases=["prepare", "freeze", "run", "finalize"],
        )
        self._seed_gold(MEASUREMENT_ARXIV_ID)
        annotation = (
            self.gold_dir
            / MEASUREMENT_ARXIV_ID
            / "annotation_expert-a.json"
        )
        selected_bytes = annotation.read_bytes()
        selected_sha = hashlib.sha256(selected_bytes).hexdigest()
        subprocess.run(
            ["git", "init", "-q"],
            cwd=self.root,
            check=True,
            capture_output=True,
        )
        history = contribution_history_object_path(self.gold_dir, selected_sha)
        history.parent.mkdir(parents=True)
        history.write_bytes(selected_bytes)

        replacement = fictional_annotation_payload()
        replacement["guideline_version"] = "revised-after-selection"
        replacement_document = contribution_gold_json_document(
            HvsContributionGoldAnnotation.model_validate(replacement)
        )
        annotation.write_text(
            json.dumps(replacement_document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        selection_path = contribution_selection_path(self.root, {})
        selection_path.parent.mkdir(parents=True, exist_ok=True)
        selection_path.write_text(
            json.dumps(
                {
                    "schema": schema_ref("benchmark.hvs_contribution_gold_selection"),
                    "selection_id": selection_path.stem,
                    "target_schema": schema_ref("benchmark.hvs_contribution_annotation"),
                    "papers": [
                        {
                            "arxiv_id": MEASUREMENT_ARXIV_ID,
                            "selected_expert": "expert-a",
                            "annotation_file": "annotation_expert-a.json",
                            "sha256": selected_sha,
                        }
                    ],
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


if __name__ == "__main__":
    unittest.main()
