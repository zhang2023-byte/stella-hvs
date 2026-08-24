"""Roster submission schema and collecting schema validator tests."""

from __future__ import annotations

import unittest

from stella.lit.extraction.schema_check import collect_schema_errors
from stella.hvs_extraction.submission_schema import (
    build_roster_submission_schema,
)


ALLOWED = ["main.tex", "sections/intro.tex"]


def valid_payload() -> dict:
    return {
        "candidates": [
            {
                "identifiers": [
                    {
                        "value": "HVS-1",
                        "source_refs": [
                            {"path": "main.tex", "start_line": 3, "end_line": 3}
                        ],
                    }
                ],
                "qualification": {
                    "reason": "The paper concludes HVS-1 is unbound.",
                    "source_refs": [
                        {"path": "main.tex", "start_line": 3, "end_line": 4}
                    ],
                },
            }
        ],
        "reviewed_exclusions": [
            {
                "subject": "WD1",
                "reason": "The paper treats WD1 as bound.",
                "source_refs": [
                    {"path": "sections/intro.tex", "start_line": 9, "end_line": 10}
                ],
            }
        ],
        "range_groups": [],
    }


class RosterSubmissionSchemaTest(unittest.TestCase):
    def test_schema_injects_runtime_path_enum_everywhere(self) -> None:
        schema = build_roster_submission_schema(ALLOWED)
        text = str(schema)
        self.assertIn("'enum': ['main.tex', 'sections/intro.tex']", text)

    def test_schema_is_strict_at_every_level(self) -> None:
        schema = build_roster_submission_schema(ALLOWED)

        def walk(node: object) -> None:
            if isinstance(node, dict):
                if node.get("type") == "object":
                    self.assertIs(node.get("additionalProperties"), False, node)
                    self.assertIn("required", node)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(schema)
        self.assertEqual(
            set(schema["required"]), {"candidates", "reviewed_exclusions", "range_groups"}
        )

    def test_valid_payload_passes_and_empty_arrays_allowed(self) -> None:
        schema = build_roster_submission_schema(ALLOWED)
        self.assertEqual(collect_schema_errors(valid_payload(), schema), [])
        self.assertEqual(
            collect_schema_errors(
                {"candidates": [], "reviewed_exclusions": [], "range_groups": []}, schema
            ),
            [],
        )

    def test_every_violation_is_collected_with_json_path(self) -> None:
        schema = build_roster_submission_schema(ALLOWED)
        payload = valid_payload()
        payload["extra"] = True
        del payload["candidates"][0]["qualification"]["reason"]
        payload["candidates"][0]["identifiers"][0]["value"] = ""
        payload["candidates"][0]["identifiers"][0]["source_refs"] = []
        payload["reviewed_exclusions"][0]["source_refs"][0]["path"] = "ghost.tex"
        payload["reviewed_exclusions"][0]["source_refs"][0]["start_line"] = 0
        payload["reviewed_exclusions"][0]["source_refs"][0]["end_line"] = "9"
        payload["unexpected_top"] = 1
        issues = collect_schema_errors(payload, schema)
        rendered = "\n".join(issue.render() for issue in issues)
        self.assertIn("$: unexpected property 'extra'", rendered)
        self.assertIn("$: unexpected property 'unexpected_top'", rendered)
        self.assertIn(
            "$.candidates[0].qualification: missing required property 'reason'",
            rendered,
        )
        self.assertIn("$.candidates[0].identifiers[0].value", rendered)
        self.assertIn("at least 1 item", rendered)
        self.assertIn("outside the allowed enum", rendered)
        self.assertIn("must be >= 1", rendered)
        self.assertIn("must have JSON type integer", rendered)

    def test_missing_top_level_and_wrong_types(self) -> None:
        schema = build_roster_submission_schema(ALLOWED)
        issues = collect_schema_errors({"candidates": "nope"}, schema)
        rendered = "\n".join(issue.render() for issue in issues)
        self.assertIn("missing required property 'reviewed_exclusions'", rendered)
        self.assertIn("$.candidates: must have JSON type array", rendered)


if __name__ == "__main__":
    unittest.main()
