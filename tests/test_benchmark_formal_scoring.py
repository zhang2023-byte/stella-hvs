from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from stella.benchmark.campaign import sha256_file
from stella.benchmark.gold import upgrade_annotation
from stella.benchmark.gold_selection import build_gold_selection
from stella.benchmark.run_contract import canonical_sha256
from stella.benchmark.scoring import (
    _formal_run_bindings,
    _require_sealed_artifacts,
    load_formal_gold_snapshot,
    score_formal_campaign_run,
)
from stella.schema_registry import ACTIVE_BENCHMARK_CAMPAIGN, schema_ref


P1 = "2401.00001"
P2 = "2401.00002"


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def fixtures(root: Path) -> tuple[Path, Path, dict[str, str]]:
    campaign_path = root / "campaign.json"
    write_json(
        campaign_path,
        {
            "schema": schema_ref("benchmark.campaign"),
            "campaign_id": ACTIVE_BENCHMARK_CAMPAIGN,
            "papers": [
                {"arxiv_id": P1, "split": "dev"},
                {"arxiv_id": P2, "split": "dev"},
            ],
        },
    )
    campaign_binding = {
        "campaign_id": ACTIVE_BENCHMARK_CAMPAIGN,
        "manifest_path": str(campaign_path),
        "manifest_sha256": sha256_file(campaign_path),
    }
    components = {
        "scorer": "a" * 64,
        "identity_matching": "b" * 64,
        "unit_table": "c" * 64,
    }
    config = {
        "schema": schema_ref("benchmark.run_config"),
        "run_id": "run-1",
        "campaign": campaign_binding,
        "scope": "full_dev",
        "papers": [P1, P2],
        "method_fingerprint": canonical_sha256({"method": "fixture"}),
        "component_hashes": components,
    }
    run_dir = root / "run"
    write_json(run_dir / "run_config.json", config)
    empty_usage = {
        "prompt_tokens": 0,
        "cached_input_tokens": 0,
        "uncached_input_tokens": 0,
        "completion_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
        "api_calls": 0,
        "telemetry_status": "not_applicable",
        "warnings": [],
    }
    format_validation = {
        "observed_units": 0,
        "valid_first_pass": 0,
        "valid_after_correction": 0,
        "invalid": 0,
        "not_observed": 0,
        "first_pass_rate": 0.0,
        "final_valid_rate": 0.0,
    }
    usage = {
        "by_role": {
            "roster": dict(empty_usage),
            "core_fields": dict(empty_usage),
        },
        "total": dict(empty_usage),
    }
    write_json(
        run_dir / "run_summary.json",
        {
            "schema": schema_ref("benchmark.run_summary"),
            "format_validation": format_validation,
            "usage": usage,
        },
    )
    write_json(
        run_dir / "run_manifest.json",
        {
            "schema": schema_ref("benchmark.run_manifest"),
            "run_id": "run-1",
            "campaign": campaign_binding,
            "papers": [P1, P2],
            "method_fingerprint": config["method_fingerprint"],
            "component_hashes": components,
            "run_config_sha256": sha256_file(run_dir / "run_config.json"),
            "run_summary_sha256": sha256_file(run_dir / "run_summary.json"),
            "l1_roster_delivery": {
                "complete": [P1, P2],
                "failed": [],
                "missing": [],
            },
            "l2_core_field_delivery": {
                "complete": [P1],
                "partial": [P2],
                "failed": [],
                "missing": [],
                "candidate_counts": {
                    "total": 1,
                    "fields_complete": 0,
                    "field_extraction_failed": 1,
                },
            },
            "l0": {
                "format_validation": {
                    **format_validation,
                }
            },
            "usage": usage,
            "artifacts": {},
        },
    )
    return campaign_path, run_dir, components


def gold_annotation(arxiv_id: str, annotator: str, notes: str) -> dict:
    return {
        "schema": schema_ref("benchmark.gold_annotation"),
        "arxiv_id": arxiv_id,
        "annotator": annotator,
        "annotated_at": "2026-08-02",
        "guideline_version": "fixture",
        "evidence_basis": "pdf",
        "status": "no_candidates",
        "candidates": [],
        "notes": notes,
    }


