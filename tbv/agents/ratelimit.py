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
    """Blocks until a request fits the RPM, TPM (input tokens per minute) and RPD limits."""

    def __init__(
        self,
        rpm: int,
        rpd: int,
        *,
        tpm: int | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        used_today: int = 0,
        day: str | None = None,
    ) -> None:
        self.rpm, self.rpd, self.tpm = rpm, rpd, tpm
        self._clock, self._sleep = clock, sleep
        self._recent: deque[list[float]] = deque()  # [timestamp, tokens]
        self._last: list[float] | None = None
        self._day = day or _pacific_day(clock())
        self.used_today = used_today

    def acquire(self, est_tokens: int = 0) -> None:
        """Wait until allowed; raise DailyQuotaExhausted if today's request quota is gone."""
        now = self._clock()
        today = _pacific_day(now)
        if today != self._day:
            self._day, self.used_today = today, 0
        if self.used_today >= self.rpd:
            raise DailyQuotaExhausted(next_reset(now))
        if self.tpm is not None and est_tokens > self.tpm:
            raise ValueError(f"one request (~{est_tokens} tokens) exceeds the {self.tpm} TPM limit")
        while True:
            now = self._clock()
            while self._recent and now - self._recent[0][0] >= 60:
                self._recent.popleft()
            used = sum(t for _, t in self._recent)
            if len(self._recent) < self.rpm and (self.tpm is None or used + est_tokens <= self.tpm):
                break
            self._sleep(max(0.01, 60 - (now - self._recent[0][0])) if self._recent else 0.01)
        entry = [self._clock(), float(est_tokens)]
        self._recent.append(entry)
        self._last = entry
        self.used_today += 1

    @property
    def day(self) -> str:
        return self._day

    def settle(self, actual_tokens: int) -> None:
        """Replace the estimate for the latest request with the real input-token count."""
        if self._last is not None:
            self._last[1] = float(actual_tokens)
