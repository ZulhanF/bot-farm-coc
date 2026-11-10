"""Screen-driven farming loop with stuck detection and escalating recovery."""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from coc_bot.config import Settings
from coc_bot.device.adb import AdbError
from coc_bot.game.loot import is_worth_attacking
from coc_bot.vision.screens import Screen

log = logging.getLogger(__name__)

ACTION_SCREENS = frozenset({Screen.POPUP, Screen.ATTACK_MENU, Screen.RESULT, Screen.ARMY})
WAIT_SCREENS = frozenset({Screen.UNKNOWN, Screen.SEARCHING})
PROGRESS_SCREENS = frozenset({Screen.HOME, Screen.BATTLE})
MAX_SAME_ACTION_TICKS = 5
MAX_ADB_RECONNECTS = 3


class FatalError(RuntimeError):
    """The bot cannot continue safely."""


@dataclass
class Stats:
    attacks: int = 0
    skipped: int = 0
    recoveries: int = 0
    restarts: int = 0


class Bot:
    def __init__(
        self,
        game,
        policy,
        settings: Settings,
        rng: random.Random,
        clock: Callable[[], datetime],
        sleep: Callable[[float], None],
    ) -> None:
        self.game = game
        self.policy = policy
        self.settings = settings
        self.rng = rng
        self.clock = clock
        self.sleep = sleep
        self.stats = Stats()
        self._stop = False
        self._trained = False
        self._next_count = 0
        self._battle_started: datetime | None = None
        self._last_screen: Screen | None = None
        self._same_ticks = 0
        self._wait_since: datetime | None = None
        self._recover_level = 0
        self._consecutive_restarts = 0
        self._handlers = {
            Screen.HOME: self._on_home,
            Screen.ATTACK_MENU: self._on_attack_menu,
            Screen.ARMY: self._on_army,
            Screen.SEARCHING: self._on_searching,
            Screen.BASE_PREVIEW: self._on_base_preview,
            Screen.BATTLE: self._on_battle,
            Screen.RESULT: self._on_result,
            Screen.POPUP: self._on_popup,
            Screen.UNKNOWN: self._on_unknown,
        }

    def stop(self) -> None:
        self._stop = True

    def run(self, max_ticks: int | None = None) -> None:
        self.policy.start_play(self.clock())
        adb_failures = 0
        ticks = 0
        while not self._stop and (max_ticks is None or ticks < max_ticks):
            ticks += 1
            try:
                self.tick()
            except AdbError as exc:
                adb_failures += 1
                log.warning("ADB error (%d/%d): %s", adb_failures, MAX_ADB_RECONNECTS, exc)
                if adb_failures > MAX_ADB_RECONNECTS:
                    raise FatalError(f"ADB unavailable after {MAX_ADB_RECONNECTS} reconnects") from exc
                self.sleep(5.0)
                try:
                    self.game.reconnect()
                except AdbError as reconnect_exc:
                    log.warning("Reconnect failed: %s", reconnect_exc)
            else:
                adb_failures = 0
        log.info("Bot stopped. %s", self.stats)

    def tick(self) -> None:
        now = self.clock()
        screen = self.game.screen()
        if self._check_stuck(screen, now):
            return
        self._handlers[screen](now)

    # --- stuck detection / recovery --------------------------------------
    def _check_stuck(self, screen: Screen, now: datetime) -> bool:
        if screen != self._last_screen:
            log.debug("Screen: %s", screen.name)
            self._last_screen = screen
            self._same_ticks = 1
            self._wait_since = now if screen in WAIT_SCREENS else None
            if screen is Screen.UNKNOWN:
                self.game.save_debug_screenshot("unknown")
        else:
            self._same_ticks += 1
        if screen in PROGRESS_SCREENS:
            self._recover_level = 0
            self._consecutive_restarts = 0
        stuck = (
            (screen in ACTION_SCREENS and self._same_ticks > MAX_SAME_ACTION_TICKS)
            or (screen is Screen.BASE_PREVIEW and self._same_ticks > self.settings.loot.max_next + 10)
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
        self._wait_since = self.clock() if screen in WAIT_SCREENS else None
        if self._recover_level == 0:
            log.warning("Stuck on %s, pressing Back", screen.name)
            self._recover_level = 1
            self.game.go_back()
            return
        if self._consecutive_restarts >= self.settings.timing.max_restarts:
            raise FatalError(f"Still stuck on {screen.name} after {self._consecutive_restarts} restarts")
        self._consecutive_restarts += 1
        self.stats.restarts += 1
        log.warning("Stuck on %s, restarting game (%d/%d)", screen.name,
                    self._consecutive_restarts, self.settings.timing.max_restarts)
        self.game.restart_game()

    # --- screen handlers --------------------------------------------------
    def _on_home(self, now: datetime) -> None:
        self._battle_started = None
        if self.policy.should_rest(now):
            self.policy.end_play(now)
            seconds = self.policy.rest_seconds(now)
            log.info("Resting for %.0f min", seconds / 60)
            self.sleep(seconds)
            self.policy.start_play(self.clock())
            return
        if self.game.army_ready():
            log.info("Army ready, opening attack menu")
            self.game.open_attack_menu()
            return
        if not self._trained:
            log.info("Army not ready, quick training")
            self.game.quick_train()
            self._trained = True
        self.sleep(self.rng.uniform(*self.settings.timing.army_poll_s))

    def _on_attack_menu(self, now: datetime) -> None:
        self._next_count = 0
        self.game.find_match()

    def _on_army(self, now: datetime) -> None:
        self.game.close_army()

    def _on_searching(self, now: datetime) -> None:
        self.sleep(1.0)

    def _on_unknown(self, now: datetime) -> None:
        self.sleep(2.0)

    def _on_base_preview(self, now: datetime) -> None:
        loot = self.game.read_loot()
        cfg = self.settings.loot
        worth = is_worth_attacking(loot, cfg)
        if worth or self._next_count >= cfg.max_next:
            log.info("Attacking (%s) %s after %d skips",
                     "loot ok" if worth else "max_next reached", loot, self._next_count)
            self.game.deploy_army()
            self.stats.attacks += 1
            self._trained = False
            self._battle_started = now
            return
        self.stats.skipped += 1
        self._next_count += 1
        log.info("Skip %d: %s", self._next_count, loot)
        self.game.next_base()
        self.sleep(self.rng.uniform(1.5, 3.0))

    def _on_battle(self, now: datetime) -> None:
        if self._battle_started is None:
            self._battle_started = now
        if (now - self._battle_started).total_seconds() >= self.settings.timing.battle_timeout_s:
            log.info("Battle timeout, ending battle")
            self.game.end_battle()
            return
        self.sleep(3.0)

    def _on_result(self, now: datetime) -> None:
        self._battle_started = None
        log.info("Battle finished. %s", self.stats)
        self.game.return_home()
        self.sleep(self.rng.uniform(2.0, 4.0))

    def _on_popup(self, now: datetime) -> None:
        self.game.dismiss_popup()
