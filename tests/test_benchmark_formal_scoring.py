from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from stella.benchmark.campaign import sha256_file
from stella.benchmark.run_contract import canonical_sha256
from stella.benchmark.scoring import _formal_run_bindings
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


class FormalScoringContractTest(unittest.TestCase):
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
