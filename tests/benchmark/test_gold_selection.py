"""The public gold selection consumes JSON annotations only.

Selection preparation and validation require no YAML twin: the manifest
carries paper ids, experts, and hashes, and never a gold value.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stella.benchmark.gold_selection import (
    contribution_selection_path,
    prepare_selection,
    validate_selection,
)
from tests.benchmark.test_hvs_contribution_gold import fictional_annotation_payload
from stella.benchmark.hvs_contribution_gold_form import save_expert_annotation

EXPERT = "expert-a"
PAPER = "2601.00001"
PAPER_B = "2601.00002"


def _seed_gold(gold_dir: Path) -> None:
    save_expert_annotation(
        fictional_annotation_payload(), gold_dir, expert_approved=True
    )


def _seed_second_gold(gold_dir: Path) -> None:
    payload = fictional_annotation_payload()
    payload["arxiv_id"] = PAPER_B
    save_expert_annotation(payload, gold_dir, expert_approved=True)


class GoldSelectionJsonOnlyTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.gold_dir = self.root / "private-gold"
        self.gold_dir.mkdir()
        _seed_gold(self.gold_dir)
        self._old = os.environ.get("STELLA_GOLD_DIR")
        os.environ["STELLA_GOLD_DIR"] = str(self.gold_dir)

    def tearDown(self) -> None:
        if self._old is None:
            os.environ.pop("STELLA_GOLD_DIR", None)
        else:
            os.environ["STELLA_GOLD_DIR"] = self._old
        self._tmp.cleanup()

    def test_selection_consumes_json_without_requiring_a_twin(self) -> None:
        result = prepare_selection(
            {"expert": EXPERT, "papers": [PAPER]}, root=self.root
        )
        self.assertEqual(result["status"], "complete")
        selection_path = contribution_selection_path(self.root, {})
        self.assertTrue(selection_path.is_file())
        selection = json.loads(selection_path.read_text(encoding="utf-8"))
        entry = selection["papers"][0]
        self.assertEqual(entry["arxiv_id"], PAPER)
        self.assertEqual(entry["selected_expert"], EXPERT)
        self.assertTrue(entry["sha256"])
        # No gold values leak into the public artifact.
        rendered = json.dumps(selection)
        for forbidden in ("object_contributions", "quantities", "values"):
            self.assertNotIn(forbidden, rendered)
        # No YAML twin was ever required or produced.
        self.assertEqual(
            [], list((self.gold_dir / PAPER).glob("*.yaml"))
        )

    def test_selection_expands_the_configured_gold_directory(self) -> None:
        with patch.dict(
            os.environ,
            {
                "HOME": str(self.root),
                "STELLA_GOLD_DIR": "~/private-gold",
            },
        ):
            result = prepare_selection(
                {"expert": EXPERT, "papers": [PAPER]}, root=self.root
            )

        self.assertEqual(result["status"], "complete", result)

    def test_validator_accepts_the_json_only_selection(self) -> None:
        result = prepare_selection(
            {"expert": EXPERT, "papers": [PAPER]}, root=self.root
        )
        errors = validate_selection({}, result, root=self.root)
        self.assertEqual([], errors)

    def test_every_paper_gets_its_own_hash_and_selection_is_write_once(self) -> None:
        _seed_second_gold(self.gold_dir)
        first = prepare_selection(
            {"expert": EXPERT, "papers": [PAPER, PAPER_B]}, root=self.root
        )
        self.assertEqual(first["status"], "complete", first)
        entries = (first.get("detail") or {})["selection"]["papers"]
        self.assertEqual([bool(entry.get("sha256")) for entry in entries], [True, True])
        self.assertNotEqual(entries[0]["sha256"], entries[1]["sha256"])
        second = prepare_selection(
            {"expert": EXPERT, "papers": [PAPER, PAPER_B]}, root=self.root
        )
        self.assertEqual(second["status"], "failed")

    def test_validator_rejects_a_selection_with_gold_values(self) -> None:
        selection_path = contribution_selection_path(self.root, {})
        selection_path.parent.mkdir(parents=True)
        selection_path.write_text(
            json.dumps(
                {
                    "papers": [
                        {
                            "arxiv_id": PAPER,
                            "selected_expert": EXPERT,
                            "sha256": "0" * 64,
                            "quantities": [{"value": 1.0}],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        result = {"status": "complete"}
        errors = validate_selection({}, result, root=self.root)
        self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
