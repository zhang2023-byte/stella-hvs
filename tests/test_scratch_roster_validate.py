"""Roster deterministic evidence validation and hydration tests (D012, D015)."""

from __future__ import annotations

import hashlib
import unittest

from stella.benchmark.scratch.roster_validate import (
    DUPLICATE_IDENTIFIER_ACROSS_CANDIDATES,
    DUPLICATE_IDENTIFIER_WITHIN_CANDIDATE,
    IDENTIFIER_NOT_VERBATIM,
    SOURCE_LINE_OUT_OF_BOUNDS,
    SOURCE_LINE_RANGE_REVERSED,
    SOURCE_PATH_NOT_ALLOWED,
    SOURCE_RANGE_COMMENT_ONLY,
    hydrate_source_refs,
    validate_roster_submission,
)


ORIGINAL = "line one\nline two HVS-1 here\n% a comment\nline four\n"
CLEANED = "line one\nline two HVS-1 here\n\nline four\n"
FILES = {"main.tex": 4}
ORIGINAL_TEXTS = {"main.tex": ORIGINAL}
CLEANED_TEXTS = {"main.tex": CLEANED}
SHA = {"main.tex": hashlib.sha256(ORIGINAL.encode("utf-8")).hexdigest()}


def ref(path: str, start: int, end: int) -> dict:
    return {"path": path, "start_line": start, "end_line": end}


def candidate(value: str = "HVS-1", refs: list[dict] | None = None) -> dict:
    return {
        "identifiers": [
            {"value": value, "source_refs": refs or [ref("main.tex", 2, 2)]}
        ],
        "qualification": {
            "reason": "The paper concludes the object is unbound.",
            "source_refs": [ref("main.tex", 2, 4)],
        },
    }


def validate(payload: dict):
    return validate_roster_submission(
        payload,
        file_line_counts=FILES,
        original_texts=ORIGINAL_TEXTS,
        cleaned_texts=CLEANED_TEXTS,
    )


class RosterEvidenceValidationTest(unittest.TestCase):
    def test_valid_submission_passes(self) -> None:
        payload = {
            "candidates": [candidate()],
            "reviewed_exclusions": [
                {
                    "subject": "WD1",
                    "reason": "Bound in the paper.",
                    "source_refs": [ref("main.tex", 1, 2)],
                }
            ],
        }
        self.assertEqual(validate(payload), [])

    def test_coordinate_errors(self) -> None:
        cases = {
            SOURCE_PATH_NOT_ALLOWED: candidate(refs=[ref("ghost.tex", 1, 1)]),
            SOURCE_LINE_RANGE_REVERSED: candidate(refs=[ref("main.tex", 3, 2)]),
            SOURCE_LINE_OUT_OF_BOUNDS: candidate(refs=[ref("main.tex", 2, 99)]),
            SOURCE_RANGE_COMMENT_ONLY: candidate(refs=[ref("main.tex", 3, 3)]),
        }
        for code, broken in cases.items():
            with self.subTest(code=code):
                issues = validate({"candidates": [broken], "reviewed_exclusions": []})
                self.assertTrue(
                    any(issue.code == code for issue in issues),
                    [issue.render() for issue in issues],
                )
                self.assertTrue(all(issue.path.startswith("$.candidates[0]") for issue in issues))

    def test_comment_only_allows_mixed_ranges(self) -> None:
        payload = {"candidates": [candidate(refs=[ref("main.tex", 2, 3)])], "reviewed_exclusions": []}
        self.assertEqual(validate(payload), [])

    def test_identifier_must_occur_verbatim(self) -> None:
        broken = candidate(value="HVS-9", refs=[ref("main.tex", 2, 2)])
        issues = validate({"candidates": [broken], "reviewed_exclusions": []})
        self.assertEqual([issue.code for issue in issues], [IDENTIFIER_NOT_VERBATIM])
        self.assertEqual(issues[0].path, "$.candidates[0].identifiers[0]")

    def test_identifier_verbatim_in_any_one_of_several_refs(self) -> None:
        payload = {
            "candidates": [candidate(refs=[ref("main.tex", 1, 1), ref("main.tex", 2, 2)])],
            "reviewed_exclusions": [],
        }
        self.assertEqual(validate(payload), [])

    def test_duplicate_within_candidate(self) -> None:
        broken = candidate()
        broken["identifiers"].append(
            {"value": "HVS-1", "source_refs": [ref("main.tex", 2, 2)]}
        )
        issues = validate({"candidates": [broken], "reviewed_exclusions": []})
        self.assertIn(DUPLICATE_IDENTIFIER_WITHIN_CANDIDATE, [issue.code for issue in issues])

    def test_duplicate_across_candidates(self) -> None:
        payload = {
            "candidates": [candidate(), candidate()],
            "reviewed_exclusions": [],
        }
        issues = validate(payload)
        codes = [issue.code for issue in issues]
        self.assertIn(DUPLICATE_IDENTIFIER_ACROSS_CANDIDATES, codes)
        offender = [issue for issue in issues if issue.code == DUPLICATE_IDENTIFIER_ACROSS_CANDIDATES]
        self.assertEqual(offender[0].path, "$.candidates[1].identifiers[0]")

    def test_hydration_resolves_exact_text_and_hash(self) -> None:
        payload = {"candidates": [candidate()], "reviewed_exclusions": []}
        hydrated = hydrate_source_refs(
            payload, original_texts=ORIGINAL_TEXTS, file_sha256=SHA
        )
        source = hydrated["candidates"][0]["identifiers"][0]["source_refs"][0]
        self.assertEqual(source["resolved_text"], "line two HVS-1 here")
        self.assertEqual(source["source_sha256"], SHA["main.tex"])
        qualification = hydrated["candidates"][0]["qualification"]["source_refs"][0]
        self.assertEqual(
            qualification["resolved_text"],
            "line two HVS-1 here\n% a comment\nline four",
        )
        # Model-submitted fields stay untouched.
        self.assertEqual(hydrated["candidates"][0]["identifiers"][0]["value"], "HVS-1")


if __name__ == "__main__":
    unittest.main()
