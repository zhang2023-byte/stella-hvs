from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

fake_deepxiv_sdk = types.ModuleType("deepxiv_sdk")
fake_deepxiv_sdk.Reader = object
sys.modules.setdefault("deepxiv_sdk", fake_deepxiv_sdk)

SCRIPT = ROOT / "scripts" / "fetch_high_velocity_lit.py"
SPEC = importlib.util.spec_from_file_location("fetch_high_velocity_lit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)


class CliOptionParsingTest(unittest.TestCase):
    def test_from_periods_start_at_expected_boundaries(self) -> None:
        today = date(2026, 4, 18)
        self.assertEqual(cli.parse_period("2025", kind="from", today=today), date(2025, 1, 1))
        self.assertEqual(cli.parse_period("2025-02", kind="from", today=today), date(2025, 2, 1))
        self.assertEqual(cli.parse_period("2025-02-14", kind="from", today=today), date(2025, 2, 14))

    def test_to_periods_end_at_expected_boundaries(self) -> None:
        today = date(2026, 4, 18)
        self.assertEqual(cli.parse_period(None, kind="to", today=today), today)
        self.assertEqual(cli.parse_period("none", kind="to", today=today), today)
        self.assertEqual(cli.parse_period("2025", kind="to", today=today), date(2025, 12, 31))
        self.assertEqual(cli.parse_period("2025-02", kind="to", today=today), date(2025, 2, 28))
        self.assertEqual(cli.parse_period("2025-02-14", kind="to", today=today), date(2025, 2, 14))

    def test_future_dates_are_clamped_to_today(self) -> None:
        today = date(2026, 4, 18)
        self.assertEqual(cli.parse_period("2027", kind="from", today=today), today)
        self.assertEqual(cli.parse_period("2026-12", kind="to", today=today), today)

    def test_invalid_periods_raise(self) -> None:
        for value in ("2026/03", "2026-3", "2026-02-31", "none"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    cli.parse_period(value, kind="from", today=date(2026, 4, 18))

    def test_bool_parser(self) -> None:
        self.assertTrue(cli.parse_bool("True"))
        self.assertTrue(cli.parse_bool("yes"))
        self.assertFalse(cli.parse_bool("False"))
        self.assertFalse(cli.parse_bool("0"))
        with self.assertRaises(Exception):
            cli.parse_bool("maybe")

    def test_default_max_results_is_quota_conservative(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args(["--from", "2026-03"])
        self.assertEqual(args.max_results, 20)

    def test_default_categories_focus_on_galactic_astrophysics(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args(["--from", "2026-03"])
        self.assertEqual(args.categories, "astro-ph.GA")

    def test_default_queries_avoid_singular_plural_duplicates(self) -> None:
        self.assertEqual(
            cli.load_queries(None, []),
            [
                "hypervelocity stars",
                "high-velocity stars",
                "runaway stars",
                "unbound stars",
                "escaping stars",
            ],
        )


if __name__ == "__main__":
    unittest.main()
