"""Builder Base farming.

elixir: drop one troop and surrender at once. Builder Elixir comes from the defense every search opens,
        it waits in the Elixir Cart, which is collected every `cart_every` attacks. Trophies drop over time.
gold:   hero + tank + Night Witches at one point; stage 2 is attacked too when it appears.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable

from coc_bot.bot.engine import FatalError
from coc_bot.config import BUILDER_MODES
from coc_bot.vision.screens import Screen

log = logging.getLogger(__name__)

MAX_BOAT_FAILURES = 3
BATTLE_OVERRUN_S = 120
MIN_STAGE_S = 8.0   # never end a stage for stagnation before this


class BuilderFarmTask:
    forward_transitions = frozenset({
        (Screen.HOME, Screen.BB_HOME),
        (Screen.BB_HOME, Screen.BB_SEARCHING),
        (Screen.BB_HOME, Screen.BB_PREP),
        (Screen.BB_SEARCHING, Screen.BB_PREP),
        (Screen.BB_PREP, Screen.BB_BATTLE),
        (Screen.BB_PREP, Screen.BB_RESULT),
        (Screen.BB_BATTLE, Screen.BB_RESULT),
        (Screen.BB_BATTLE, Screen.BB_STAGE2_PREP),
        (Screen.BB_STAGE2_PREP, Screen.BB_BATTLE),
        (Screen.BB_STAGE2_PREP, Screen.BB_RESULT),
        (Screen.BB_RESULT, Screen.BB_HOME),
    })
    action_screens = frozenset({Screen.POPUP, Screen.HOME, Screen.BB_PREP, Screen.BB_STAGE2_PREP,
                                Screen.BB_RESULT})
    wait_screens = frozenset({Screen.UNKNOWN, Screen.BB_SEARCHING})

    def __init__(self, mode: str | None = None, recorder: Callable[[dict], None] | None = None) -> None:
        self.mode_override = mode
        self.recorder = recorder
        self.loop = None
        self.mode = mode or "elixir"
        self._claimed_once = False
        self._since_claim = 0
        self._boat_failures = 0
        self._attack_started: datetime | None = None
        self._prev_attack_started: datetime | None = None
        self._record_pending = False
        self._stage = 0
        self._stage_started: datetime | None = None
        self._last_damage = 0
        self._last_damage_time: datetime | None = None
        self._damage_seen = False
        self._last_ability: datetime | None = None
        self._abilities_used = False
        self.handlers = {
            Screen.HOME: self._on_village,
            Screen.BB_HOME: self._on_bb_home,
            Screen.BB_SEARCHING: self._on_searching,
            Screen.BB_PREP: self._on_prep,
            Screen.BB_STAGE2_PREP: self._on_stage2_prep,
            Screen.BB_BATTLE: self._on_battle,
            Screen.BB_RESULT: self._on_result,
            Screen.POPUP: self._on_popup,
            Screen.UNKNOWN: self._on_unknown,
        }

    # --- Task protocol ----------------------------------------------------
    def bind(self, loop) -> None:
        self.loop = loop
        self.mode = self.mode_override or loop.settings.builder.mode
        if self.mode not in BUILDER_MODES:
            raise ValueError(f"Builder mode must be one of {', '.join(BUILDER_MODES)}, got {self.mode!r}")

    def on_start(self, now: datetime) -> None:
        log.info("Builder Base farming: mode %s, Elixir Cart every %d attacks", self.mode, self.cfg.cart_every)

    def is_stuck(self, screen: Screen, same_ticks: int, now: datetime) -> bool:
        return (
            screen is Screen.BB_BATTLE
            and self._stage_started is not None
            and (now - self._stage_started).total_seconds() > self.cfg.battle_timeout_s + BATTLE_OVERRUN_S
        )

    def on_recover(self) -> None:
        self._stage_started = None

    def on_resume(self, now: datetime) -> None:
        if self._last_damage_time is not None:
            self._last_damage_time = now

    # --- shortcuts --------------------------------------------------------
    @property
    def game(self):
        return self.loop.game

    @property
    def cfg(self):
        return self.loop.settings.builder

    @property
    def stats(self):
        return self.loop.stats

    def sleep(self, seconds: float) -> None:
        self.loop.sleep(seconds)

    # --- village / search -------------------------------------------------
    def _on_village(self, now: datetime) -> None:
        log.info("Home village: taking the boat to the Builder Base")
        if self.loop.act(self.game.go_to_builder_base()):
            self._boat_failures = 0
            return
        self._boat_failures += 1
        if self._boat_failures >= MAX_BOAT_FAILURES:
            raise FatalError("Boat to the Builder Base not found: calibrate template bb_boat "
                             "(is the Builder Base unlocked?)")
        self.sleep(2.0)

    def _on_bb_home(self, now: datetime) -> None:
        self._stage_started = None
        if self.loop.maybe_rest(now):
            return
        if not self._claimed_once or self._since_claim >= self.cfg.cart_every:
            self._claimed_once = True
            if self.game.collect_cart():
                self._since_claim = 0
                self.stats.carts += 1
                log.info("Elixir Cart collected (%d so far)", self.stats.carts)
            else:
                # try again after the next attack instead of every tick
                self._since_claim = self.cfg.cart_every - 1
                log.warning("Elixir Cart not collected, trying again after the next attack")
            return
        log.info("Builder Base: searching for an opponent")
        if self.loop.act(self.game.open_attack()):
            self.sleep(self.loop.rng.uniform(1.0, 2.0))

    def _on_searching(self, now: datetime) -> None:
        self.sleep(1.0)

    def _on_unknown(self, now: datetime) -> None:
        self.sleep(2.0)

    def _on_popup(self, now: datetime) -> None:
        self.loop.act(self.game.dismiss_popup())
        self.sleep(1.0)

    # --- battle -------------------------------------------------------------
    def _begin_attack(self, now: datetime) -> None:
        self.stats.attacks += 1
        self._since_claim += 1
        self._prev_attack_started = self._attack_started
        self._attack_started = now
        self._record_pending = True
        self._stage = 0
        self._last_damage = 0

    def _on_prep(self, now: datetime) -> None:
        self._begin_attack(now)
        if self.mode == "elixir":
            self.game.drop_one_troop()
            self.sleep(self.cfg.surrender_after_s)
            self.game.surrender()
            return
        self._start_stage(1)

    def _start_stage(self, stage: int) -> None:
        log.info("Stage %d: deploying at one point", stage)
        self.game.deploy_stage(stage)
        now = self.loop.clock()
        self._stage = stage
        self._stage_started = now
        self._last_damage_time = now
        self._damage_seen = False
        self._last_ability = None
        self._abilities_used = False

    def _on_stage2_prep(self, now: datetime) -> None:
        if self.mode == "elixir" or not self.cfg.stage2:
            log.info("Stage 2 reached, ending the battle (stage2 off)")
            self.loop.act(self.game.surrender())
            return
        self.stats.stage2 += 1
        self._start_stage(2)

    def _on_battle(self, now: datetime) -> None:
        if self.mode == "elixir":
            self.loop.act(self.game.surrender())
            self.sleep(1.0)
            return
        self._gold_battle(now)

    def _gold_battle(self, now: datetime) -> None:
        cfg = self.cfg
        if self._stage_started is None:          # e.g. after a recovery: track from now
            self._stage = max(self._stage, 1)
            self._stage_started = now
            self._last_damage_time = now
        elapsed = (now - self._stage_started).total_seconds()

        if self._last_ability is None or (now - self._last_ability).total_seconds() >= cfg.ability_every_s:
            self.game.hero_ability()
            self._last_ability = now
        if not self._abilities_used and elapsed >= cfg.bat_swarm_after_s:
            self.game.troop_abilities()
            self._abilities_used = True

        damage = self.game.read_damage()
        if damage is not None:
            self._damage_seen = True
            if damage > self._last_damage:
                self._last_damage = damage
                self._last_damage_time = now
                log.info("Stage %d damage: %d%%", self._stage, damage)

        stagnant = (now - self._last_damage_time).total_seconds() if self._last_damage_time else 0.0
        if self._damage_seen and elapsed >= MIN_STAGE_S and stagnant >= cfg.damage_stagnant_s:
            log.info("Damage stuck at %d%% for %.0fs, ending the battle", self._last_damage, stagnant)
            self.game.surrender()
        elif elapsed >= cfg.battle_timeout_s:
            log.info("Stage %d timeout (%.0fs), ending the battle", self._stage, elapsed)
            self.game.surrender()
        self.sleep(2.0)

    def _on_result(self, now: datetime) -> None:
        if self._record_pending and self._attack_started is not None:
            self._record(now)
        self._stage_started = None
        self.loop.act(self.game.return_home())
        self.sleep(self.loop.rng.uniform(2.0, 4.0))

    def _record(self, now: datetime) -> None:
        started = self._attack_started
        cycle_s = ((started - self._prev_attack_started).total_seconds()
                   if self._prev_attack_started is not None else None)
        gold = self.game.read_result_gold()
        row = {
            "time": now,
            "mode": self.mode,
            "cycle_s": cycle_s,
            "battle_s": (now - started).total_seconds(),
            "damage_pct": self._last_damage if self.mode == "gold" else None,
            "gold": gold,
            "stage2": self._stage == 2,
        }
        self._record_pending = False
        log.info("Builder battle finished (%s): damage %s, gold %s. %s | %s", self.mode,
                 row["damage_pct"], gold, self.stats, self.loop.rate_summary())
        if self.recorder is not None:
            try:
                self.recorder(row)
            except OSError as exc:
                log.warning("Could not write builder record: %s", exc)
