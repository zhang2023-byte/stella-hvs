"""Cross-process rolling-window request limiter for benchmark providers."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Callable


class RollingWindowRateLimiter:
    """Share one exact request-start window across paper worker processes."""

    def __init__(
        self,
        path: Path,
        *,
        max_requests: int,
        window_seconds: int,
        backoff_limits: tuple[int, ...] | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_requests < 1 or window_seconds < 1:
            raise ValueError("rate limit and window must both be positive")
        self.path = Path(path)
        self.max_requests = int(max_requests)
        self.backoff_limits = tuple(backoff_limits or (self.max_requests,))
        if (
            not self.backoff_limits
            or self.backoff_limits[0] != self.max_requests
            or any(limit < 1 for limit in self.backoff_limits)
            or any(
                later >= earlier
                for earlier, later in zip(
                    self.backoff_limits, self.backoff_limits[1:]
                )
            )
        ):
            raise ValueError(
                "backoff limits must start at max_requests and strictly decrease"
            )
        self.window_seconds = int(window_seconds)
        self.clock = clock
        self.sleep = sleep
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS request_starts "
                "(started_at REAL NOT NULL)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS request_starts_at "
                "ON request_starts(started_at)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS limiter_state ("
                "id INTEGER PRIMARY KEY CHECK (id = 1), "
                "level INTEGER NOT NULL, "
                "last_429 REAL, "
                "last_recovery REAL)"
            )
            connection.execute(
                "INSERT OR IGNORE INTO limiter_state"
                "(id, level, last_429, last_recovery) VALUES (1, 0, NULL, NULL)"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def acquire(self) -> None:
        while True:
            now = float(self.clock())
            cutoff = now - self.window_seconds
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                state = connection.execute(
                    "SELECT level, last_429, last_recovery "
                    "FROM limiter_state WHERE id = 1"
                ).fetchone()
                level = min(int(state[0]), len(self.backoff_limits) - 1)
                last_429 = state[1]
                last_recovery = state[2]
                recovery_anchor = (
                    float(last_recovery)
                    if last_recovery is not None
                    else float(last_429)
                    if last_429 is not None
                    else now
                )
                if (
                    level > 0
                    and last_429 is not None
                    and now - float(last_429) >= self.window_seconds
                    and now - recovery_anchor >= self.window_seconds
                ):
                    recovered_steps = min(
                        level,
                        int((now - recovery_anchor) // self.window_seconds),
                    )
                    level -= recovered_steps
                    connection.execute(
                        "UPDATE limiter_state SET level = ?, last_recovery = ? "
                        "WHERE id = 1",
                        (level, now),
                    )
                effective_limit = self.backoff_limits[level]
                connection.execute(
                    "DELETE FROM request_starts WHERE started_at <= ?", (cutoff,)
                )
                row = connection.execute(
                    "SELECT COUNT(*), MIN(started_at) FROM request_starts"
                ).fetchone()
                count = int(row[0] if row else 0)
                oldest = row[1] if row else None
                if count < effective_limit:
                    connection.execute(
                        "INSERT INTO request_starts(started_at) VALUES (?)", (now,)
                    )
                    return
            wait = max(
                0.001,
                float(oldest) + self.window_seconds - now
                if oldest is not None
                else 0.001,
            )
            self.sleep(wait)

    def record_rate_limit(self) -> None:
        """Lower the shared ceiling one step after a provider 429."""

        now = float(self.clock())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT level FROM limiter_state WHERE id = 1"
            ).fetchone()
            level = min(
                int(row[0] if row else 0) + 1,
                len(self.backoff_limits) - 1,
            )
            connection.execute(
                "UPDATE limiter_state SET level = ?, last_429 = ?, "
                "last_recovery = ? WHERE id = 1",
                (level, now, now),
            )

    def current_limit(self) -> int:
        """Return the process-shared ceiling without advancing recovery."""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT level FROM limiter_state WHERE id = 1"
            ).fetchone()
        level = min(int(row[0] if row else 0), len(self.backoff_limits) - 1)
        return self.backoff_limits[level]

    def recent_request_count(self) -> int:
        now = float(self.clock())
        cutoff = now - self.window_seconds
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM request_starts WHERE started_at > ?", (cutoff,)
            ).fetchone()
        return int(row[0] if row else 0)


class RateLimitedTransport:
    """Acquire one global permit for every physical provider request."""

    def __init__(self, inner, limiter: RollingWindowRateLimiter) -> None:
        self.inner = inner
        self.limiter = limiter

    def __call__(self, **kwargs):
        self.limiter.acquire()
        try:
            return self.inner(**kwargs)
        except Exception as error:
            if (
                getattr(error, "http_status", None) == 429
                or getattr(error, "category", "") == "rate_limit"
            ):
                self.limiter.record_rate_limit()
            raise
