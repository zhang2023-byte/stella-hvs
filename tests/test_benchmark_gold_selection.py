from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from stella.benchmark.campaign import sha256_file
from stella.benchmark.gold_assignment import load_gold_assignment, primary_annotator_map
from stella.benchmark.gold import upgrade_annotation
from stella.benchmark.gold_selection import (
    build_gold_selection,
    load_gold_selection_snapshot,
    validate_gold_manifest_twins,
    write_gold_selection_once,
)
from stella.schema_registry import ACTIVE_BENCHMARK_CAMPAIGN, schema_ref
from stella.benchmark.paths import campaign_paths


P1 = "2401.00001"
P2 = "2401.00002"


def annotation(arxiv_id: str, annotator: str) -> dict:
    return {
        "schema": schema_ref("benchmark.gold_annotation"),
        "arxiv_id": arxiv_id,
        "annotator": annotator,
        "annotated_at": "2026-08-02",
        "guideline_version": "fixture",
        "evidence_basis": "pdf",
        "status": "no_candidates",
        "candidates": [],
        "notes": "Synthetic negative fixture.",
    }


def write_twin(gold_dir: Path, arxiv_id: str, annotator: str) -> list[dict]:
    paper_dir = gold_dir / arxiv_id
    paper_dir.mkdir(parents=True, exist_ok=True)
    yaml_path = paper_dir / f"annotation_{annotator}.yaml"
    json_path = paper_dir / f"annotation_{annotator}.json"
    payload = annotation(arxiv_id, annotator)
    yaml_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    json_path.write_text(
        json.dumps(upgrade_annotation(payload), ensure_ascii=False), encoding="utf-8"
    )
    return [
        {
            "arxiv_id": arxiv_id,
            "file": path.relative_to(gold_dir).as_posix(),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for path in (json_path, yaml_path)
    ]


class GoldSelectionTest(unittest.TestCase):
    def fixtures(self, root: Path) -> tuple[Path, Path, Path]:
        campaign_path = root / "campaign.json"
        campaign_path.write_text(
            json.dumps(
                {
                    "schema": schema_ref("benchmark.campaign"),
                    "campaign_id": ACTIVE_BENCHMARK_CAMPAIGN,
                    "papers": [
                        {"arxiv_id": P1, "split": "dev"},
                        {"arxiv_id": P2, "split": "dev"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        gold_dir = root / "gold"
        records = []
        records.extend(write_twin(gold_dir, P1, "expert_a"))
        records.extend(write_twin(gold_dir, P1, "expert_b"))
        records.extend(write_twin(gold_dir, P2, "expert_b"))
        gold_manifest_path = root / "gold_manifest.json"
        gold_manifest_path.write_text(
            json.dumps(
                {
                    "schema": schema_ref("benchmark.gold_manifest"),
                    "files": sorted(records, key=lambda item: item["file"]),
                }
            ),
            encoding="utf-8",
        )
        return campaign_path, gold_manifest_path, gold_dir

    def test_builds_ordered_value_free_per_paper_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign_path, gold_manifest_path, gold_dir = self.fixtures(Path(tmp))
            profile = build_gold_selection(
                campaign_path=campaign_path,
                gold_manifest_path=gold_manifest_path,
                gold_dir=gold_dir,
                split="dev",
                selection_id="dev-primary-v1",
                annotator_map={P1: "expert_a", P2: "expert_b"},
            )

        self.assertEqual(profile["schema"], schema_ref("benchmark.gold_selection"))
        self.assertEqual([paper["arxiv_id"] for paper in profile["papers"]], [P1, P2])
        self.assertEqual(
            [paper["annotator"] for paper in profile["papers"]],
            ["expert_a", "expert_b"],
        )
        serialized = json.dumps(profile)
        for forbidden in ("candidates", "notes", "evidence", "Synthetic negative"):
            self.assertNotIn(forbidden, serialized)

    def test_selection_requires_exact_split_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign_path, gold_manifest_path, gold_dir = self.fixtures(Path(tmp))
            with self.assertRaisesRegex(ValueError, "missing.*2401.00002"):
                build_gold_selection(
                    campaign_path=campaign_path,
                    gold_manifest_path=gold_manifest_path,
                    gold_dir=gold_dir,
                    split="dev",
                    selection_id="dev-primary-v1",
                    annotator_map={P1: "expert_a"},
                )

    def test_selection_rejects_missing_selected_annotator_without_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign_path, gold_manifest_path, gold_dir = self.fixtures(Path(tmp))
            with self.assertRaisesRegex(ValueError, "annotation_expert_a"):
                build_gold_selection(
                    campaign_path=campaign_path,
                    gold_manifest_path=gold_manifest_path,
                    gold_dir=gold_dir,
                    split="dev",
                    selection_id="dev-primary-v1",
                    annotator_map={P1: "expert_a", P2: "expert_a"},
                )

    def test_manifest_twin_validation_rejects_non_deterministic_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, gold_manifest_path, gold_dir = self.fixtures(Path(tmp))
            json_path = gold_dir / P1 / "annotation_expert_a.json"
            document = json.loads(json_path.read_text(encoding="utf-8"))
            document["notes"] = "changed only in json"
            json_path.write_text(json.dumps(document), encoding="utf-8")
            manifest = json.loads(gold_manifest_path.read_text(encoding="utf-8"))
            for record in manifest["files"]:
                if record["file"] == f"{P1}/annotation_expert_a.json":
                    record["sha256"] = sha256_file(json_path)
                    record["bytes"] = json_path.stat().st_size
            with self.assertRaisesRegex(ValueError, "deterministic JSON twin"):
                validate_gold_manifest_twins(gold_dir, manifest)

    def test_selection_profile_is_write_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dev-primary-v1.json"
            payload = {
                "schema": schema_ref("benchmark.gold_selection"),
                "selection_id": "dev-primary-v1",
            }
            write_gold_selection_once(path, payload)
            with self.assertRaisesRegex(ValueError, "already exists"):
                write_gold_selection_once(path, payload)

    def test_snapshot_rejects_tampered_selection_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign_path, gold_manifest_path, gold_dir = self.fixtures(root)
            profile = build_gold_selection(
                campaign_path=campaign_path,
                gold_manifest_path=gold_manifest_path,
                gold_dir=gold_dir,
                split="dev",
                selection_id="dev-primary-v1",
                annotator_map={P1: "expert_a", P2: "expert_b"},
            )
            profile["papers"][0]["json"]["sha256"] = "0" * 64
            selection_path = root / "selection.json"
            selection_path.write_text(json.dumps(profile), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "selected-records hash mismatch"):
                load_gold_selection_snapshot(
                    selection_path=selection_path,
                    gold_manifest_path=gold_manifest_path,
                    gold_dir=gold_dir,
                    paper_ids=[P1, P2],
                    campaign_id=ACTIVE_BENCHMARK_CAMPAIGN,
                    campaign_sha256=sha256_file(campaign_path),
                    split="dev",
                )

    def test_live_v6_dev_selection_matches_assignment_and_public_gold_hashes(self) -> None:
        root = Path(__file__).resolve().parents[1]
        paths = campaign_paths(root, ACTIVE_BENCHMARK_CAMPAIGN)
        campaign = json.loads(paths.campaign_manifest.read_text(encoding="utf-8"))
        dev_ids = [
            paper["arxiv_id"]
            for paper in campaign["papers"]
            if paper["split"] == "dev"
        ]
        selection_path = paths.gold_selections / "evaluation-dev-primary-v1.json"
        selection = json.loads(selection_path.read_text(encoding="utf-8"))
        assignment = load_gold_assignment(
            paths.gold_assignments / "evaluation-primary-v1.json",
            paths.campaign_manifest,
        )
        expected_annotators = primary_annotator_map(assignment, dev_ids)
        manifest = json.loads(paths.gold_manifest.read_text(encoding="utf-8"))
        records = {record["file"]: record for record in manifest["files"]}

        self.assertEqual(selection["campaign"]["campaign_id"], ACTIVE_BENCHMARK_CAMPAIGN)
        self.assertEqual(selection["campaign"]["sha256"], sha256_file(paths.campaign_manifest))
        self.assertEqual(selection["split"], "dev")
        self.assertEqual([paper["arxiv_id"] for paper in selection["papers"]], dev_ids)
        self.assertEqual(len(selection["papers"]), 10)
        for paper in selection["papers"]:
            arxiv_id = paper["arxiv_id"]
            self.assertEqual(paper["annotator"], expected_annotators[arxiv_id])
            for twin in (paper["yaml"], paper["json"]):
                self.assertEqual(twin, records[twin["file"]])


if __name__ == "__main__":
    unittest.main()
