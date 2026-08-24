from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from stella.benchmark.gold_assignment import (
    annotation_queue,
    build_gold_assignment,
    load_gold_assignment,
    primary_annotator_map,
    write_gold_assignment_once,
)
from stella.schema_registry import ACTIVE_BENCHMARK_CAMPAIGN, schema_ref


P1 = "2401.00001"
P2 = "2401.00002"
P3 = "2401.00003"


class GoldAssignmentTest(unittest.TestCase):
    def campaign(self, root: Path) -> Path:
        path = root / "campaign.json"
        path.write_text(
            json.dumps(
                {
                    "schema": schema_ref("benchmark.campaign"),
                    "campaign_id": ACTIVE_BENCHMARK_CAMPAIGN,
                    "papers": [
                        {"arxiv_id": P1, "split": "dev"},
                        {"arxiv_id": P2, "split": "test"},
                        {"arxiv_id": P3, "split": "test"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        return path

    def assignments(self) -> dict[str, dict[str, object]]:
        return {
            P1: {"primary_annotator": "will", "additional_annotators": []},
            P2: {
                "primary_annotator": "will",
                "additional_annotators": ["shunhong_deng"],
            },
            P3: {
                "primary_annotator": "shunhong_deng",
                "additional_annotators": [],
            },
        }

    def test_builds_complete_ordered_value_free_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = self.campaign(Path(tmp))
            profile = build_gold_assignment(
                campaign_path=campaign,
                assignment_id="primary-v1",
                assignments=self.assignments(),
            )

        self.assertEqual(profile["schema"], schema_ref("benchmark.gold_assignment"))
        self.assertEqual([paper["arxiv_id"] for paper in profile["papers"]], [P1, P2, P3])
        self.assertEqual(profile["papers"][1]["primary_annotator"], "will")
        self.assertEqual(profile["papers"][1]["additional_annotators"], ["shunhong_deng"])
        rendered = json.dumps(profile)
        for forbidden in ("candidates", "notes", "evidence", "values"):
            self.assertNotIn(forbidden, rendered)

    def test_requires_exact_campaign_coverage_and_distinct_roles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            campaign = self.campaign(Path(tmp))
            missing = self.assignments()
            missing.pop(P3)
            with self.assertRaisesRegex(ValueError, "exactly cover"):
                build_gold_assignment(
                    campaign_path=campaign,
                    assignment_id="primary-v1",
                    assignments=missing,
                )
            duplicate = self.assignments()
            duplicate[P2]["additional_annotators"] = ["will"]
            with self.assertRaisesRegex(ValueError, "also be additional"):
                build_gold_assignment(
                    campaign_path=campaign,
                    assignment_id="primary-v1",
                    assignments=duplicate,
                )

    def test_queue_separates_new_resume_and_completed_per_annotator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign = self.campaign(root)
            profile = build_gold_assignment(
                campaign_path=campaign,
                assignment_id="primary-v1",
                assignments=self.assignments(),
            )
            gold_dir = root / "gold"
            (gold_dir / P2).mkdir(parents=True)
            (gold_dir / P2 / "draft_shunhong_deng.json").write_text("{}", encoding="utf-8")
            (gold_dir / P3).mkdir(parents=True)
            (gold_dir / P3 / "draft_will.json").write_text("{}", encoding="utf-8")
            manifest = {
                "schema": schema_ref("benchmark.gold_manifest"),
                "files": [
                    {"arxiv_id": P1, "file": f"{P1}/annotation_will.yaml"},
                    {"arxiv_id": P1, "file": f"{P1}/annotation_will.json"},
                    {"arxiv_id": P2, "file": f"{P2}/annotation_will.yaml"},
                    {"arxiv_id": P2, "file": f"{P2}/annotation_will.json"},
                ],
            }

            will_queue = annotation_queue(profile, manifest, gold_dir, "will")
            shunhong_queue = annotation_queue(
                profile, manifest, gold_dir, "shunhong_deng"
            )

        self.assertEqual(
            [(row["arxiv_id"], row["role"], row["status"]) for row in will_queue],
            [(P1, "primary", "completed"), (P2, "primary", "completed")],
        )
        self.assertEqual(
            [(row["arxiv_id"], row["role"], row["status"]) for row in shunhong_queue],
            [(P2, "additional", "resume"), (P3, "primary", "new")],
        )

    def test_partial_final_twin_fails_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign = self.campaign(root)
            profile = build_gold_assignment(
                campaign_path=campaign,
                assignment_id="primary-v1",
                assignments=self.assignments(),
            )
            manifest = {
                "schema": schema_ref("benchmark.gold_manifest"),
                "files": [
                    {"arxiv_id": P1, "file": f"{P1}/annotation_will.yaml"},
                ],
            }
            with self.assertRaisesRegex(ValueError, "partial final twin"):
                annotation_queue(profile, manifest, root / "gold", "will")

    def test_load_write_once_and_primary_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign = self.campaign(root)
            profile = build_gold_assignment(
                campaign_path=campaign,
                assignment_id="primary-v1",
                assignments=self.assignments(),
            )
            path = root / "primary-v1.json"
            write_gold_assignment_once(path, profile)
            with self.assertRaisesRegex(ValueError, "already exists"):
                write_gold_assignment_once(path, profile)
            loaded = load_gold_assignment(path, campaign)

        self.assertEqual(
            primary_annotator_map(loaded, [P2, P3]),
            {P2: "will", P3: "shunhong_deng"},
        )

    def test_v6_evaluation_primary_preserves_v5_scoring_and_parallel_roles(self) -> None:
        root = Path(__file__).resolve().parents[2]
        path = (
            root
            / "benchmark/campaigns/hvs-extraction-v6/manifest/gold_assignments/evaluation-primary-v1.json"
        )
        campaign = (
            root
            / "benchmark/campaigns/hvs-extraction-v6/manifest/campaign_manifest.json"
        )
        profile = load_gold_assignment(path, campaign)
        v5_profile = load_gold_assignment(
            root
            / "benchmark/campaigns/hvs-extraction-v5/manifest/gold_assignments/primary-v1.json",
            root
            / "benchmark/campaigns/hvs-extraction-v5/manifest/campaign_manifest.json",
        )
        by_id = {paper["arxiv_id"]: paper for paper in profile["papers"]}
        self.assertEqual(
            [
                (
                    paper["arxiv_id"],
                    paper["primary_annotator"],
                    paper["additional_annotators"],
                )
                for paper in profile["papers"]
            ],
            [
                (
                    paper["arxiv_id"],
                    paper["primary_annotator"],
                    paper["additional_annotators"],
                )
                for paper in v5_profile["papers"]
            ],
        )
        self.assertEqual(len(profile["papers"]), 50)
        primary = [paper["primary_annotator"] for paper in profile["papers"]]
        self.assertEqual(primary.count("will"), 44)
        self.assertEqual(primary.count("shunhong_deng"), 6)
        additional = [
            (paper["arxiv_id"], annotator)
            for paper in profile["papers"]
            for annotator in paper["additional_annotators"]
        ]
        self.assertEqual(additional, [("2601.19866", "shunhong_deng")])
        self.assertEqual(by_id["2601.19866"]["primary_annotator"], "will")
        self.assertEqual(
            by_id["2601.19866"]["additional_annotators"], ["shunhong_deng"]
        )
        for arxiv_id in (
            "1811.04302",
            "1907.11725",
            "2502.00102",
            "2603.02850",
            "2402.02876",
            "2404.07731",
        ):
            self.assertEqual(by_id[arxiv_id]["primary_annotator"], "shunhong_deng")


if __name__ == "__main__":
    unittest.main()
