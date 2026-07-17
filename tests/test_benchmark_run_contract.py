from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from stella.benchmark.run_contract import (
    build_method_fingerprint,
    build_run_config,
    ensure_run_config,
    external_failure_retry_eligibility,
    prepare_external_failure_retry,
    prepare_paper_retry,
    prepare_run_resume,
    require_run_manifest_delivery_contract,
    seal_run,
)
from stella.benchmark.components import validate_run_component_provenance
from stella.schema_registry import ACTIVE_BENCHMARK_CAMPAIGN, schema_ref


class FakeValidator:
    def validate_hvs_candidates_report(self, payload, *, workspace, require_complete):
        return type("Report", (), {"errors": [], "warnings": []})()


class EnrichmentAwareFakeValidator:
    """Fails any candidate whose enrichment groups are non-empty."""

    def validate_hvs_candidates_report(self, payload, *, workspace, require_complete):
        errors = [
            f"$.candidates[{index}].photometry: synthetic enrichment defect"
            for index, candidate in enumerate(payload.get("candidates") or [])
            if isinstance(candidate, dict) and candidate.get("photometry")
        ]
        return type("Report", (), {"errors": errors, "warnings": []})()


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
            "provenance": {
                "components": {
                    "prompt": "prompt-recorded",
                    "skill": "skill-recorded",
                    "validator": "validator-recorded",
                    "context_packer": "context-recorded",
                    "task_surface": "surface-recorded",
                    "normalizer": "normalizer-recorded",
                    "scorer": "scorer-recorded",
                    "identity_matching": "identity-recorded",
                    "unit_table": "unit-recorded",
                    "rule_profile": "rule-recorded",
                }
            },
            "parameters": {
                "task_surface": "full",
                "task_surface_sha256": "surface-recorded",
                "rule_profile_id": "hvs_extractor",
                "rule_profile_sha256": "rule-recorded",
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
            "campaign_id": ACTIVE_BENCHMARK_CAMPAIGN,
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
            "campaign_id": ACTIVE_BENCHMARK_CAMPAIGN,
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

    def test_only_active_campaign_accepts_new_formal_runs(self) -> None:
        for campaign_id in ("hvs-extraction-v1", "hvs-extraction-v2"):
            with self.subTest(campaign_id=campaign_id):
                with self.assertRaisesRegex(ValueError, "not writable"):
                    build_run_config(
                        run_id="r1",
                        method=self.method(),
                        expected_papers=["x"],
                        code={"commit": "abc", "dirty": False},
                        campaign={
                            "campaign_id": campaign_id,
                            "papers": [{"arxiv_id": "x", "split": "dev"}],
                        },
                        split="dev",
                    )

        config = build_run_config(
            run_id="r1",
            method=self.method(),
            expected_papers=["x"],
            code={"commit": "abc", "dirty": False},
            campaign={
                "campaign_id": ACTIVE_BENCHMARK_CAMPAIGN,
                "papers": [{"arxiv_id": "x", "split": "dev"}],
            },
            split="dev",
        )
        self.assertEqual(config["campaign"]["campaign_id"], ACTIVE_BENCHMARK_CAMPAIGN)

    def test_formal_b_and_c_runs_require_core_prov(self) -> None:
        campaign = {
            "campaign_id": ACTIVE_BENCHMARK_CAMPAIGN,
            "papers": [{"arxiv_id": "x", "split": "dev"}],
        }
        for producer in ("stella-benchmark-extraction", "stella-agentic-extraction"):
            with self.subTest(producer=producer):
                method = self.method()
                method["producer"] = producer
                with self.assertRaisesRegex(ValueError, "formal B/C.*core_prov"):
                    build_run_config(
                        run_id="r1",
                        method=method,
                        expected_papers=["x"],
                        code={"commit": "abc", "dirty": False},
                        campaign=campaign,
                        split="dev",
                    )

                method["parameters"]["task_surface"] = "core_prov"
                config = build_run_config(
                    run_id="r1",
                    method=method,
                    expected_papers=["x"],
                    code={"commit": "abc", "dirty": False},
                    campaign=campaign,
                    split="dev",
                )
                self.assertEqual(
                    config["method"]["parameters"]["task_surface"], "core_prov"
                )

    def test_component_override_must_cover_the_exact_recorded_contract(self) -> None:
        config = self.config()
        with self.assertRaisesRegex(ValueError, "component set mismatch"):
            validate_run_component_provenance(
                config,
                workspace=Path("."),
                current_component_hashes={"validator": "validator-recorded"},
            )

    def test_delivery_contract_rejects_inconsistent_status_and_surface_pairing(self) -> None:
        outcomes = {"valid": ["x"], "invalid": [], "missing": []}
        artifacts = {"x": {"literature_hvs_candidates.json": {"sha256": "hash"}}}
        manifest = {
            "papers": outcomes,
            "artifacts": artifacts,
            "core_delivery": {
                "status": "complete",
                "validation_mode": "core_prov",
                "papers": outcomes,
                "artifacts": artifacts,
            },
            "enrichment_delivery": {
                "status": "not_requested",
                "validation_mode": "not_requested",
                "papers": {"valid": [], "invalid": [], "missing": []},
                "artifacts": {},
            },
        }
        require_run_manifest_delivery_contract(manifest)

        manifest["core_delivery"]["status"] = "partial"
        with self.assertRaisesRegex(ValueError, "status does not match"):
            require_run_manifest_delivery_contract(manifest)

        manifest["core_delivery"]["status"] = "complete"
        manifest["enrichment_delivery"] = {
            "status": "complete",
            "validation_mode": "coupled_full",
            "papers": outcomes,
            "artifacts": artifacts,
        }
        with self.assertRaisesRegex(ValueError, "CORE delivery requires empty enrichment"):
            require_run_manifest_delivery_contract(manifest)

    def test_delivery_contract_accepts_historical_coupled_full(self) -> None:
        outcomes = {"valid": ["x"], "invalid": [], "missing": []}
        artifacts = {"x": {"literature_hvs_candidates.json": {"sha256": "hash"}}}
        delivery = {
            "status": "complete",
            "validation_mode": "coupled_full",
            "papers": outcomes,
            "artifacts": artifacts,
        }
        manifest = {
            "papers": outcomes,
            "artifacts": artifacts,
            "core_delivery": dict(delivery),
            "enrichment_delivery": dict(delivery),
        }
        require_run_manifest_delivery_contract(manifest)

        manifest["enrichment_delivery"] = {
            **delivery,
            "papers": {"valid": [], "invalid": ["x"], "missing": []},
            "status": "unavailable",
        }
        with self.assertRaisesRegex(ValueError, "coupled FULL deliveries must match"):
            require_run_manifest_delivery_contract(manifest)

    def test_delivery_contract_decoupled_full_pairing(self) -> None:
        core_outcomes = {"valid": ["x"], "invalid": ["y"], "missing": []}
        enrichment_outcomes = {"valid": [], "invalid": ["x", "y"], "missing": []}
        artifacts = {
            "x": {"literature_hvs_candidates.json": {"sha256": "hash-x"}},
            "y": {"literature_hvs_candidates.json": {"sha256": "hash-y"}},
        }
        manifest = {
            "papers": core_outcomes,
            "artifacts": artifacts,
            "core_delivery": {
                "status": "partial",
                "validation_mode": "full_core",
                "papers": core_outcomes,
                "artifacts": artifacts,
            },
            "enrichment_delivery": {
                "status": "unavailable",
                "validation_mode": "full_enrichment",
                "papers": enrichment_outcomes,
                "artifacts": artifacts,
            },
        }
        # core_valid + enrichment_invalid is the designed decoupled shape.
        require_run_manifest_delivery_contract(manifest)

        # Enrichment validity requires core validity.
        broken = json.loads(json.dumps(manifest))
        broken["enrichment_delivery"]["papers"] = {
            "valid": ["y"],
            "invalid": ["x"],
            "missing": [],
        }
        broken["enrichment_delivery"]["status"] = "partial"
        with self.assertRaisesRegex(ValueError, "enrichment validity requires core validity"):
            require_run_manifest_delivery_contract(broken)

        # The enrichment delivery must carry the strict FULL validation mode.
        broken = json.loads(json.dumps(manifest))
        broken["enrichment_delivery"]["validation_mode"] = "coupled_full"
        with self.assertRaisesRegex(ValueError, "full_enrichment"):
            require_run_manifest_delivery_contract(broken)

        # Missing papers are shared by both deliveries.
        broken = json.loads(json.dumps(manifest))
        broken["enrichment_delivery"]["papers"]["missing"] = ["z"]
        broken["enrichment_delivery"]["papers"]["invalid"] = ["x", "y"]
        with self.assertRaisesRegex(ValueError, "share missing papers"):
            require_run_manifest_delivery_contract(broken)

        # The compatibility views always mirror the core delivery.
        broken = json.loads(json.dumps(manifest))
        broken["papers"] = enrichment_outcomes
        with self.assertRaisesRegex(ValueError, "compatibility view must match core_delivery"):
            require_run_manifest_delivery_contract(broken)

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

    def test_resume_skips_success_and_archives_only_incomplete_papers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            success = run_dir / "ok"
            success.mkdir()
            (success / "report.json").write_text('{"status":"ok"}')
            failed = run_dir / "failed"
            (failed / "attempts").mkdir(parents=True)
            (failed / "report.json").write_text('{"status":"transport_error"}')
            context_only = run_dir / "context-only"
            context_only.mkdir()
            (context_only / "context_manifest.json").write_text("{}")

            plan = prepare_run_resume(
                run_dir,
                ["ok", "failed", "context-only", "missing"],
            )

            self.assertEqual(plan["skipped_success"], ["ok"])
            self.assertEqual(plan["pending"], ["failed", "context-only", "missing"])
            self.assertEqual(list(plan["archived"]), ["failed"])
            self.assertTrue(Path(plan["archived"]["failed"]).is_dir())
            self.assertTrue((run_dir / "context-only" / "context_manifest.json").is_file())

    def test_resume_refuses_sealed_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "run_manifest.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "sealed"):
                prepare_run_resume(run_dir, ["x"])

    def test_external_failure_retry_accepts_only_transport_errors_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            for paper_id, status in {
                "transport-a": "transport_error",
                "transport-b": "transport_error",
                "workflow": "validator_errors",
                "success": "ok",
            }.items():
                paper_dir = run_dir / paper_id
                paper_dir.mkdir()
                (paper_dir / "report.json").write_text(
                    json.dumps(
                        {
                            "status": status,
                            "error": "HTTPError: HTTP Error 503: Service Unavailable",
                        }
                    ),
                    encoding="utf-8",
                )

            with self.assertRaisesRegex(ValueError, "external-service"):
                prepare_external_failure_retry(
                    run_dir,
                    ["transport-a", "transport-b", "workflow", "success"],
                    ["transport-a", "workflow"],
                )
            self.assertTrue((run_dir / "transport-a" / "report.json").is_file())

            plan = prepare_external_failure_retry(
                run_dir,
                ["transport-a", "transport-b", "workflow", "success"],
                ["transport-b", "transport-a"],
            )
            self.assertEqual(plan["pending"], ["transport-b", "transport-a"])
            self.assertEqual(list(plan["archived"]), ["transport-b", "transport-a"])
            self.assertFalse((run_dir / "transport-a").exists())
            self.assertFalse((run_dir / "transport-b").exists())

    def test_external_failure_retry_rejects_nontransient_http_400(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            paper_dir = run_dir / "bad-request"
            paper_dir.mkdir()
            (paper_dir / "report.json").write_text(
                json.dumps(
                    {
                        "status": "transport_error",
                        "error": "cand-008: HTTPError: HTTP Error 400: Bad Request",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "request/configuration"):
                prepare_external_failure_retry(
                    run_dir, ["bad-request"], ["bad-request"]
                )
            self.assertTrue((paper_dir / "report.json").is_file())

    def test_external_failure_retry_prefers_structured_policy_over_legacy_text(self) -> None:
        retryable = {
            "status": "transport_error",
            "transport_error": {
                "category": "authentication",
                "http_status": 401,
                "manual_retry_eligible": True,
            },
            "error": "HTTP 400 stale legacy text",
        }
        blocked = {
            "status": "transport_error",
            "transport_error": {
                "category": "context_limit",
                "http_status": 400,
                "manual_retry_eligible": False,
            },
            "error": "TimeoutError stale legacy text",
        }

        self.assertTrue(external_failure_retry_eligibility(retryable)[0])
        self.assertFalse(external_failure_retry_eligibility(blocked)[0])

    def test_external_failure_retry_rejects_sealed_or_unknown_papers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            paper_dir = run_dir / "transport"
            paper_dir.mkdir()
            (paper_dir / "report.json").write_text(
                '{"status":"transport_error","error":"TimeoutError: timed out"}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "not part"):
                prepare_external_failure_retry(
                    run_dir, ["transport"], ["not-in-run"]
                )
            (run_dir / "run_manifest.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "sealed"):
                prepare_external_failure_retry(
                    run_dir, ["transport"], ["transport"]
                )

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
                },
                "candidates": [],
            }
            (paper / "literature_hvs_candidates.json").write_text(json.dumps(document))
            (paper / "report.json").write_text('{"status":"ok"}')
            (paper / "context_manifest.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "leakage audit"):
                seal_run(
                    run_dir,
                    workspace=root,
                    validator_module=FakeValidator(),
                    current_component_hashes=config["method"]["provenance"]["components"],
                )
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
            manifest = seal_run(
                run_dir,
                workspace=root,
                validator_module=FakeValidator(),
                current_component_hashes=config["method"]["provenance"]["components"],
            )
            self.assertEqual(manifest["core_delivery"]["papers"]["valid"], ["x"])
            self.assertEqual(manifest["core_delivery"]["status"], "complete")
            self.assertEqual(
                manifest["core_delivery"]["validation_mode"], "full_core"
            )
            self.assertEqual(manifest["papers"], manifest["core_delivery"]["papers"])
            self.assertEqual(
                manifest["artifacts"], manifest["core_delivery"]["artifacts"]
            )
            self.assertEqual(manifest["enrichment_delivery"]["status"], "complete")
            self.assertEqual(
                manifest["enrichment_delivery"]["validation_mode"], "full_enrichment"
            )
            self.assertEqual(
                manifest["component_hashes"],
                config["method"]["provenance"]["components"],
            )
            self.assertEqual(manifest["leakage_audit"]["status"], "clean")
            self.assertEqual(manifest["leakage_audit"]["path"], "leakage_audit.json")
            self.assertEqual(len(manifest["leakage_audit"]["sha256"]), 64)
            with self.assertRaisesRegex(ValueError, "already sealed"):
                seal_run(
                    run_dir,
                    workspace=root,
                    validator_module=FakeValidator(),
                    current_component_hashes=config["method"]["provenance"]["components"],
                )

    def test_seal_rejects_validator_scorer_and_normalizer_drift_before_manifest(self) -> None:
        for component in ("validator", "scorer", "normalizer"):
            with self.subTest(component=component), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                run_dir = root / "r"
                config = self.config()
                ensure_run_config(run_dir, config)
                (run_dir / "leakage_audit.json").write_text(
                    json.dumps(
                        {
                            "schema": schema_ref("benchmark.leakage_audit"),
                            "run_dir": str(run_dir.resolve()),
                            "files_scanned": 0,
                            "markers_scanned": 0,
                            "hits": [],
                            "status": "clean",
                        }
                    )
                )
                current = dict(config["method"]["provenance"]["components"])
                current[component] = f"{component}-current"
                with self.assertRaisesRegex(ValueError, rf"provenance mismatch.*{component}"):
                    seal_run(
                        run_dir,
                        workspace=root,
                        validator_module=FakeValidator(),
                        current_component_hashes=current,
                    )
                self.assertFalse((run_dir / "run_manifest.json").exists())

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
            manifest = seal_run(
                run_dir,
                workspace=root,
                validator_module=FakeValidator(),
                current_component_hashes=self.method()["provenance"]["components"],
            )
            self.assertEqual(manifest["leakage_audit"]["status"], "contaminated")

    def test_seal_rejects_nonempty_core_enrichment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "r"
            method = self.method()
            method["parameters"] = {
                "task_surface": "core_prov",
                "task_surface_sha256": "synthetic",
            }
            config = build_run_config(
                run_id="r1",
                method=method,
                expected_papers=["x"],
                code={"commit": "abc", "dirty": True},
            )
            ensure_run_config(run_dir, config)
            paper = run_dir / "x"
            paper.mkdir()
            document = {
                "extraction": {
                    "provenance": {
                        "parameters": {"method_fingerprint": config["method_fingerprint"]}
                    }
                },
                "candidates": [
                    {
                        "photometry": [{"synthetic": True}],
                        "spectroscopy": [],
                        "stellar_parameters": {"other": []},
                        "abundances": [],
                        "quality_flags": [],
                        "orbit": {"other": []},
                        "astrophysical_origin": {"hypothesis_metrics": [], "other": []},
                        "extra": [],
                    }
                ],
            }
            (paper / "literature_hvs_candidates.json").write_text(json.dumps(document))
            (paper / "report.json").write_text('{"status":"ok"}')
            (paper / "context_manifest.json").write_text("{}")
            (run_dir / "leakage_audit.json").write_text(
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
            manifest = seal_run(
                run_dir,
                workspace=root,
                validator_module=FakeValidator(),
                current_component_hashes=method["provenance"]["components"],
            )
            self.assertEqual(manifest["core_delivery"]["papers"]["invalid"], ["x"])
            self.assertEqual(manifest["core_delivery"]["status"], "unavailable")
            self.assertEqual(
                manifest["core_delivery"]["validation_mode"], "core_prov"
            )
            self.assertEqual(
                manifest["enrichment_delivery"],
                {
                    "status": "not_requested",
                    "validation_mode": "not_requested",
                    "papers": {"valid": [], "invalid": [], "missing": []},
                    "artifacts": {},
                },
            )


    def test_seal_full_decouples_core_and_enrichment_delivery(self) -> None:
        # Task 3 Step 2: core valid + enrichment invalid -> the manifest
        # reports core_valid and enrichment_invalid; strict FULL validation
        # is retained for the enrichment diagnostic and the on-disk FULL
        # document is never projected in place.
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
                },
                "candidates": [
                    {
                        "identifiers": {"record_id": "x:cand-001"},
                        "photometry": [{"synthetic": True}],
                    }
                ],
            }
            (paper / "literature_hvs_candidates.json").write_text(json.dumps(document))
            (paper / "report.json").write_text('{"status":"ok"}')
            (paper / "context_manifest.json").write_text("{}")
            (run_dir / "leakage_audit.json").write_text(
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
            manifest = seal_run(
                run_dir,
                workspace=root,
                validator_module=EnrichmentAwareFakeValidator(),
                current_component_hashes=config["method"]["provenance"]["components"],
            )
            self.assertEqual(manifest["core_delivery"]["papers"]["valid"], ["x"])
            self.assertEqual(manifest["core_delivery"]["status"], "complete")
            self.assertEqual(manifest["core_delivery"]["validation_mode"], "full_core")
            self.assertEqual(manifest["enrichment_delivery"]["papers"]["invalid"], ["x"])
            self.assertEqual(manifest["enrichment_delivery"]["status"], "unavailable")
            self.assertEqual(
                manifest["enrichment_delivery"]["validation_mode"], "full_enrichment"
            )
            self.assertEqual(manifest["papers"], manifest["core_delivery"]["papers"])
            on_disk = json.loads(
                (paper / "literature_hvs_candidates.json").read_text()
            )
            self.assertTrue(on_disk["candidates"][0]["photometry"])


if __name__ == "__main__":
    unittest.main()
