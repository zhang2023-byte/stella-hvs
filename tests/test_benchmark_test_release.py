from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from stella.benchmark.test_release import (
    build_test_release,
    find_matching_release,
    write_test_release,
)


class TestReleaseTest(unittest.TestCase):
    def fixtures(self, root: Path, *, split: str = "test", audit: str = "clean") -> tuple[Path, Path]:
        root.mkdir(parents=True, exist_ok=True)
        campaign = root / "campaign.json"
        campaign.write_text(json.dumps({"campaign_id": "hvs-extraction-v1", "papers": []}))
        run_dir = root / "run"
        run_dir.mkdir()
        (run_dir / "run_manifest.json").write_text(
            json.dumps(
                {
                    "schema": {"name": "benchmark.run_manifest", "version": 1},
                    "run_id": "run-1",
                    "campaign": {"campaign_id": "hvs-extraction-v1", "sha256": None},
                    "split": split,
                    "leakage_audit": {"status": audit},
                }
            )
        )
        return campaign, run_dir

    def test_rejects_non_test_or_contaminated_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign, dev = self.fixtures(root, split="dev")
            with self.assertRaisesRegex(ValueError, "test split"):
                build_test_release(campaign_path=campaign, run_dir=dev)
            campaign, contaminated = self.fixtures(root / "contaminated", audit="contaminated")
            with self.assertRaisesRegex(ValueError, "leakage"):
                build_test_release(campaign_path=campaign, run_dir=contaminated)

    def test_release_binds_hashes_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign, run_dir = self.fixtures(root)
            manifest = json.loads((run_dir / "run_manifest.json").read_text())
            from stella.benchmark.campaign import sha256_file

            manifest["campaign"]["sha256"] = sha256_file(campaign)
            (run_dir / "run_manifest.json").write_text(json.dumps(manifest))
            release = build_test_release(campaign_path=campaign, run_dir=run_dir)
            self.assertEqual(release["schema"], {"name": "benchmark.test_release", "version": 1})
            releases = root / "releases"
            path = write_test_release(release=release, releases_root=releases)
            self.assertEqual(path, write_test_release(release=release, releases_root=releases))
            self.assertEqual(
                find_matching_release(campaign_path=campaign, run_dir=run_dir, releases_root=releases),
                path,
            )


if __name__ == "__main__":
    unittest.main()
