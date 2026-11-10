"""Human-like play schedule: active hours, play/break blocks, daily cap."""
from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta

from coc_bot.config import SessionConfig


def _parse_hhmm(text: str) -> time:
    hours, minutes = text.split(":")
    return time(int(hours), int(minutes))


class SessionPolicy:
    def __init__(self, cfg: SessionConfig, rng: random.Random) -> None:
        self._cfg = cfg
        self._rng = rng
        self._start = _parse_hhmm(cfg.active_hours[0])
        self._end = _parse_hhmm(cfg.active_hours[1])
        self._play_started: datetime | None = None
        self._play_until: datetime | None = None
        self._played: dict[date, float] = {}

    def in_active_hours(self, now: datetime) -> bool:
        t = now.time()
        if self._start <= self._end:
            return self._start <= t < self._end
        return t >= self._start or t < self._end

    def _session_day(self, now: datetime) -> date:
        """The date an overnight window opened on, so a night counts as one day."""
        if self._start > self._end and now.time() < self._end:
            return now.date() - timedelta(days=1)
        return now.date()

    def start_play(self, now: datetime) -> None:
        self._play_started = now
        self._play_until = now + timedelta(minutes=self._rng.uniform(*self._cfg.play_minutes))

    def end_play(self, now: datetime) -> None:
        if self._play_started is None:
            return
        day = self._session_day(self._play_started)
        self._played[day] = self._played.get(day, 0.0) + (now - self._play_started).total_seconds()
        self._play_started = None
        self._play_until = None

    def played_seconds(self, now: datetime) -> float:
        day = self._session_day(now)
        total = self._played.get(day, 0.0)
        if self._play_started is not None and self._session_day(self._play_started) == day:
            total += (now - self._play_started).total_seconds()
        return total

    def _daily_cap_reached(self, now: datetime) -> bool:
        return self.played_seconds(now) >= self._cfg.max_hours_per_day * 3600

    def should_rest(self, now: datetime) -> bool:
        if not self._cfg.enabled:
            return False
        if not self.in_active_hours(now) or self._daily_cap_reached(now):
            return True
        return self._play_until is not None and now >= self._play_until

    def rest_seconds(self, now: datetime) -> float:
        if not self.in_active_hours(now) or self._daily_cap_reached(now):
            candidate = datetime.combine(self._session_day(now), self._start)
            while candidate <= now:
                candidate += timedelta(days=1)
            return (candidate - now).total_seconds()
        return self._rng.uniform(*self._cfg.break_minutes) * 60
