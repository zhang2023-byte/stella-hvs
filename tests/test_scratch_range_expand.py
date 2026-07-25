"""Deterministic range expansion tests (D059)."""

from __future__ import annotations

import unittest

from stella.benchmark.scratch.range_expand import expand_range_notation


class RangeExpansionTest(unittest.TestCase):
    def test_hvs_survey_notation(self) -> None:
        expansion = expand_range_notation("HVS1,4-10,12-24 and others")
        self.assertIsNone(expansion.error)
        self.assertEqual(
            expansion.identifiers,
            ["HVS1"]
            + [f"HVS{n}" for n in range(4, 11)]
            + [f"HVS{n}" for n in range(12, 25)],
        )
        self.assertEqual(expansion.remainder, "and others")

    def test_prefixed_range(self) -> None:
        expansion = expand_range_notation("LAMOST-HVS1-3")
        self.assertIsNone(expansion.error)
        self.assertEqual(
            expansion.identifiers, ["LAMOST-HVS1", "LAMOST-HVS2", "LAMOST-HVS3"]
        )
        self.assertIsNone(expansion.remainder)

    def test_single_full_form(self) -> None:
        expansion = expand_range_notation("US708")
        self.assertEqual(expansion.identifiers, ["US708"])

    def test_multiple_full_forms_reset_prefix(self) -> None:
        expansion = expand_range_notation("HVS1,GD492,1-2")
        self.assertEqual(expansion.identifiers, ["HVS1", "GD492", "GD1", "GD2"])

    def test_descending_range_rejected(self) -> None:
        self.assertIsNotNone(expand_range_notation("HVS10-4").error)

    def test_oversized_span_rejected(self) -> None:
        self.assertIsNotNone(expand_range_notation("HVS1-99").error)

    def test_bare_number_without_prefix_rejected(self) -> None:
        self.assertIsNotNone(expand_range_notation("4-10").error)

    def test_unparseable_segment_rejected(self) -> None:
        self.assertIsNotNone(expand_range_notation("HVS+").error)

    def test_empty_segment_rejected(self) -> None:
        self.assertIsNotNone(expand_range_notation("HVS1,,HVS2").error)

    def test_no_identifiers_rejected(self) -> None:
        self.assertIsNotNone(expand_range_notation("and others").error)


if __name__ == "__main__":
    unittest.main()
