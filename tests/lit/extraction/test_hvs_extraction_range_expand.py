"""Strict deterministic compressed-identifier range tests."""

from __future__ import annotations

import unittest

from stella.lit.extraction.range_expand import expand_range_notation


class RangeExpansionTest(unittest.TestCase):
    def test_shared_prefix_list_and_remainder(self) -> None:
        expansion = expand_range_notation("OBJ1,4-6,09-10 and others")
        self.assertIsNone(expansion.error)
        self.assertEqual(
            expansion.identifiers,
            ["OBJ1", "OBJ4", "OBJ5", "OBJ6", "OBJ09", "OBJ10"],
        )
        self.assertEqual(expansion.remainder, "and others")

    def test_prefixed_range_preserves_zero_padding(self) -> None:
        expansion = expand_range_notation("CAT-X001-003")
        self.assertIsNone(expansion.error)
        self.assertEqual(
            expansion.identifiers,
            ["CAT-X001", "CAT-X002", "CAT-X003"],
        )
        self.assertIsNone(expansion.remainder)

    def test_unpadded_range_does_not_gain_padding(self) -> None:
        expansion = expand_range_notation("OBJ9-10")
        self.assertIsNone(expansion.error)
        self.assertEqual(expansion.identifiers, ["OBJ9", "OBJ10"])

    def test_common_dash_characters_are_accepted(self) -> None:
        for notation in ("OBJ1--3", "OBJ1–3", "OBJ1—3"):
            with self.subTest(notation=notation):
                expansion = expand_range_notation(notation)
                self.assertIsNone(expansion.error)
                self.assertEqual(expansion.identifiers, ["OBJ1", "OBJ2", "OBJ3"])

    def test_prefix_reset_is_rejected(self) -> None:
        expansion = expand_range_notation("OBJ1,OTHER2,3-4")
        self.assertIsNotNone(expansion.error)

    def test_ambiguous_or_unsupported_segments_are_rejected(self) -> None:
        for notation in (
            "4-6",
            "OBJ1,,4",
            "OBJ1A-3A",
            "OBJ1,4-6,4",
            "OBJ10-4",
            "OBJ9-010",
            "and others",
        ):
            with self.subTest(notation=notation):
                self.assertIsNotNone(expand_range_notation(notation).error)

    def test_group_member_cap_fails_closed(self) -> None:
        expansion = expand_range_notation("OBJ1-51", max_members=50)
        self.assertIsNotNone(expansion.error)


if __name__ == "__main__":
    unittest.main()
