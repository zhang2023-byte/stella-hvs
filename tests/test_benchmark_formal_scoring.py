from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from stella.benchmark.campaign import sha256_file
from stella.benchmark.gold import upgrade_annotation
from stella.benchmark.gold_selection import build_gold_selection
from stella.benchmark.run_contract import canonical_sha256
from stella.benchmark.scoring import _formal_run_bindings, load_formal_gold_snapshot
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


if __name__ == "__main__":
    unittest.main()
