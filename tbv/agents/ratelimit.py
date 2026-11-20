"""Quota limiter for free-tier APIs: requests per minute and requests per (Pacific) day."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")


class DailyQuotaExhausted(RuntimeError):
    def __init__(self, reset_at: float) -> None:
        super().__init__("daily request quota exhausted")
        self.reset_at = reset_at  # epoch seconds of the next Pacific midnight


def _pacific_day(ts: float) -> str:
    return datetime.fromtimestamp(ts, PACIFIC).date().isoformat()


def next_reset(ts: float) -> float:
    local = datetime.fromtimestamp(ts, PACIFIC)
    nxt = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return nxt.astimezone(UTC).timestamp()


class QuotaLimiter:
    def __init__(
        self,
        rpm: int,
        rpd: int,
        *,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        used_today: int = 0,
        day: str | None = None,
    ) -> None:
        self.rpm, self.rpd = rpm, rpd
        self._clock, self._sleep = clock, sleep
        self._recent: deque[float] = deque()
        self._day = day or _pacific_day(clock())
        self.used_today = used_today

    def acquire(self) -> None:
        """Block until a request is allowed; raise DailyQuotaExhausted if today's quota is gone."""
        now = self._clock()
        today = _pacific_day(now)
        if today != self._day:
            self._day, self.used_today = today, 0
        if self.used_today >= self.rpd:
            raise DailyQuotaExhausted(next_reset(now))
        while True:
            now = self._clock()
            while self._recent and now - self._recent[0] >= 60:
                self._recent.popleft()
            if len(self._recent) < self.rpm:
                break
            self._sleep(max(0.01, 60 - (now - self._recent[0])))
        self._recent.append(self._clock())
        self.used_today += 1