def write_gold_twin(
    gold_dir: Path, arxiv_id: str, annotator: str, notes: str
) -> list[dict]:
    paper_dir = gold_dir / arxiv_id
    paper_dir.mkdir(parents=True, exist_ok=True)
    payload = gold_annotation(arxiv_id, annotator, notes)
    yaml_path = paper_dir / f"annotation_{annotator}.yaml"
    json_path = paper_dir / f"annotation_{annotator}.json"
    yaml_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    json_path.write_text(json.dumps(upgrade_annotation(payload)), encoding="utf-8")
    return [
        {
            "arxiv_id": arxiv_id,
            "file": path.relative_to(gold_dir).as_posix(),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for path in (json_path, yaml_path)
    ]


class FormalScoringContractTest(unittest.TestCase):
    def test_formal_gold_snapshot_uses_per_paper_selection_without_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_path, _, _ = fixtures(root)
            gold_dir = root / "gold"
            records = []
            records.extend(write_gold_twin(gold_dir, P1, "expert_a", "chosen-a"))
            records.extend(write_gold_twin(gold_dir, P1, "expert_b", "ignored-b"))
            records.extend(write_gold_twin(gold_dir, P2, "expert_b", "chosen-b"))
            gold_manifest_path = root / "gold-manifest.json"
            write_json(
                gold_manifest_path,
                {
                    "schema": schema_ref("benchmark.gold_manifest"),
                    "files": sorted(records, key=lambda item: item["file"]),
                },
            )
            profile = build_gold_selection(
                campaign_path=campaign_path,
                gold_manifest_path=gold_manifest_path,
                gold_dir=gold_dir,
                split="dev",
                selection_id="dev-primary-v1",
                annotator_map={P1: "expert_a", P2: "expert_b"},
            )
            selection_path = root / "selection.json"
            write_json(selection_path, profile)

            annotations, snapshot = load_formal_gold_snapshot(
                gold_dir=gold_dir,
                gold_manifest_path=gold_manifest_path,
                gold_selection_path=selection_path,
                paper_ids=[P1, P2],
                campaign_id=ACTIVE_BENCHMARK_CAMPAIGN,
                campaign_sha256=sha256_file(campaign_path),
                split="dev",
            )

            self.assertEqual(annotations[P1]["notes"], "chosen-a")
            self.assertEqual(annotations[P2]["notes"], "chosen-b")
            self.assertEqual(snapshot["selection_id"], "dev-primary-v1")
            self.assertEqual(snapshot["annotators"], {P1: "expert_a", P2: "expert_b"})

    def test_formal_gold_snapshot_rejects_missing_selection_paper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_path, _, _ = fixtures(root)
            gold_dir = root / "gold"
            records = write_gold_twin(gold_dir, P1, "expert_a", "chosen-a")
            gold_manifest_path = root / "gold-manifest.json"
            write_json(
                gold_manifest_path,
                {"schema": schema_ref("benchmark.gold_manifest"), "files": records},
            )
            selection_path = root / "selection.json"
            write_json(
                selection_path,
                {
                    "schema": schema_ref("benchmark.gold_selection"),
                    "selection_id": "dev-primary-v1",
                    "campaign": {
                        "campaign_id": ACTIVE_BENCHMARK_CAMPAIGN,
                        "sha256": sha256_file(campaign_path),
                    },
                    "split": "dev",
                    "selected_records_sha256": canonical_sha256([]),
                    "papers": [],
                },
            )

            with self.assertRaisesRegex(ValueError, "exact campaign split order"):
                load_formal_gold_snapshot(
                    gold_dir=gold_dir,
                    gold_manifest_path=gold_manifest_path,
                    gold_selection_path=selection_path,
                    paper_ids=[P1, P2],
                    campaign_id=ACTIVE_BENCHMARK_CAMPAIGN,
                    campaign_sha256=sha256_file(campaign_path),
                    split="dev",
                )

    def test_field_partial_paper_remains_available_to_l1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign, run_dir, components = fixtures(Path(tmp))
            _, _, _, delivery, expected, _, _ = _formal_run_bindings(
                campaign_path=campaign,
                split="dev",
                run_dir=run_dir,
                workspace=Path(tmp),
                current_component_hashes=components,
            )
            self.assertEqual(expected, [P1, P2])
            self.assertEqual(delivery["papers"]["valid"], [P1, P2])

    def test_config_and_campaign_paper_sets_must_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign, run_dir, components = fixtures(Path(tmp))
            config_path = run_dir / "run_config.json"
            config = json.loads(config_path.read_text())
            config["papers"] = [P1]
            write_json(config_path, config)
            manifest_path = run_dir / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["run_config_sha256"] = sha256_file(config_path)
            write_json(manifest_path, manifest)
            with self.assertRaisesRegex(ValueError, "papers do not match"):
                _formal_run_bindings(
                    campaign_path=campaign,
                    split="dev",
                    run_dir=run_dir,
                    workspace=Path(tmp),
                    current_component_hashes=components,
                )

    def test_manifest_and_campaign_paper_order_must_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign, run_dir, components = fixtures(Path(tmp))
            manifest_path = run_dir / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["papers"] = [P2, P1]
            manifest["l1_roster_delivery"]["complete"] = [P2, P1]
            manifest["l2_core_field_delivery"]["complete"] = [P2]
            manifest["l2_core_field_delivery"]["partial"] = [P1]
            write_json(manifest_path, manifest)
            with self.assertRaisesRegex(ValueError, "manifest papers do not match"):
                _formal_run_bindings(
                    campaign_path=campaign,
                    split="dev",
                    run_dir=run_dir,
                    workspace=Path(tmp),
                    current_component_hashes=components,
                )

    def test_legacy_manifest_is_refused_for_new_scoring(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign, run_dir, components = fixtures(Path(tmp))
            manifest_path = run_dir / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["schema"]["version"] = 4
            write_json(manifest_path, manifest)
            with self.assertRaisesRegex(ValueError, "current sealed"):
                _formal_run_bindings(
                    campaign_path=campaign,
                    split="dev",
                    run_dir=run_dir,
                    workspace=Path(tmp),
                    current_component_hashes=components,
                )

    def test_tampered_summary_and_artifact_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign, run_dir, components = fixtures(root)
            summary_path = run_dir / "run_summary.json"
            summary = json.loads(summary_path.read_text())
            summary["format_validation"]["not_observed"] = 1
            write_json(summary_path, summary)
            with self.assertRaisesRegex(ValueError, "summary hash"):
                _formal_run_bindings(
                    campaign_path=campaign,
                    split="dev",
                    run_dir=run_dir,
                    workspace=root,
                    current_component_hashes=components,
                )

            artifact = run_dir / "papers" / P1 / "paper_result.json"
            write_json(artifact, {"status": "complete"})
            manifest = json.loads((run_dir / "run_manifest.json").read_text())
            manifest["artifacts"] = {
                P1: {
                    artifact.name: {
                        "sha256": "0" * 64,
                        "bytes": artifact.stat().st_size,
                    }
                }
            }
            with self.assertRaisesRegex(ValueError, "sealed artifact changed"):
                _require_sealed_artifacts(run_dir=run_dir, manifest=manifest)


class NetworkDebugScoringTest(unittest.TestCase):
    def make_debug_fixture(self, root: Path) -> tuple[Path, Path, Path, Path, Path]:
        campaign_path, run_dir, components = fixtures(root)
        pricing_dir = root / "pricing"
        pricing_path = pricing_dir / "tokendance-2026-08-03-screenshots-v1.json"
        write_json(
            pricing_path,
            json.loads(
                (
                    Path(__file__).resolve().parents[1]
                    / "benchmark"
                    / "pricing"
                    / "tokendance"
                    / "tokendance-2026-08-03-screenshots-v1.json"
                ).read_text(encoding="utf-8")
            ),
        )
        # Source formal run must sit at the sibling runs/ root of the debug
        # container, mirroring the campaign layout.
        campaign_root = root / "campaigns" / "hvs-extraction-v6"
        source_dir = campaign_root / "runs" / "run-1"
        shutil.copytree(run_dir, source_dir)
        config = json.loads((source_dir / "run_config.json").read_text())
        config["method"] = {
            "roster_model": {
                "provider": "deepseek",
                "model": "deepseek-v4-pro",
            },
            "core_field_model": {
                "provider": "deepseek",
                "model": "deepseek-v4-pro",
            },
        }
        write_json(source_dir / "run_config.json", config)

        debug_dir = campaign_root / "debug" / "debug-1"
        empty_usage = {
            "prompt_tokens": 0,
            "cached_input_tokens": 0,
            "uncached_input_tokens": 0,
            "completion_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
            "api_calls": 0,
            "telemetry_status": "not_applicable",
            "warnings": [],
        }
        format_validation = {
            "observed_units": 0,
            "valid_first_pass": 0,
            "valid_after_correction": 0,
            "invalid": 0,
            "not_observed": 0,
            "first_pass_rate": 0.0,
            "final_valid_rate": 0.0,
        }
        result_papers = []
        for arxiv_id in (P1, P2):
            paper_dir = debug_dir / "papers" / arxiv_id
            write_json(
                paper_dir / "paper_result.json",
                {
                    "schema": schema_ref("hvs_extraction.paper_result"),
                    "run_id": "debug-1",
                    "status": "complete",
                    "roster_status": "candidates_found",
                    "candidates": [
                        {"record_id": "candidate-001", "status": "fields_complete"}
                    ],
                },
            )
            write_json(
                paper_dir / "literature_hvs_candidates.json",
                {"schema": schema_ref("literature_hvs_candidates"), "candidates": []},
            )
            result_papers.append(
                {"arxiv_id": arxiv_id, "status": "complete", "origin": "copied", "copied_files": {}}
            )
        debug_result = {
            "schema": schema_ref("benchmark.network_debug_result"),
            "debug_run_id": "debug-1",
            "source_run": {
                "run_id": "run-1",
                "scope": "full_dev",
                "state": "completed",
                "run_config_sha256": sha256_file(source_dir / "run_config.json"),
                "run_summary_sha256": "0" * 64,
                "run_manifest_sha256": None,
            },
            "scope": "full_dev",
            "papers": result_papers,
            "retry_commands": 2,
            "usage": {
                "by_role": {"roster": dict(empty_usage), "core_fields": dict(empty_usage)},
                "total": dict(empty_usage),
            },
            "format_validation": format_validation,
            "terminal_network_check": {"passed": True},
        }
        debug_result["content_sha256"] = canonical_sha256(debug_result)
        write_json(debug_dir / "debug_result.json", debug_result)
        debug_config = {
            "schema": schema_ref("benchmark.network_debug_config"),
            "debug_run_id": "debug-1",
            "campaign": dict(config["campaign"]),
            "source_run": dict(debug_result["source_run"]),
            "papers": [P1, P2],
            "method_fingerprint": config["method_fingerprint"],
            "pricing_snapshot": {
                "snapshot_id": pricing_path.stem,
                "sha256": sha256_file(pricing_path),
            },
            "component_hashes": {"source": dict(components), "current": dict(components)},
            "state": "clean",
        }
        debug_config["content_sha256"] = canonical_sha256(debug_config)
        write_json(debug_dir / "debug_config.json", debug_config)

        gold_dir = root / "gold"
        records = []
        records.extend(write_gold_twin(gold_dir, P1, "expert_a", "chosen-a"))
        records.extend(write_gold_twin(gold_dir, P2, "expert_b", "chosen-b"))
        gold_manifest_path = root / "gold-manifest.json"
        write_json(
            gold_manifest_path,
            {
                "schema": schema_ref("benchmark.gold_manifest"),
                "files": sorted(records, key=lambda item: item["file"]),
            },
        )
        selection_path = root / "selection.json"
        write_json(
            selection_path,
            build_gold_selection(
                campaign_path=campaign_path,
                gold_manifest_path=gold_manifest_path,
                gold_dir=gold_dir,
                split="dev",
                selection_id="dev-primary-v1",
                annotator_map={P1: "expert_a", P2: "expert_b"},
            ),
        )
        return campaign_path, debug_dir, gold_dir, gold_manifest_path, selection_path

    def score(self, root: Path, **overrides):
        campaign_path, debug_dir, gold_dir, gold_manifest, selection = (
            self.make_debug_fixture(root)
        )
        kwargs = dict(
            campaign_path=campaign_path,
            split="dev",
            run_dir=debug_dir,
            gold_dir=gold_dir,
            gold_manifest_path=gold_manifest,
            gold_selection_path=selection,
            pricing_snapshot_path=(
                root / "pricing" / "tokendance-2026-08-03-screenshots-v1.json"
            ),
        )
        kwargs.update(overrides)
        return score_formal_campaign_run(**kwargs)

    def score_existing(self, root: Path, **overrides):
        campaign_path = root / "campaign.json"
        debug_dir = (
            root / "campaigns" / "hvs-extraction-v6" / "debug" / "debug-1"
        )
        gold_dir = root / "gold"
        kwargs = dict(
            campaign_path=campaign_path,
            split="dev",
            run_dir=debug_dir,
            gold_dir=gold_dir,
            gold_manifest_path=root / "gold-manifest.json",
            gold_selection_path=root / "selection.json",
            pricing_snapshot_path=(
                root / "pricing" / "tokendance-2026-08-03-screenshots-v1.json"
            ),
        )
        kwargs.update(overrides)
        return score_formal_campaign_run(**kwargs)

    def test_debug_run_scores_with_lineage_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scorecard, details = self.score(Path(tmp))
            self.assertEqual(scorecard["schema"], schema_ref("benchmark.scorecard"))
            self.assertEqual(scorecard["schema"]["version"], 8)
            self.assertEqual(
                scorecard["run_source"]["mode"], "formal_campaign_network_debug"
            )
            self.assertEqual(scorecard["network_debug"]["source_run_id"], "run-1")
            self.assertEqual(scorecard["network_debug"]["debug_run_id"], "debug-1")
            self.assertTrue(scorecard["network_debug"]["terminal_network_check"]["passed"])
            self.assertEqual(scorecard["l0"]["roster_delivery"]["complete"], 2)
            self.assertIn(
                "debug_result_content_hash",
                scorecard["l0"]["integrity_gate"]["checks"],
            )
            self.assertEqual(details["formal"]["run_id"], "debug-1")

    def test_debug_scoring_refuses_unfinalized_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_debug_fixture(root)
            debug_dir = (
                root / "campaigns" / "hvs-extraction-v6" / "debug" / "debug-1"
            )
            config_path = debug_dir / "debug_config.json"
            config = json.loads(config_path.read_text())
            config["state"] = "recovering"
            config["content_sha256"] = canonical_sha256(
                {k: v for k, v in config.items() if k != "content_sha256"}
            )
            write_json(config_path, config)
            with self.assertRaisesRegex(ValueError, "finalized clean"):
                self.score_existing(root)

    def test_debug_scoring_refuses_tampered_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_debug_fixture(root)
            debug_dir = (
                root / "campaigns" / "hvs-extraction-v6" / "debug" / "debug-1"
            )
            result_path = debug_dir / "debug_result.json"
            result = json.loads(result_path.read_text())
            result["retry_commands"] = 99
            write_json(result_path, result)
            with self.assertRaisesRegex(ValueError, "content hash"):
                self.score_existing(root)

    def test_debug_scoring_refuses_split_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "source scope"):
                self.score(Path(tmp), split="test")

    def test_debug_scoring_refuses_wrong_pricing_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_debug_fixture(root)
            debug_dir = (
                root / "campaigns" / "hvs-extraction-v6" / "debug" / "debug-1"
            )
            config_path = debug_dir / "debug_config.json"
            config = json.loads(config_path.read_text())
            config["pricing_snapshot"]["snapshot_id"] = "other-snapshot"
            config["content_sha256"] = canonical_sha256(
                {k: v for k, v in config.items() if k != "content_sha256"}
            )
            write_json(config_path, config)
            with self.assertRaisesRegex(ValueError, "pricing snapshot"):
                self.score_existing(root)


if __name__ == "__main__":
    unittest.main()
