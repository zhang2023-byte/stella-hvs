"""Deterministic contribution-roster validation tests."""

from __future__ import annotations

import unittest
from pathlib import Path

from tests.hvs_contribution_fixtures import (
    BOTH_TYPES_SUBMISSION,
    EMPTY_SUBMISSION,
    EXTERNAL_KNOWLEDGE_SUBMISSION,
    FULL_SUBMISSION,
    LINE_BOUND,
    LINE_RANGE,
    LINE_SEARCH,
    RANGE_GROUP,
    manuscript_text,
)
from stella.lit.extraction.cleaning import strip_tex_comments
from stella.lit.extraction.roster_validate import (
    BOUNDNESS_EVIDENCE_REQUIRED,
    CONTRIBUTION_EVIDENCE_REQUIRED,
    CONTRIBUTION_SUMMARY_REQUIRED,
    CONTRIBUTION_TYPE_STATUS_INCOMPATIBLE,
    DUPLICATE_IDENTIFIER_ACROSS_CONTRIBUTIONS,
    DUPLICATE_IDENTIFIER_WITHIN_CONTRIBUTION,
    IDENTIFIER_NOT_VERBATIM,
    RANGE_EXPANSION_COLLISION,
    RANGE_NOTATION_NOT_VERBATIM,
    RANGE_NOTATION_UNPARSEABLE,
    REVIEWED_EXCLUSION_EVIDENCE_REQUIRED,
    SOURCE_LINE_OUT_OF_BOUNDS,
    SOURCE_LINE_RANGE_REVERSED,
    SOURCE_PATH_NOT_ALLOWED,
    SOURCE_RANGE_COMMENT_ONLY,
    hydrate_contribution_source_refs,
    validate_contribution_roster_submission,
)

ROOT = Path(__file__).resolve().parents[3]


def context(tex: str | None = None):
    text = tex if tex is not None else manuscript_text()
    return {
        "file_line_counts": {"main.tex": text.count("\n")},
        "original_texts": {"main.tex": text},
        "cleaned_texts": {"main.tex": strip_tex_comments(text)},
    }


def sha_map() -> dict:
    return {"main.tex": "0" * 64}


def codes(issues) -> set[str]:
    return {issue.code for issue in issues}


