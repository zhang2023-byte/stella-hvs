from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from stella.benchmark.coding_agent_baseline import (
    BASELINE_PRODUCER,
    collect_bundle,
    create_baseline_run_config,
    finalize_baseline_run,
    launch_adapter,
    load_bundle,
    prepare_bundle,
)
from stella.benchmark.campaign import sha256_file
from stella.benchmark.gold import upgrade_annotation
from stella.benchmark.gold_selection import build_gold_selection
from stella.benchmark.pricing import build_pricing_snapshot
from stella.benchmark.run_contract import require_v6_run_manifest
from stella.benchmark.scoring import score_formal_campaign_run
from stella.schema_registry import schema_ref


ROOT = Path(__file__).resolve().parents[1]
ARXIV_ID = "2406.99999"
RUN_ID = "coding-baseline-fixture"


class FakeValidator:
    def __init__(self, errors: list[str] | None = None) -> None:
        self.errors = errors or []

    def validate_hvs_candidates_report(
        self, payload, *, workspace, require_complete
    ):
        del payload, workspace, require_complete
        return type(
            "Report", (), {"errors": self.errors, "warnings": []}
        )()


def make_workspace(root: Path) -> None:
    rules = root / "skills" / "hvs-candidates-extraction" / "rules"
    rules.parent.mkdir(parents=True)
    shutil.copytree(
        ROOT / "skills" / "hvs-candidates-extraction" / "rules", rules
    )
    (rules.parent / "SKILL.md").write_text("# Shared rules\n", encoding="utf-8")
    scripts = root / "scripts"
    scripts.mkdir()
    (scripts / "validate_hvs_candidates.py").write_text(
        "# fixture validator\n", encoding="utf-8"
    )
    paper = root / "literature" / ARXIV_ID
    source = paper / "arxiv_source"
    source.mkdir(parents=True)
    (source / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "No qualifying candidates are reported.\n"
        "\\end{document}\n",
        encoding="utf-8",
    )


def create_config(
    root: Path, *, campaign_sha256: str = "a" * 64
) -> tuple[Path, dict]:
    config = create_baseline_run_config(
        root,
        run_id=RUN_ID,
        papers=[ARXIV_ID],
        scope="full_dev",
        campaign_binding={
            "campaign_id": "hvs-extraction-v6",
            "manifest_path": "campaign.json",
            "manifest_sha256": campaign_sha256,
        },
        runtime_name="fixture-agent",
        runtime_release="1.2.3",
        model_id="fixture-model",
        code={"revision": "abc", "clean_for_dev": True},
    )
    run_dir = (
        root
        / "benchmark"
        / "campaigns"
        / "hvs-extraction-v6"
        / "runs"
        / RUN_ID
    )
    return run_dir, config


def valid_document(config: dict) -> dict:
    return {
        "schema": schema_ref("literature_hvs_candidates"),
        "generated_at": "2026-07-26T00:00:00+00:00",
        "paper": {"arxiv_id": ARXIV_ID},
        "inputs": {
            "campaign_id": "hvs-extraction-v6",
            "source_run_id": RUN_ID,
        },
        "production": {
            "producer": BASELINE_PRODUCER,
            "method_fingerprint": config["method_fingerprint"],
            "component_hashes": config["component_hashes"],
        },
        "extraction": {
            "status": "complete",
            "roster_status": "no_candidates",
        },
        "roster": {"status": "complete", "reviewed_groups": []},
        "candidates": [],
    }


