from __future__ import annotations

import unittest

from stella.benchmark.method_policy import (
    LEGACY_DIRECT_METHODS,
    LEGACY_TASK_SURFACES,
    PRIMARY_DIRECT_METHOD,
    PRIMARY_TASK_SURFACE,
    require_legacy_opt_in,
)


class BenchmarkMethodPolicyTest(unittest.TestCase):
    def test_primary_and_legacy_surfaces_are_explicit(self) -> None:
        self.assertEqual(PRIMARY_DIRECT_METHOD, "B")
        self.assertEqual(PRIMARY_TASK_SURFACE, "core_prov")
        self.assertEqual(LEGACY_DIRECT_METHODS, ("C",))
        self.assertEqual(LEGACY_TASK_SURFACES, ("full",))

    def test_primary_b_core_needs_no_legacy_opt_in(self) -> None:
        require_legacy_opt_in(method="B", task_surface="core_prov")

    def test_method_c_and_full_fail_closed_without_explicit_opt_in(self) -> None:
        with self.assertRaisesRegex(ValueError, "Method C is legacy"):
            require_legacy_opt_in(method="C", task_surface="core_prov")
        with self.assertRaisesRegex(ValueError, "FULL is legacy"):
            require_legacy_opt_in(method="B", task_surface="full")

    def test_explicit_legacy_interfaces_remain_available(self) -> None:
        require_legacy_opt_in(
            method="C",
            task_surface="full",
            allow_legacy_method_c=True,
            allow_legacy_full=True,
        )


if __name__ == "__main__":
    unittest.main()
