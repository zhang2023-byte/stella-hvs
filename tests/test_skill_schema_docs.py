from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from high_velocity_lit.schema_specs import SKILL_SCHEMA_SPECS  # noqa: E402


class SkillSchemaDocsTest(unittest.TestCase):
    def test_skill_schema_docs_match_code_schema_specs(self) -> None:
        for spec in SKILL_SCHEMA_SPECS:
            with self.subTest(schema=spec.version):
                path = ROOT / spec.reference_path
                self.assertTrue(path.exists(), f"missing schema reference: {path}")
                text = path.read_text(encoding="utf-8")

                self.assertIn(spec.version, text)
                for field in spec.top_level_fields:
                    self.assertIn(f'"{field}"', text, f"{field} missing from {spec.reference_path}")
                for status_path, statuses in spec.status_values.items():
                    self.assertIn(status_path.split(".")[-1], text)
                    for status in statuses:
                        self.assertIn(f"`{status}`", text, f"{status} missing from {spec.reference_path}")


if __name__ == "__main__":
    unittest.main()
