"""Screen-driven farming loop with stuck detection and escalating recovery."""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from coc_bot.config import Settings
from coc_bot.device.adb import AdbError
from coc_bot.game.loot import Loot, is_worth_attacking, storage_full
from coc_bot.vision.screens import Screen

log = logging.getLogger(__name__)

ACTION_SCREENS = frozenset({Screen.POPUP, Screen.ATTACK_MENU, Screen.RESULT, Screen.ARMY})
WAIT_SCREENS = frozenset({Screen.UNKNOWN, Screen.SEARCHING})
MAX_SAME_ACTION_TICKS = 5
MAX_FAILED_ACTIONS = 5
MAX_ADB_RECONNECTS = 3
BATTLE_OVERRUN_S = 120
FORWARD_TRANSITIONS = frozenset({
    (Screen.HOME, Screen.ATTACK_MENU),
    (Screen.ATTACK_MENU, Screen.SEARCHING),
    (Screen.ATTACK_MENU, Screen.BASE_PREVIEW),
    (Screen.SEARCHING, Screen.BASE_PREVIEW),
    (Screen.BASE_PREVIEW, Screen.BATTLE),
    (Screen.BATTLE, Screen.RESULT),
    (Screen.RESULT, Screen.HOME),
})


class FatalError(RuntimeError):
    """The bot cannot continue safely."""


@dataclass
class Stats:
    attacks: int = 0
    skipped: int = 0
    recoveries: int = 0
    restarts: int = 0

    def per_hour(self, hours: float) -> str:
        if hours <= 0:
            return "n/a"
        return f"{self.attacks / hours:.0f} attacks/h"


