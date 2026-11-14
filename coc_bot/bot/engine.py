"""Screen-driven loop shared by every task: stuck detection, escalating recovery, ADB reconnects."""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from coc_bot.bot.task import Task
from coc_bot.config import Settings
from coc_bot.device.adb import AdbError
from coc_bot.vision.screens import Screen

log = logging.getLogger(__name__)

MAX_SAME_ACTION_TICKS = 5
MAX_FAILED_ACTIONS = 5
MAX_ADB_RECONNECTS = 3


class FatalError(RuntimeError):
    """The bot cannot continue safely."""


@dataclass
class Stats:
    attacks: int = 0
    skipped: int = 0
    recoveries: int = 0
    restarts: int = 0
    carts: int = 0     # Builder Base: Elixir Cart collections
    stage2: int = 0    # Builder Base: battles that reached stage 2

    def per_hour(self, hours: float) -> str:
        if hours <= 0:
            return "n/a"
        return f"{self.attacks / hours:.0f} attacks/h"


class ScreenLoop:
    def __init__(
        self,
        game,
        task: Task,
        policy,
        settings: Settings,
        rng: random.Random,
        clock: Callable[[], datetime],
        sleep: Callable[[float], None],
    ) -> None:
        self.game = game
        self.task = task
        self.policy = policy
        self.settings = settings
        self.rng = rng
        self.clock = clock
        self.sleep = sleep
        self.stats = Stats()
        self.check_storage = True   # the dashboard can switch the storage-full check off while running
        self._stop = False
        self._started_at: datetime | None = None
        self._last_screen: Screen | None = None
        self._same_ticks = 0
        self._wait_since: datetime | None = None
        self._recover_level = 0
        self._consecutive_restarts = 0
        self._failed_actions = 0
        self._last_progress: datetime | None = None
        task.bind(self)

    # --- control ----------------------------------------------------------
    def stop(self) -> None:
        self._stop = True

    @property
    def current_screen(self) -> Screen | None:
        return self._last_screen

    def reset_timers(self) -> None:
        """After a pause: don't count the paused time as being stuck."""
        self.mark_progress()
        self._after_recovery()
        self.task.on_resume(self.clock())

    def run(self, max_ticks: int | None = None) -> None:
        self.policy.start_play(self.clock())
        self._last_progress = self.clock()
        self._started_at = self.clock()
        self.task.on_start(self.clock())
        adb_failures = 0
        ticks = 0
        try:
            while not self._stop and (max_ticks is None or ticks < max_ticks):
                ticks += 1
                try:
                    self.tick()
                except AdbError as exc:
                    adb_failures += 1
                    log.warning("ADB error (%d/%d): %s", adb_failures, MAX_ADB_RECONNECTS, exc)
                    if adb_failures > MAX_ADB_RECONNECTS:
                        raise FatalError(
                            f"ADB unavailable after {MAX_ADB_RECONNECTS} reconnects"
                        ) from exc
                    self.sleep(5.0)
                    try:
                        self.game.reconnect()
                    except AdbError as reconnect_exc:
                        log.warning("Reconnect failed: %s", reconnect_exc)
                else:
                    adb_failures = 0
        finally:
            self.policy.end_play(self.clock())
            log.info("Bot stopped. %s | %s", self.stats, self.rate_summary())

    def tick(self) -> None:
        now = self.clock()
        screen = self.game.screen()
        if self._check_stuck(screen, now):
            return
        if self._last_progress is None:
            self._last_progress = now
        if (now - self._last_progress).total_seconds() > self.settings.timing.progress_timeout_s:
            log.warning("No forward progress for %ds on %s",
                        self.settings.timing.progress_timeout_s, screen.name)
            self._recover(screen)
            self._last_progress = now
            return
        self.task.handlers.get(screen, self._on_unhandled)(now)
        if self._failed_actions >= MAX_FAILED_ACTIONS:
            log.warning("%d game actions in a row did nothing on %s",
                        self._failed_actions, screen.name)
            self._failed_actions = 0
            self._recover(screen)

    def _on_unhandled(self, now: datetime) -> None:
        self.sleep(2.0)

    # --- helpers for tasks ------------------------------------------------
    def act(self, ok) -> bool:
        """Track whether a game action actually did something."""
        if ok:
            self._failed_actions = 0
        else:
            self._failed_actions += 1
        return bool(ok)

    def mark_progress(self, now: datetime | None = None) -> None:
        """The bot got somewhere, so recovery starts from Back again."""
        self._recover_level = 0
        self._consecutive_restarts = 0
        self._last_progress = now if now is not None else self.clock()

    def maybe_rest(self, now: datetime) -> bool:
        """Take a session break if the policy says so. True = rested (the handler should return)."""
        if not self.policy.should_rest(now):
            return False
        self.policy.end_play(now)
        seconds = self.policy.rest_seconds(now)
        log.info("Resting for %.0f min", seconds / 60)
        self.sleep(seconds)
        self.policy.start_play(self.clock())
        self.mark_progress()
        return True

    def rate_summary(self) -> str:
        if self._started_at is None:
            return "n/a"
        hours = (self.clock() - self._started_at).total_seconds() / 3600
        return self.stats.per_hour(hours)

    # --- stuck detection / recovery --------------------------------------
    def _check_stuck(self, screen: Screen, now: datetime) -> bool:
        task = self.task
        if screen != self._last_screen:
            log.debug("Screen: %s", screen.name)
            if (self._last_screen, screen) in task.forward_transitions:
                self.mark_progress(now)
            self._last_screen = screen
            self._same_ticks = 1
            self._wait_since = now if screen in task.wait_screens else None
        else:
            self._same_ticks += 1
        stuck = (
            (screen in task.action_screens and self._same_ticks > MAX_SAME_ACTION_TICKS)
            or task.is_stuck(screen, self._same_ticks, now)
            or (
                self._wait_since is not None
                and (now - self._wait_since).total_seconds() > self.settings.timing.stuck_timeout_s
            )
        )
        if stuck:
            self._recover(screen)
        return stuck

    def _recover(self, screen: Screen) -> None:
        self.stats.recoveries += 1
        self.game.save_debug_screenshot(f"stuck_{screen.name.lower()}")
        self._same_ticks = 0
        self._failed_actions = 0
        self._wait_since = self.clock() if screen in self.task.wait_screens else None
        self.task.on_recover()
        if self._recover_level == 0:
            log.warning("Stuck on %s, pressing Back", screen.name)
            self._recover_level = 1
            self.game.go_back()
            self._after_recovery()
            return
        if self._consecutive_restarts >= self.settings.timing.max_restarts:
            raise FatalError(f"Still stuck on {screen.name} after {self._consecutive_restarts} restarts")
        self._consecutive_restarts += 1
        self.stats.restarts += 1
        log.warning("Stuck on %s, restarting game (%d/%d)", screen.name,
                    self._consecutive_restarts, self.settings.timing.max_restarts)
        self.game.restart_game()
        self._after_recovery()

    def _after_recovery(self) -> None:
        """Back/restart can take a long time; the next tick starts a fresh stuck timer."""
        self._last_screen = None
        self._same_ticks = 0
        self._wait_since = None