class CodingAgentBaselineTest(unittest.TestCase):
    def test_prepare_uses_canonical_input_boundary_and_no_private_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            make_workspace(workspace)
            run_dir, _ = create_config(workspace)
            bundle = prepare_bundle(
                workspace=workspace,
                run_dir=run_dir,
                bundle_root=workspace / "bundles",
                arxiv_id=ARXIV_ID,
            )
            paths = {
                path.relative_to(bundle.root).as_posix()
                for path in bundle.root.rglob("*")
                if path.is_file()
            }
            self.assertIn("inputs/prepared_input.json", paths)
            self.assertIn("skill/rules/hvs-roster.yaml", paths)
            self.assertNotIn("catalog_review.json", "\n".join(paths))
            self.assertFalse(any("gold" in path.lower() for path in paths))
            task = json.loads(bundle.task_path.read_text(encoding="utf-8"))
            self.assertEqual(
                task["output_schema"], schema_ref("literature_hvs_candidates")
            )
            self.assertEqual(task["producer"], BASELINE_PRODUCER)

    def test_launch_clears_gold_and_loader_rejects_output_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            make_workspace(workspace)
            run_dir, _ = create_config(workspace)
            bundle = prepare_bundle(
                workspace=workspace,
                run_dir=run_dir,
                bundle_root=workspace / "bundles",
                arxiv_id=ARXIV_ID,
            )
            adapter = workspace / "adapter.py"
            adapter.write_text(
                "import json, os, pathlib\n"
                "pathlib.Path('seen.json').write_text(json.dumps("
                "{'gold': os.environ.get('STELLA_GOLD_DIR'), "
                "'cwd': os.getcwd()}))\n",
                encoding="utf-8",
            )
            launch_adapter(
                bundle=bundle,
                argv=[os.environ.get("PYTHON", "python"), str(adapter)],
                base_env={
                    "PATH": os.environ.get("PATH", ""),
                    "STELLA_GOLD_DIR": "/private/gold",
                },
            )
            seen = json.loads((bundle.root / "seen.json").read_text())
            self.assertIsNone(seen["gold"])
            self.assertEqual(Path(seen["cwd"]).resolve(), bundle.root.resolve())
            task = json.loads(bundle.task_path.read_text(encoding="utf-8"))
            task["output"] = "../../escape.json"
            bundle.task_path.write_text(json.dumps(task), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "output path"):
                load_bundle(bundle.root)

    def test_collect_requires_v3_baseline_bindings_and_preserves_core(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            make_workspace(workspace)
            run_dir, config = create_config(workspace)
            bundle = prepare_bundle(
                workspace=workspace,
                run_dir=run_dir,
                bundle_root=workspace / "bundles",
                arxiv_id=ARXIV_ID,
            )
            document = valid_document(config)
            bundle.output_path.write_text(json.dumps(document), encoding="utf-8")
            report = collect_bundle(
                workspace=workspace,
                run_dir=run_dir,
                bundle=bundle,
                validator_module=FakeValidator(),
            )
            self.assertEqual(report["status"], "complete")
            archived = json.loads(
                (
                    run_dir / ARXIV_ID / "literature_hvs_candidates.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(archived, document)
            self.assertNotIn("method_chain", archived)
            self.assertNotIn("full_fields", archived)

    def test_input_mutation_or_wrong_producer_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            make_workspace(workspace)
            run_dir, config = create_config(workspace)
            bundle = prepare_bundle(
                workspace=workspace,
                run_dir=run_dir,
                bundle_root=workspace / "bundles",
                arxiv_id=ARXIV_ID,
            )
            document = valid_document(config)
            document["production"]["producer"] = "hvs_candidate_extraction"
            bundle.output_path.write_text(json.dumps(document), encoding="utf-8")
            report = collect_bundle(
                workspace=workspace,
                run_dir=run_dir,
                bundle=bundle,
                validator_module=FakeValidator(),
            )
            self.assertEqual(report["failure"]["code"], "validator_errors")

            (bundle.root / "inputs" / "prepared_input.json").write_text(
                "{}", encoding="utf-8"
            )
            report = collect_bundle(
                workspace=workspace,
                run_dir=run_dir,
                bundle=bundle,
                validator_module=FakeValidator(),
            )
            self.assertEqual(report["failure"]["code"], "input_mutated")

    def test_finalize_builds_the_same_v5_delivery_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            make_workspace(workspace)
            run_dir, config = create_config(workspace)
            bundle = prepare_bundle(
                workspace=workspace,
                run_dir=run_dir,
                bundle_root=workspace / "bundles",
                arxiv_id=ARXIV_ID,
            )
            bundle.output_path.write_text(
                json.dumps(valid_document(config)), encoding="utf-8"
            )
            collect_bundle(
                workspace=workspace,
                run_dir=run_dir,
                bundle=bundle,
                validator_module=FakeValidator(),
            )
            summary, manifest = finalize_baseline_run(run_dir)
            self.assertEqual(summary["totals"]["delivered"], 1)
            l1, l2 = require_v6_run_manifest(manifest)
            self.assertEqual(l1["complete"], [ARXIV_ID])
            self.assertEqual(l2["complete"], [ARXIV_ID])
            self.assertEqual(l2["candidate_counts"]["total"], 0)
            with self.assertRaisesRegex(ValueError, "already finalized"):
                finalize_baseline_run(run_dir)

    def test_v3_schema_rejects_embedded_supplement_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            make_workspace(workspace)
            run_dir, config = create_config(workspace)
            bundle = prepare_bundle(
                workspace=workspace,
                run_dir=run_dir,
                bundle_root=workspace / "bundles",
                arxiv_id=ARXIV_ID,
            )
            document = valid_document(config)
            document["method_chain"] = {"steps": []}
            bundle.output_path.write_text(json.dumps(document), encoding="utf-8")
            report = collect_bundle(
                workspace=workspace,
                run_dir=run_dir,
                bundle=bundle,
                validator_module=FakeValidator(),
            )
            self.assertEqual(report["status"], "failed")

    def test_formal_scorer_accepts_the_baseline_v3_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            make_workspace(workspace)
            campaign_path = workspace / "campaign.json"
            campaign_path.write_text(
                json.dumps(
                    {
                        "schema": schema_ref("benchmark.campaign"),
                        "campaign_id": "hvs-extraction-v6",
                        "papers": [{"arxiv_id": ARXIV_ID, "split": "dev"}],
                    }
                ),
                encoding="utf-8",
            )
            run_dir, config = create_config(
                workspace, campaign_sha256=sha256_file(campaign_path)
            )
            bundle = prepare_bundle(
                workspace=workspace,
                run_dir=run_dir,
                bundle_root=workspace / "bundles",
                arxiv_id=ARXIV_ID,
            )
            bundle.output_path.write_text(
                json.dumps(valid_document(config)), encoding="utf-8"
            )
            collect_bundle(
                workspace=workspace,
                run_dir=run_dir,
                bundle=bundle,
                validator_module=FakeValidator(),
            )
            finalize_baseline_run(run_dir)

            gold_dir = workspace / "gold"
            annotation_dir = gold_dir / ARXIV_ID
            annotation_dir.mkdir(parents=True)
            yaml_path = annotation_dir / "annotation_expert.yaml"
            annotation_path = annotation_dir / "annotation_expert.json"
            annotation = {
                "schema": schema_ref("benchmark.gold_annotation"),
                "arxiv_id": ARXIV_ID,
                "annotator": "expert",
                "annotated_at": "2026-08-02",
                "guideline_version": "fixture",
                "evidence_basis": "pdf",
                "status": "no_candidates",
                "candidates": [],
                "notes": "Synthetic negative fixture.",
            }
            yaml_path.write_text(
                yaml.safe_dump(annotation, sort_keys=False), encoding="utf-8"
            )
            annotation_path.write_text(
                json.dumps(upgrade_annotation(annotation)), encoding="utf-8"
            )
            gold_manifest = gold_dir / "gold_manifest.json"
            gold_manifest.write_text(
                json.dumps(
                    {
                        "schema": schema_ref("benchmark.gold_manifest"),
                        "files": [
                            *[
                                {
                                    "arxiv_id": ARXIV_ID,
                                    "file": path.relative_to(gold_dir).as_posix(),
                                    "sha256": sha256_file(path),
                                    "bytes": path.stat().st_size,
                                }
                                for path in (annotation_path, yaml_path)
                            ]
                        ],
                    }
                ),
                encoding="utf-8",
            )
            gold_selection = gold_dir / "selection.json"
            gold_selection.write_text(
                json.dumps(
                    build_gold_selection(
                        campaign_path=campaign_path,
                        gold_manifest_path=gold_manifest,
                        gold_dir=gold_dir,
                        split="dev",
                        selection_id="fixture-selection",
                        annotator_map={ARXIV_ID: "expert"},
                    )
                ),
                encoding="utf-8",
            )
            pricing_snapshot = workspace / "pricing.json"
            pricing_snapshot.write_text(
                json.dumps(
                    build_pricing_snapshot(
                        {
                            "snapshot_id": "fixture-pricing",
                            "source": {
                                "name": "TokenDance",
                                "url": "https://tokendance.space/models",
                                "captured_at": "2026-08-03T00:00:00+00:00",
                                "effective_at": None,
                            },
                            "currency": "CNY",
                            "routes": [
                                {
                                    "provider": "fixture",
                                    "model": "fixture-model",
                                    "source_route": {
                                        "model_slug": "fixture-model",
                                        "provider_slug": "fixture",
                                        "price_id": "fixture",
                                    },
                                    "rates_cny_per_million_tokens": {
                                        "uncached_input": "0",
                                        "cached_input": "0",
                                        "output": "0",
                                    },
                                    "cached_input_basis": "listed",
                                }
                            ],
                        }
                    )
                ),
                encoding="utf-8",
            )
            scorecard, details = score_formal_campaign_run(
                campaign_path=campaign_path,
                split="dev",
                run_dir=run_dir,
                gold_dir=gold_dir,
                gold_manifest_path=gold_manifest,
                gold_selection_path=gold_selection,
                pricing_snapshot_path=pricing_snapshot,
                bootstrap_iterations=5,
                workspace=workspace,
            )
            self.assertEqual(scorecard["l0"]["roster_delivery"]["complete"], 1)
            self.assertNotIn("delivery_counts", scorecard)
            self.assertNotIn("papers_missing_ai_output", scorecard)
            self.assertEqual(
                scorecard["operations"]["estimated_api_cost"]["status"],
                "not_applicable",
            )
            serialized_scorecard = json.dumps(scorecard, ensure_ascii=False)
            self.assertNotIn("Synthetic negative fixture.", serialized_scorecard)
            self.assertNotIn("annotation_expert", serialized_scorecard)
            self.assertEqual(scorecard["run_source"]["mode"], "formal_campaign")
            self.assertEqual(
                scorecard["run_label"], f"{RUN_ID}--gold-fixture-selection"
            )
            selection = scorecard["formal"]["gold_selection"]
            self.assertEqual(selection["selection_id"], "fixture-selection")
            self.assertEqual(
                details["gold_selection"]["annotators"], {ARXIV_ID: "expert"}
            )
            self.assertEqual(details["papers"][0]["gold_annotator"], "expert")


if __name__ == "__main__":
    unittest.main()