class Bot:
    def __init__(
        self,
        game,
        policy,
        settings: Settings,
        rng: random.Random,
        clock: Callable[[], datetime],
        sleep: Callable[[float], None],
        recorder: Callable[[dict], None] | None = None,
    ) -> None:
        self.game = game
        self.policy = policy
        self.settings = settings
        self.rng = rng
        self.clock = clock
        self.sleep = sleep
        self.stats = Stats()
        self.recorder = recorder
        self._started_at: datetime | None = None
        self._attack_started: datetime | None = None
        self._prev_attack_started: datetime | None = None
        self._preview_loot: Loot | None = None
        self._record_pending = False
        self._stop = False
        self._next_count = 0
        self._battle_started: datetime | None = None
        self._last_damage: int = 0
        self._last_damage_time: datetime | None = None
        self._last_screen: Screen | None = None
        self._same_ticks = 0
        self._wait_since: datetime | None = None
        self._recover_level = 0
        self._consecutive_restarts = 0
        self._failed_actions = 0
        self._last_progress: datetime | None = None
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
        self._last_progress = self.clock()
        self._started_at = self.clock()
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
            log.info("Bot stopped. %s | %s", self.stats, self._rate_summary())

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
        self._handlers[screen](now)
        if self._failed_actions >= MAX_FAILED_ACTIONS:
            log.warning("%d game actions in a row did nothing on %s",
                        self._failed_actions, screen.name)
            self._failed_actions = 0
            self._recover(screen)

    def _act(self, ok) -> bool:
        """Track whether a game action actually did something."""
        if ok:
            self._failed_actions = 0
        else:
            self._failed_actions += 1
        return bool(ok)

    def _mark_progress(self, now: datetime | None = None) -> None:
        """The bot got somewhere, so recovery starts from Back again."""
        self._recover_level = 0
        self._consecutive_restarts = 0
        self._last_progress = now if now is not None else self.clock()

    # --- stuck detection / recovery --------------------------------------
    def _check_stuck(self, screen: Screen, now: datetime) -> bool:
        if screen != self._last_screen:
            log.debug("Screen: %s", screen.name)
            if (self._last_screen, screen) in FORWARD_TRANSITIONS:
                self._mark_progress(now)
            self._last_screen = screen
            self._same_ticks = 1
            self._wait_since = now if screen in WAIT_SCREENS else None
        else:
            self._same_ticks += 1
        stuck = (
            (screen in ACTION_SCREENS and self._same_ticks > MAX_SAME_ACTION_TICKS)
            or (screen is Screen.BASE_PREVIEW and self._same_ticks > self.settings.loot.max_next + 10)
            or (
                screen is Screen.BATTLE
                and self._battle_started is not None
                and (now - self._battle_started).total_seconds()
                > self.settings.timing.battle_timeout_s + BATTLE_OVERRUN_S
            )
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
        self._wait_since = self.clock() if screen in WAIT_SCREENS else None
        self._battle_started = None
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

    # --- screen handlers --------------------------------------------------
    def _on_home(self, now: datetime) -> None:
        self._battle_started = None
        if self.policy.should_rest(now):
            self.policy.end_play(now)
            seconds = self.policy.rest_seconds(now)
            log.info("Resting for %.0f min", seconds / 60)
            self.sleep(seconds)
            self.policy.start_play(self.clock())
            self._mark_progress()
            return
        if self._storage_is_full(now):
            return
        log.info("Opening attack menu")
        if self._act(self.game.open_attack_menu()):
            self.sleep(self.rng.uniform(1.0, 2.0))

    def _on_attack_menu(self, now: datetime) -> None:
        self._next_count = 0
        self._act(self.game.find_match())
        self.sleep(self.rng.uniform(1.0, 2.0))

    def _on_army(self, now: datetime) -> None:
        self._act(self.game.close_army())
        self.sleep(1.0)

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
            self._preview_loot = loot
            self._prev_attack_started = self._attack_started
            self._attack_started = now
            self._record_pending = True
            self._battle_started = now
            self._last_damage = 0
            self._last_damage_time = now
            return
        self.stats.skipped += 1
        self._next_count += 1
        log.info("Skip %d: %s", self._next_count, loot)
        self._act(self.game.next_base())
        self.sleep(self.rng.uniform(1.5, 3.0))

    def _on_battle(self, now: datetime) -> None:
        if self._battle_started is None:
            self._battle_started = now
            self._last_damage = 0
            self._last_damage_time = now

        ended = False
        damage = self.game.read_damage_percent()
        if damage is not None:
            if damage > self._last_damage:
                self._last_damage = damage
                self._last_damage_time = now
                log.info("Battle damage: %d%%", damage)

            if damage >= 50:
                log.info("Target 50%% reached (%d%%)! Ending battle immediately for rank win.", damage)
                self.game.end_battle()
                ended = True

        elapsed = (now - self._battle_started).total_seconds()
        if not ended and elapsed >= 8.0 and self._last_damage_time is not None:
            stagnant_s = (now - self._last_damage_time).total_seconds()
            if stagnant_s >= self.settings.timing.damage_stagnant_s:
                log.info("Damage stagnant for %.1fs (current %d%%), ending battle early.",
                         stagnant_s, self._last_damage)
                self.game.end_battle()
                ended = True

        if not ended and elapsed >= self.settings.timing.battle_timeout_s:
            log.info("Battle timeout (%.0fs), ending battle.", elapsed)
            self.game.end_battle()

        self.sleep(3.0)

    def _on_result(self, now: datetime) -> None:
        if self._record_pending and self._attack_started is not None:
            self._record_attack(now)
        self._battle_started = None
        self._last_damage = 0
        self._last_damage_time = None
        self._act(self.game.return_home())
        self.sleep(self.rng.uniform(2.0, 4.0))

    # --- storage / records --------------------------------------------------
    def _storage_is_full(self, now: datetime) -> bool:
        cfg = self.settings.storage
        if not (cfg.gold_cap or cfg.elixir_cap or cfg.de_cap):
            return False
        storage = self.game.read_storage()
        if not storage_full(storage, cfg):
            return False
        if cfg.on_full == "wait":
            log.info("Storage full (%s), waiting %d min", storage, cfg.wait_minutes)
            self.sleep(cfg.wait_minutes * 60)
            self._mark_progress()
            return True
        log.info("Storage full (%s), stopping the bot", storage)
        self.stop()
        return True

    def _record_attack(self, now: datetime) -> None:
        started = self._attack_started
        cycle_s = ((started - self._prev_attack_started).total_seconds()
                   if self._prev_attack_started is not None else None)
        preview = self._preview_loot
        row = {
            "time": now,
            "cycle_s": cycle_s,
            "battle_s": (now - started).total_seconds(),
            "damage_pct": self._last_damage,
            "preview_gold": preview.gold if preview else None,
            "preview_elixir": preview.elixir if preview else None,
            "preview_de": preview.de if preview else None,
        }
        self._record_pending = False
        cycle = f"{cycle_s:.0f}s" if cycle_s is not None else "-"
        log.info("Battle finished: damage %d%%, cycle %s. %s | %s",
                 self._last_damage, cycle, self.stats, self._rate_summary())
        if self.recorder is not None:
            try:
                self.recorder(row)
            except OSError as exc:
                log.warning("Could not write attack record: %s", exc)

    def _rate_summary(self) -> str:
        if self._started_at is None:
            return "n/a"
        hours = (self.clock() - self._started_at).total_seconds() / 3600
        return self.stats.per_hour(hours)

    def _on_popup(self, now: datetime) -> None:
        self._act(self.game.dismiss_popup())
        self.sleep(1.0)
