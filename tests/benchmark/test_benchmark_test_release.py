from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from stella.benchmark.test_release import build_test_release
from stella.schema_registry import ACTIVE_BENCHMARK_CAMPAIGN, schema_ref


class TestReleaseTest(unittest.TestCase):
    def test_current_campaign_is_explicitly_not_test_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign = root / "campaign.json"
            campaign.write_text(
                json.dumps(
                    {
                        "schema": schema_ref("benchmark.campaign"),
                        "campaign_id": ACTIVE_BENCHMARK_CAMPAIGN,
                        "test_ready": False,
                        "papers": [],
                    }
                ),
                encoding="utf-8",
            )
            run_dir = root / "run"
            run_dir.mkdir()
            with self.assertRaisesRegex(ValueError, "not test-ready"):
                build_test_release(campaign_path=campaign, run_dir=run_dir)

    def test_legacy_campaign_manifest_is_not_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            campaign = root / "campaign.json"
            campaign.write_text(
                json.dumps(
                    {
                        "campaign_id": ACTIVE_BENCHMARK_CAMPAIGN,
                        "test_ready": True,
                    }
                ),
                encoding="utf-8",
            )
            run_dir = root / "run"
            run_dir.mkdir()
            with self.assertRaisesRegex(ValueError, "campaign manifest"):
                build_test_release(campaign_path=campaign, run_dir=run_dir)


if __name__ == "__main__":
    unittest.main()
