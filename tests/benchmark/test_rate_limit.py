"""Cross-process benchmark request-rate limiting without real network calls."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stella.benchmark.rate_limit import RateLimitedTransport, RollingWindowRateLimiter
from stella.lit.llm_batch import LLMTransportError


class RollingWindowRateLimiterTest(unittest.TestCase):
    def test_instances_share_one_exact_rolling_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            now = [100.0]
            sleeps: list[float] = []

            def clock() -> float:
                return now[0]

            def sleep(seconds: float) -> None:
                sleeps.append(seconds)
                now[0] += seconds

            path = Path(tmp) / "rate-limit.sqlite"
            first = RollingWindowRateLimiter(
                path,
                max_requests=2,
                window_seconds=60,
                clock=clock,
                sleep=sleep,
            )
            second = RollingWindowRateLimiter(
                path,
                max_requests=2,
                window_seconds=60,
                clock=clock,
                sleep=sleep,
            )

            first.acquire()
            second.acquire()
            first.acquire()

            self.assertEqual(sleeps, [60.0])
            self.assertEqual(first.recent_request_count(), 1)

    def test_429_lowers_shared_ceiling_and_clean_windows_recover(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            now = [100.0]
            path = Path(tmp) / "rate-limit.sqlite"

            def clock() -> float:
                return now[0]

            first = RollingWindowRateLimiter(
                path,
                max_requests=4,
                window_seconds=60,
                backoff_limits=(4, 3, 2),
                clock=clock,
                sleep=lambda seconds: now.__setitem__(0, now[0] + seconds),
            )
            second = RollingWindowRateLimiter(
                path,
                max_requests=4,
                window_seconds=60,
                backoff_limits=(4, 3, 2),
                clock=clock,
                sleep=lambda seconds: now.__setitem__(0, now[0] + seconds),
            )

            first.record_rate_limit()
            self.assertEqual(second.current_limit(), 3)
            second.record_rate_limit()
            self.assertEqual(first.current_limit(), 2)

            now[0] += 60
            first.acquire()
            self.assertEqual(second.current_limit(), 3)

    def test_transport_reports_429_to_limiter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            limiter = RollingWindowRateLimiter(
                Path(tmp) / "rate-limit.sqlite",
                max_requests=4,
                window_seconds=60,
                backoff_limits=(4, 3, 2),
            )

            def fail(**_kwargs):
                raise LLMTransportError(
                    "busy",
                    category="rate_limit",
                    http_status=429,
                    automatic_retryable=True,
                )

            with self.assertRaises(LLMTransportError):
                RateLimitedTransport(fail, limiter)(model="fake")
            self.assertEqual(limiter.current_limit(), 3)


if __name__ == "__main__":
    unittest.main()
