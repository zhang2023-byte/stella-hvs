from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

from stella.lit.schema_specs import SKILL_SCHEMA_SPECS  # noqa: E402
from stella.lit.schema_docs import generated_schema_docs  # noqa: E402


class SkillSchemaDocsTest(unittest.TestCase):
    def test_skill_schema_docs_are_generated_from_code(self) -> None:
        for relative_path, content in generated_schema_docs().items():
            with self.subTest(path=relative_path):
                self.assertEqual((ROOT / relative_path).read_text(encoding="utf-8"), content)

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
