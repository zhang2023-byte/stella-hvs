"""Fail-closed behavior tests for the dynamics operation adapters."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from stella.dyn.dynamics import calculate
from stella.dyn.input_selection import validate_selection


class ValidateSelectionAdapterTest(unittest.TestCase):
    def test_missing_snapshot_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = validate_selection({}, root=Path(tmp))
            self.assertEqual(result["status"], "failed")
            self.assertIn(
                "automatic selection is never used",
                result["failure"]["detail"],
            )

    def test_invalid_snapshot_payload_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "literature" / "hvs_dynamics_input_selection.json"
            path.parent.mkdir(parents=True)
            path.write_text("{not json", encoding="utf-8")
            result = validate_selection({}, root=root)
            self.assertEqual(result["status"], "failed")

    def test_snapshot_without_selections_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "literature" / "hvs_dynamics_input_selection.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"selections": []}), encoding="utf-8")
            result = validate_selection({}, root=root)
            self.assertEqual(result["status"], "failed")


class CalculateAdapterTest(unittest.TestCase):
    def test_calculate_requires_selection_and_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = calculate({}, root=root)
            self.assertEqual(result["status"], "failed")
            self.assertIn("input-selection", result["failure"]["detail"])

    def test_calculate_requires_timelines(self) -> None:
        # Even a valid selection path cannot bypass the catalog requirement.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            literature = root / "literature"
            (literature / "hvs_contribution_catalog").mkdir(parents=True)
            # No index.json: timelines are incomplete.
            result = calculate({}, root=root)
            self.assertEqual(result["status"], "failed")
            self.assertIn("selection", result["failure"]["detail"])


if __name__ == "__main__":
    unittest.main()
