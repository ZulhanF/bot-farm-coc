"""Home-village farming: find a base with enough loot, deploy, cast spells, end at 50 % / stagnation."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable

from coc_bot import names as N
from coc_bot.game.loot import Loot, is_worth_attacking, storage_full
from coc_bot.vision.screens import Screen

log = logging.getLogger(__name__)

BATTLE_OVERRUN_S = 120


class HomeFarmTask:
    forward_transitions = frozenset({
        (Screen.HOME, Screen.ATTACK_MENU),
        (Screen.ATTACK_MENU, Screen.SEARCHING),
        (Screen.ATTACK_MENU, Screen.BASE_PREVIEW),
        (Screen.SEARCHING, Screen.BASE_PREVIEW),
        (Screen.BASE_PREVIEW, Screen.BATTLE),
        (Screen.BATTLE, Screen.RESULT),
        (Screen.RESULT, Screen.HOME),
    })
    action_screens = frozenset({Screen.POPUP, Screen.ATTACK_MENU, Screen.RESULT})
    wait_screens = frozenset({Screen.UNKNOWN, Screen.SEARCHING})

    def __init__(self, recorder: Callable[[dict], None] | None = None) -> None:
        self.recorder = recorder
        self.loop = None
        self._attack_started: datetime | None = None
        self._prev_attack_started: datetime | None = None
        self._preview_loot: Loot | None = None
        self._record_pending = False
        self._spells_cast = False
        self._next_count = 0
        self._battle_started: datetime | None = None
        self._last_damage: int = 0
        self._last_damage_time: datetime | None = None
        self.handlers = {
            Screen.HOME: self._on_home,
            Screen.ATTACK_MENU: self._on_attack_menu,
            Screen.SEARCHING: self._on_searching,
            Screen.BASE_PREVIEW: self._on_base_preview,
            Screen.BATTLE: self._on_battle,
            Screen.RESULT: self._on_result,
            Screen.POPUP: self._on_popup,
            Screen.UNKNOWN: self._on_unknown,
        }

    # --- Task protocol ----------------------------------------------------
    def bind(self, loop) -> None:
        self.loop = loop

    def on_start(self, now: datetime) -> None:
        self._log_storage_check()

    def is_stuck(self, screen: Screen, same_ticks: int, now: datetime) -> bool:
        if screen is Screen.BASE_PREVIEW and same_ticks > self.settings.loot.max_next + 10:
            return True
        return (
            screen is Screen.BATTLE
            and self._battle_started is not None
            and (now - self._battle_started).total_seconds()
            > self.settings.timing.battle_timeout_s + BATTLE_OVERRUN_S
        )

    def on_recover(self) -> None:
        self._battle_started = None

    def on_resume(self, now: datetime) -> None:
        if self._last_damage_time is not None:
            self._last_damage_time = now

    # --- shortcuts --------------------------------------------------------
    @property
    def game(self):
        return self.loop.game

    @property
    def settings(self):
        return self.loop.settings

    @property
    def stats(self):
        return self.loop.stats

    def sleep(self, seconds: float) -> None:
        self.loop.sleep(seconds)

    # --- screen handlers --------------------------------------------------
    def _on_home(self, now: datetime) -> None:
        self._battle_started = None
        if self.loop.maybe_rest(now):
            return
        if self._storage_is_full(now):
            return
        log.info("Opening attack menu")
        if self.loop.act(self.game.open_attack_menu()):
            self.sleep(self.loop.rng.uniform(1.0, 2.0))

    def _on_attack_menu(self, now: datetime) -> None:
        self._next_count = 0
        self.loop.act(self.game.find_match())
        self.sleep(self.loop.rng.uniform(1.0, 2.0))

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
            self._spells_cast = False
            self._battle_started = now
            self._last_damage = 0
            self._last_damage_time = now
            return
        self.stats.skipped += 1
        self._next_count += 1
        log.info("Skip %d: %s", self._next_count, loot)
        self.loop.act(self.game.next_base())
        self.sleep(self.loop.rng.uniform(1.5, 3.0))

    def _on_battle(self, now: datetime) -> None:
        if self._battle_started is None:
            self._battle_started = now
            self._last_damage = 0
            self._last_damage_time = now

        self._maybe_cast_spells(now)

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

    def _maybe_cast_spells(self, now: datetime) -> None:
        cfg = self.settings.spells
        if not cfg.slots or self._spells_cast or self._battle_started is None:
            return
        if (now - self._battle_started).total_seconds() < cfg.delay_s:
            return
        self._spells_cast = True
        if self.game.cast_spells():
            log.info("Spells cast (slots %s)", list(cfg.slots))
            self._last_damage_time = now  # give the spells time before the stagnation check

    def _on_result(self, now: datetime) -> None:
        if self._record_pending and self._attack_started is not None:
            self._record_attack(now)
        self._battle_started = None
        self._last_damage = 0
        self._last_damage_time = None
        self.loop.act(self.game.return_home())
        self.sleep(self.loop.rng.uniform(2.0, 4.0))

    def _on_popup(self, now: datetime) -> None:
        self.loop.act(self.game.dismiss_popup())
        self.sleep(1.0)

    # --- storage / records ------------------------------------------------
    def _storage_is_full(self, now: datetime) -> bool:
        cfg = self.settings.storage
        if not self.loop.check_storage:
            return False
        levels = self.game.storage_levels()
        if not levels:
            return False
        summary = ", ".join(f"{res} {'?' if lvl is None else f'{lvl:.0%}'}" for res, lvl in levels.items())
        if not storage_full(levels, cfg.full_ratio):
            log.info("Storage: %s", summary)
            return False
        if cfg.on_full == "wait":
            log.info("Storage full (%s), waiting %d min", summary, cfg.wait_minutes)
            self.sleep(cfg.wait_minutes * 60)
            self.loop.mark_progress()
            return True
        log.info("Storage full (%s), stopping the bot", summary)
        self.loop.stop()
        return True

    def _log_storage_check(self) -> None:
        checks = N.storage_checks(self.settings)
        if not self.loop.check_storage:
            log.warning("Storage check switched OFF: the bot attacks even with full storages")
        elif checks:
            log.info("Storage check on: %s (stop when all >= %.0f%%)", ", ".join(checks),
                     self.settings.storage.full_ratio * 100)
        else:
            log.warning("Storage check is OFF: calibrate roi home_gold_bar / home_elixir_bar / "
                        "home_de_bar to stop when storages are full")

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
                 self._last_damage, cycle, self.stats, self.loop.rate_summary())
        if self.recorder is not None:
            try:
                self.recorder(row)
            except OSError as exc:
                log.warning("Could not write attack record: %s", exc)