class ContributionRosterValidateTest(unittest.TestCase):
    def test_full_submission_passes(self) -> None:
        issues = validate_contribution_roster_submission(FULL_SUBMISSION, **context())
        self.assertEqual(issues, [])

    def test_empty_submission_passes(self) -> None:
        issues = validate_contribution_roster_submission(EMPTY_SUBMISSION, **context())
        self.assertEqual(issues, [])

    def test_identifier_not_verbatim_rejects_external_knowledge(self) -> None:
        issues = validate_contribution_roster_submission(
            EXTERNAL_KNOWLEDGE_SUBMISSION, **context()
        )
        self.assertIn(IDENTIFIER_NOT_VERBATIM, codes(issues))

    def test_duplicate_identifiers_rejected(self) -> None:
        payload = {
            "object_contributions": [
                dict(BOTH_TYPES_SUBMISSION["object_contributions"][0]),
                dict(BOTH_TYPES_SUBMISSION["object_contributions"][0]),
            ],
            "reviewed_exclusions": [],
            "range_groups": [],
        }
        issues = validate_contribution_roster_submission(payload, **context())
        self.assertIn(DUPLICATE_IDENTIFIER_ACROSS_CONTRIBUTIONS, codes(issues))
        duplicate_within = dict(BOTH_TYPES_SUBMISSION["object_contributions"][0])
        duplicate_within["identifiers"] = duplicate_within["identifiers"] * 2
        issues = validate_contribution_roster_submission(
            {
                "object_contributions": [duplicate_within],
                "reviewed_exclusions": [],
                "range_groups": [],
            },
            **context(),
        )
        self.assertIn(DUPLICATE_IDENTIFIER_WITHIN_CONTRIBUTION, codes(issues))

    def test_candidates_found_status_compatibility(self) -> None:
        for status in ("bound", "not_assessed"):
            with self.subTest(status=status):
                payload = {
                    "object_contributions": [
                        {
                            "identifiers": [
                                {
                                    "value": "J1234",
                                    "source_refs": [
                                        {"path": "main.tex", "start_line": LINE_SEARCH, "end_line": LINE_SEARCH}
                                    ],
                                }
                            ],
                            "contribution_type": "candidates_found",
                            "contribution_summary": "summary",
                            "contribution_evidence": [
                                {"path": "main.tex", "start_line": LINE_SEARCH, "end_line": LINE_SEARCH}
                            ],
                            "paper_boundness": {
                                "status": status,
                                "evidence": [
                                    {"path": "main.tex", "start_line": LINE_SEARCH, "end_line": LINE_SEARCH}
                                ],
                            },
                        }
                    ],
                    "reviewed_exclusions": [],
                    "range_groups": [],
                }
                issues = validate_contribution_roster_submission(payload, **context())
                self.assertIn(CONTRIBUTION_TYPE_STATUS_INCOMPATIBLE, codes(issues))

    def test_follow_up_accepts_all_five_statuses(self) -> None:
        for status in (
            "unbound",
            "possibly_unbound",
            "bound",
            "no_overall_conclusion",
            "not_assessed",
        ):
            with self.subTest(status=status):
                payload = {
                    "object_contributions": [
                        {
                            "identifiers": [
                                {
                                    "value": "HVS-9",
                                    "source_refs": [
                                        {"path": "main.tex", "start_line": LINE_BOUND, "end_line": LINE_BOUND}
                                    ],
                                }
                            ],
                            "contribution_type": "follow_up",
                            "contribution_summary": "summary",
                            "contribution_evidence": [
                                {"path": "main.tex", "start_line": LINE_BOUND, "end_line": LINE_BOUND}
                            ],
                            "paper_boundness": {
                                "status": status,
                                "evidence": [
                                    {"path": "main.tex", "start_line": LINE_BOUND, "end_line": LINE_BOUND}
                                ]
                                if status != "not_assessed"
                                else [],
                            },
                        }
                    ],
                    "reviewed_exclusions": [],
                    "range_groups": [],
                }
                issues = validate_contribution_roster_submission(payload, **context())
                self.assertEqual(issues, [])

    def test_assessed_boundness_requires_evidence(self) -> None:
        payload = {
            "object_contributions": [
                {
                    "identifiers": [
                        {
                            "value": "HVS-9",
                            "source_refs": [
                                {"path": "main.tex", "start_line": LINE_BOUND, "end_line": LINE_BOUND}
                            ],
                        }
                    ],
                    "contribution_type": "follow_up",
                    "contribution_summary": "summary",
                    "contribution_evidence": [
                        {"path": "main.tex", "start_line": LINE_BOUND, "end_line": LINE_BOUND}
                    ],
                    "paper_boundness": {"status": "bound", "evidence": []},
                }
            ],
            "reviewed_exclusions": [],
            "range_groups": [],
        }
        issues = validate_contribution_roster_submission(payload, **context())
        self.assertIn(BOUNDNESS_EVIDENCE_REQUIRED, codes(issues))

    def test_required_summary_and_contribution_evidence(self) -> None:
        base = BOTH_TYPES_SUBMISSION["object_contributions"][0]
        no_summary = dict(base, contribution_summary="  ")
        issues = validate_contribution_roster_submission(
            {"object_contributions": [no_summary], "reviewed_exclusions": [], "range_groups": []},
            **context(),
        )
        self.assertIn(CONTRIBUTION_SUMMARY_REQUIRED, codes(issues))
        no_evidence = dict(base, contribution_evidence=[])
        issues = validate_contribution_roster_submission(
            {"object_contributions": [no_evidence], "reviewed_exclusions": [], "range_groups": []},
            **context(),
        )
        self.assertIn(CONTRIBUTION_EVIDENCE_REQUIRED, codes(issues))

    def test_reviewed_exclusion_requires_evidence(self) -> None:
        exclusion = dict(BOTH_TYPES_SUBMISSION["reviewed_exclusions"][0])
        exclusion["source_refs"] = []
        issues = validate_contribution_roster_submission(
            {
                "object_contributions": [],
                "reviewed_exclusions": [exclusion],
                "range_groups": [],
            },
            **context(),
        )
        self.assertIn(REVIEWED_EXCLUSION_EVIDENCE_REQUIRED, codes(issues))

    def test_source_coordinate_checks(self) -> None:
        payload = {
            "object_contributions": [
                {
                    "identifiers": [
                        {
                            "value": "J1234",
                            "source_refs": [
                                {"path": "other.tex", "start_line": 1, "end_line": 1}
                            ],
                        }
                    ],
                    "contribution_type": "candidates_found",
                    "contribution_summary": "summary",
                    "contribution_evidence": [
                        {"path": "main.tex", "start_line": 99, "end_line": 99}
                    ],
                    "paper_boundness": {
                        "status": "unbound",
                        "evidence": [
                            {"path": "main.tex", "start_line": 5, "end_line": 3}
                        ],
                    },
                }
            ],
            "reviewed_exclusions": [],
            "range_groups": [],
        }
        issues = validate_contribution_roster_submission(payload, **context())
        found = codes(issues)
        self.assertIn(SOURCE_PATH_NOT_ALLOWED, found)
        self.assertIn(SOURCE_LINE_OUT_OF_BOUNDS, found)
        self.assertIn(SOURCE_LINE_RANGE_REVERSED, found)

    def test_comment_only_range_rejected(self) -> None:
        tex = (
            "\\documentclass{article}\n"
            "\\begin{document}\n"
            "% J1234 retained as unbound candidate by our search\n"
            "text\n"
            "\\end{document}\n"
        )
        payload = {
            "object_contributions": [
                {
                    "identifiers": [
                        {
                            "value": "J1234",
                            "source_refs": [
                                {"path": "main.tex", "start_line": 4, "end_line": 4}
                            ],
                        }
                    ],
                    "contribution_type": "candidates_found",
                    "contribution_summary": "summary",
                    "contribution_evidence": [
                        {"path": "main.tex", "start_line": 3, "end_line": 3}
                    ],
                    "paper_boundness": {
                        "status": "unbound",
                        "evidence": [
                            {"path": "main.tex", "start_line": 3, "end_line": 3}
                        ],
                    },
                }
            ],
            "reviewed_exclusions": [],
            "range_groups": [],
        }
        issues = validate_contribution_roster_submission(payload, **context(tex))
        self.assertIn(SOURCE_RANGE_COMMENT_ONLY, codes(issues))

    def test_range_notation_checks(self) -> None:
        not_verbatim = dict(RANGE_GROUP, range_notation="J20-23")
        issues = validate_contribution_roster_submission(
            {"object_contributions": [], "reviewed_exclusions": [], "range_groups": [not_verbatim]},
            **context(),
        )
        self.assertIn(RANGE_NOTATION_NOT_VERBATIM, codes(issues))

        unparseable = dict(RANGE_GROUP, range_notation="J10..,")
        issues = validate_contribution_roster_submission(
            {"object_contributions": [], "reviewed_exclusions": [], "range_groups": [unparseable]},
            **context(manuscript_text().replace("J10-13", "J10..,")),
        )
        self.assertIn(RANGE_NOTATION_UNPARSEABLE, codes(issues))

        collision = dict(RANGE_GROUP)
        direct = {
            "identifiers": [
                {
                    "value": "J11",
                    "source_refs": [
                        {"path": "main.tex", "start_line": LINE_RANGE, "end_line": LINE_RANGE}
                    ],
                }
            ],
            "contribution_type": "candidates_found",
            "contribution_summary": "summary",
            "contribution_evidence": [
                {"path": "main.tex", "start_line": LINE_RANGE, "end_line": LINE_RANGE}
            ],
            "paper_boundness": {
                "status": "unbound",
                "evidence": [
                    {"path": "main.tex", "start_line": LINE_RANGE, "end_line": LINE_RANGE}
                ],
            },
        }
        issues = validate_contribution_roster_submission(
            {"object_contributions": [direct], "reviewed_exclusions": [], "range_groups": [collision]},
            **context(),
        )
        self.assertIn(RANGE_EXPANSION_COLLISION, codes(issues))

    def test_hydration_adds_resolved_text_and_hash(self) -> None:
        hydrated = hydrate_contribution_source_refs(
            BOTH_TYPES_SUBMISSION,
            original_texts=context()["original_texts"],
            file_sha256=sha_map(),
        )
        first = hydrated["object_contributions"][0]
        ref = first["contribution_evidence"][0]
        self.assertEqual(ref["resolved_text"], manuscript_text().split("\n")[LINE_SEARCH - 1])
        self.assertEqual(ref["source_sha256"], "0" * 64)
        identifier_ref = first["identifiers"][0]["source_refs"][0]
        self.assertIn("resolved_text", identifier_ref)
        boundness_ref = first["paper_boundness"]["evidence"][0]
        self.assertIn("resolved_text", boundness_ref)
        self.assertEqual(
            hydrated["reviewed_exclusions"][0]["source_refs"][0]["source_sha256"],
            "0" * 64,
        )


if __name__ == "__main__":
    unittest.main()
