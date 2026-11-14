# Builder Base Farm Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `builder` run mode that farms the Builder Base in two sub-modes — `elixir` (drop one troop, surrender, collect the Elixir Cart every N attacks) and `gold` (hero + Giant + Night Witch at one point, including stage 2) — on top of a shared screen-loop engine.

**Architecture:** Split today's `Bot` (`coc_bot/bot/state_machine.py`) into a village-neutral `ScreenLoop` (engine: tick, stuck detection, Back→restart→fatal recovery, ADB reconnects, session rests) and pluggable tasks (`HomeFarmTask`, `BuilderFarmTask`) that own the per-screen handlers. `Bot` stays as a thin facade (`ScreenLoop` + `HomeFarmTask`) so existing tests and imports keep working. Builder actions live in `BuilderGame(Game)`; Builder screens are added to the `Screen` enum with their own marker list.

**Tech Stack:** Python 3.12, OpenCV template matching, RapidOCR, pytest, Textual (dashboard). Run everything from `D:\Bot Farm COC` with `.venv/Scripts/python`.

**Spec:** `docs/superpowers/specs/2026-11-14-builder-base-farm-design.md`

## Global Constraints

- Emulator resolution 1280×720 (unchanged); all coordinates come from `calibration.toml`.
- Home-village behaviour must not change: the full existing suite (183 tests) passes after every task.
- `[builder]` is a **flat** settings section (the loader only supports flat sections).
- Builder sub-modes are exactly `"elixir"` and `"gold"`; default `"elixir"`; `cart_every` default `15`.
- Trophies are allowed to drop in elixir mode (no trophy keeping).
- Stage 2 is attacked in gold mode when `stage2 = true` (default).
- Builder card slots are calibrated as points `bb_slot_N` (N = 1..8), separate from the home `troop_slot_N`.
- Log messages in English (like the existing code); user-facing dashboard text in Indonesian.
- Git: the user approves every commit explicitly. Each task ends with a commit step — ask before running it; never push.
- Test command: `.venv/Scripts/python -m pytest -q` (from `D:\Bot Farm COC`).

## File map

| File | Change | Responsibility |
|---|---|---|
| `coc_bot/bot/task.py` | create | `Task` protocol |
| `coc_bot/bot/engine.py` | create | `ScreenLoop`, `Stats`, `FatalError` |
| `coc_bot/bot/home_task.py` | create | `HomeFarmTask` (moved home handlers) |
| `coc_bot/bot/state_machine.py` | rewrite | `Bot` facade + re-exports |
| `coc_bot/bot/builder_task.py` | create | `BuilderFarmTask` |
| `coc_bot/bot/records.py` | modify | `CsvRecorder(prefix, fields)`, `BUILDER_FIELDS` |
| `coc_bot/config.py` | modify | `BuilderConfig`, `[builder]` section |
| `coc_bot/names.py` | modify | Builder template/ROI/point names, builder calibration checks |
| `coc_bot/vision/screens.py` | modify | `BB_*` screens, `detect_builder_screen` |
| `coc_bot/game/builder.py` | create | `BuilderGame(Game)` actions |
| `coc_bot/control.py` | modify | `Mode.BUILDER` available, `builder_mode`, task wiring, `mode_label` |
| `coc_bot/main.py` | modify | `run --builder-mode`, `check --mode` |
| `coc_bot/tui/app.py`, `pages.py`, `info.py` | modify | builder sub-modes in Mode page, mode-aware calibration |
| `settings.example.toml`, `README.md`, `docs/ROADMAP.md` | modify | document `[builder]` |
| `tests/test_engine.py`, `test_builder_config.py`, `test_builder_names.py`, `test_builder_game.py`, `test_builder_task.py` | create | new tests |
| `tests/fakes.py`, `test_control.py` | modify | `FakeBuilderGame`, builder runner tests |

---

### Task 1: Split the loop into engine + home task

**Files:**
- Create: `coc_bot/bot/task.py`, `coc_bot/bot/engine.py`, `coc_bot/bot/home_task.py`
- Rewrite: `coc_bot/bot/state_machine.py`
- Test: `tests/test_engine.py` (new), `tests/test_state_machine.py` (unchanged, must pass)

**Interfaces:**
- Produces:
  - `coc_bot.bot.engine.ScreenLoop(game, task, policy, settings, rng, clock, sleep)` with public `stats: Stats`, `check_storage: bool`, `stop()`, `current_screen`, `reset_timers()`, `run(max_ticks=None)`, `tick()`, and helpers for tasks: `act(ok) -> bool`, `mark_progress(now=None)`, `maybe_rest(now) -> bool`, `rate_summary() -> str`, attributes `game`, `settings`, `rng`, `clock`, `sleep`, `policy`.
  - `coc_bot.bot.engine.Stats` dataclass: `attacks, skipped, recoveries, restarts, carts, stage2` (all `int = 0`), `per_hour(hours) -> str`.
  - `coc_bot.bot.engine.FatalError(RuntimeError)`.
  - `coc_bot.bot.task.Task` protocol: attributes `handlers: dict[Screen, Callable[[datetime], None]]`, `forward_transitions`, `action_screens`, `wait_screens` (frozensets); methods `bind(loop)`, `on_start(now)`, `is_stuck(screen, same_ticks, now) -> bool`, `on_recover()`, `on_resume(now)`.
  - `coc_bot.bot.home_task.HomeFarmTask(recorder=None)`.
  - `coc_bot.bot.state_machine.Bot(game, policy, settings, rng, clock, sleep, recorder=None)` (same signature as today), re-exports `FatalError`, `Stats`.

- [ ] **Step 1: Write the failing engine test**

Create `tests/test_engine.py`:

```python
import random
from datetime import datetime

from coc_bot.bot.engine import ScreenLoop
from coc_bot.vision.screens import Screen
from tests.fakes import FakeClock, FakeGame, FakePolicy, make_settings


class DummyTask:
    forward_transitions = frozenset({(Screen.HOME, Screen.ATTACK_MENU)})
    action_screens = frozenset({Screen.ATTACK_MENU})
    wait_screens = frozenset({Screen.UNKNOWN})

    def __init__(self, stuck=False):
        self.events = []
        self.stuck = stuck
        self.loop = None
        self.handlers = {Screen.ATTACK_MENU: lambda now: self.events.append("menu")}

    def bind(self, loop):
        self.loop = loop

    def on_start(self, now):
        self.events.append("start")

    def is_stuck(self, screen, same_ticks, now):
        return self.stuck

    def on_recover(self):
        self.events.append("recover")

    def on_resume(self, now):
        self.events.append("resume")


def make_loop(screens, task):
    clock = FakeClock()
    game = FakeGame(screens)
    loop = ScreenLoop(game, task, FakePolicy(), make_settings(), random.Random(0),
                      clock=clock.now, sleep=clock.sleep)
    return loop, game, clock


def test_bind_and_dispatch():
    task = DummyTask()
    loop, _, _ = make_loop([Screen.ATTACK_MENU], task)
    assert task.loop is loop
    loop.tick()
    assert task.events == ["menu"]


def test_on_start_called_once_per_run():
    task = DummyTask()
    loop, _, _ = make_loop([Screen.ATTACK_MENU], task)
    loop.run(max_ticks=3)
    assert task.events.count("start") == 1


def test_unhandled_screen_waits():
    task = DummyTask()
    loop, _, clock = make_loop([Screen.RESULT], task)
    loop.tick()
    assert clock.slept == [2.0]


def test_task_stuck_rule_triggers_back_and_on_recover():
    task = DummyTask(stuck=True)
    loop, game, _ = make_loop([Screen.ATTACK_MENU], task)
    loop.tick()
    assert game.count("go_back") == 1
    assert "recover" in task.events
    assert loop.stats.recoveries == 1


def test_reset_timers_notifies_task():
    task = DummyTask()
    loop, _, _ = make_loop([Screen.ATTACK_MENU], task)
    loop.reset_timers()
    assert task.events == ["resume"]


def test_stats_has_builder_counters():
    task = DummyTask()
    loop, _, _ = make_loop([Screen.ATTACK_MENU], task)
    assert loop.stats.carts == 0 and loop.stats.stage2 == 0
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_engine.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'coc_bot.bot.engine'`

- [ ] **Step 3: Create `coc_bot/bot/task.py`**

```python
"""What a task plugs into the screen loop: one handler per screen plus its own stuck rules."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Callable, Protocol

from coc_bot.vision.screens import Screen

if TYPE_CHECKING:
    from coc_bot.bot.engine import ScreenLoop

Handler = Callable[[datetime], None]


class Task(Protocol):
    handlers: dict[Screen, Handler]
    forward_transitions: frozenset[tuple[Screen, Screen]]  # moving along these = progress
    action_screens: frozenset[Screen]   # stuck if the same screen repeats too many ticks
    wait_screens: frozenset[Screen]     # stuck if shown longer than timing.stuck_timeout_s

    def bind(self, loop: ScreenLoop) -> None: ...
    def on_start(self, now: datetime) -> None: ...
    def is_stuck(self, screen: Screen, same_ticks: int, now: datetime) -> bool: ...
    def on_recover(self) -> None: ...
    def on_resume(self, now: datetime) -> None: ...
```

- [ ] **Step 4: Create `coc_bot/bot/engine.py`**

```python
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
```

- [ ] **Step 5: Create `coc_bot/bot/home_task.py`** (the home handlers moved out of `state_machine.py`; behaviour identical)

```python
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
```

- [ ] **Step 6: Rewrite `coc_bot/bot/state_machine.py` as the facade**

```python
"""Home-village farming bot: the shared screen loop running the home farming task.

Kept as the import point for existing callers and tests; the loop lives in `engine.py`,
the home handlers in `home_task.py`.
"""
from __future__ import annotations

import random
from datetime import datetime
from typing import Callable

from coc_bot.bot.engine import FatalError, ScreenLoop, Stats
from coc_bot.bot.home_task import HomeFarmTask
from coc_bot.config import Settings

__all__ = ["Bot", "FatalError", "Stats"]


class Bot(ScreenLoop):
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
        super().__init__(game, HomeFarmTask(recorder), policy, settings, rng, clock, sleep)
```

- [ ] **Step 7: Run the whole suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all tests pass (183 existing + 6 new = 189). If a `test_state_machine.py` test fails, the move changed behaviour — diff the handler against the original in `git show HEAD:coc_bot/bot/state_machine.py` and fix the task, not the test.

- [ ] **Step 8: Commit (ask the user first)**

```bash
git add coc_bot/bot/task.py coc_bot/bot/engine.py coc_bot/bot/home_task.py coc_bot/bot/state_machine.py tests/test_engine.py
git commit -m "refactor: split the bot loop into a shared engine and a home farming task"
```

---

### Task 2: `[builder]` settings

**Files:**
- Modify: `coc_bot/config.py`, `settings.example.toml`
- Test: `tests/test_builder_config.py` (new)

**Interfaces:**
- Produces: `coc_bot.config.BuilderConfig` (frozen dataclass) with fields
  `mode: str = "elixir"`, `cart_every: int = 15`, `troop_slot: int = 2`, `surrender_after_s: float = 1.5`,
  `hero_slot: int = 1`, `tank_slot: int = 2`, `main_slots: tuple[int, ...] = (3, 4, 5, 6)`,
  `taps_per_slot: int = 3`, `witch_delay_s: float = 2.0`, `ability_every_s: float = 3.0`,
  `bat_swarm_after_s: float = 6.0`, `damage_stagnant_s: float = 12.0`, `battle_timeout_s: int = 150`,
  `stage2: bool = True`, `stage2_slots: tuple[int, ...] = ()`; `coc_bot.config.BUILDER_MODES = ("elixir", "gold")`;
  `Settings.builder: BuilderConfig`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_builder_config.py`:

```python
import pytest

from coc_bot.config import BUILDER_MODES, BuilderConfig, Settings, load_settings


def write(tmp_path, text):
    path = tmp_path / "settings.toml"
    path.write_text(text, encoding="utf-8")
    return load_settings(path, tmp_path / "calibration.toml")


def test_defaults():
    b = Settings().builder
    assert b.mode == "elixir" and b.cart_every == 15 and b.stage2 is True
    assert BUILDER_MODES == ("elixir", "gold")


def test_loaded_from_toml(tmp_path):
    s = write(tmp_path, '[builder]\nmode = "gold"\ncart_every = 5\nmain_slots = [3, 4]\n')
    assert s.builder.mode == "gold"
    assert s.builder.cart_every == 5
    assert s.builder.main_slots == (3, 4)


def test_unknown_mode_rejected(tmp_path):
    with pytest.raises(ValueError, match="mode"):
        write(tmp_path, '[builder]\nmode = "dark"\n')


def test_cart_every_must_be_positive():
    with pytest.raises(ValueError, match="cart_every"):
        BuilderConfig(cart_every=0)


def test_slots_start_at_one():
    with pytest.raises(ValueError, match="slot"):
        BuilderConfig(main_slots=(0, 3))


def test_tank_slot_zero_means_no_tank():
    assert BuilderConfig(tank_slot=0).tank_slot == 0


def test_unknown_key_rejected(tmp_path):
    with pytest.raises(ValueError, match="Unknown key"):
        write(tmp_path, "[builder]\nbogus = 1\n")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_builder_config.py -q`
Expected: FAIL with `ImportError: cannot import name 'BUILDER_MODES'`

- [ ] **Step 3: Add `BuilderConfig` to `coc_bot/config.py`**

Insert after `VisionConfig`:

```python
BUILDER_MODES = ("elixir", "gold")
BB_MAX_SLOTS = 8


@dataclass(frozen=True)
class BuilderConfig:
    mode: str = "elixir"             # "elixir" = 1 troop + surrender, "gold" = hero + tank + Night Witch push
    cart_every: int = 15             # collect the Elixir Cart every N attacks (both modes)
    troop_slot: int = 2              # elixir: the one card dropped before surrendering
    surrender_after_s: float = 1.5
    hero_slot: int = 1               # gold: hero card (pick Battle Copter in the army screen)
    tank_slot: int = 2               # gold: Giant; 0 = no tank
    main_slots: tuple[int, ...] = (3, 4, 5, 6)   # gold: Night Witch cards
    taps_per_slot: int = 3           # taps on the deploy point per card (empties the card)
    witch_delay_s: float = 2.0       # wait after the tank before the Night Witches
    ability_every_s: float = 3.0     # tap the hero card this often (does nothing until charged)
    bat_swarm_after_s: float = 6.0   # tap the Night Witch cards once (Bat Swarm) after this long
    damage_stagnant_s: float = 12.0  # end the stage if the damage % stops rising this long
    battle_timeout_s: int = 150      # per stage (the game's own timer is 2 minutes)
    stage2: bool = True              # attack stage 2 when it appears
    stage2_slots: tuple[int, ...] = ()   # extra cards on stage 2 (Reinforcement Camp troops)

    def __post_init__(self) -> None:
        if self.mode not in BUILDER_MODES:
            raise ValueError(f"[builder] mode must be one of {', '.join(BUILDER_MODES)}, got {self.mode!r}")
        if self.cart_every < 1:
            raise ValueError("[builder] cart_every must be at least 1")
        slots = (self.troop_slot, self.hero_slot, *self.main_slots, *self.stage2_slots)
        if any(not 1 <= s <= BB_MAX_SLOTS for s in slots) or not 0 <= self.tank_slot <= BB_MAX_SLOTS:
            raise ValueError(f"[builder] card slots run from 1 to {BB_MAX_SLOTS} (tank_slot 0 = no tank)")
```

Add the field to `Settings` (after `vision`):

```python
    builder: BuilderConfig = field(default_factory=BuilderConfig)
```

Add to `_SECTIONS`:

```python
    "builder": BuilderConfig,
```

- [ ] **Step 4: Document it in `settings.example.toml`** — append before `[vision]`:

```toml
[builder]
# Builder Base (desa malam), used by `run --mode builder`. Card slots = points bb_slot_N.
mode = "elixir"          # "elixir" = drop 1 troop + surrender (elixir comes from defenses, trophies drop)
                         # "gold"   = hero + Giant + Night Witch at one point, stage 2 too
cart_every = 15          # collect the Elixir Cart every N attacks
troop_slot = 2           # elixir: card dropped before surrendering
surrender_after_s = 1.5
hero_slot = 1            # gold: hero card (choose Battle Copter in the Builder Base army screen)
tank_slot = 2            # gold: Giant (0 = no tank)
main_slots = [3, 4, 5, 6]  # gold: Night Witch cards
taps_per_slot = 3
witch_delay_s = 2.0
ability_every_s = 3.0    # tap the hero card this often to fire its ability
bat_swarm_after_s = 6.0
damage_stagnant_s = 12.0
battle_timeout_s = 150
stage2 = true
stage2_slots = []        # extra stage-2 cards (Reinforcement Camp)
```

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit (ask the user first)**

```bash
git add coc_bot/config.py settings.example.toml tests/test_builder_config.py
git commit -m "feat: [builder] settings for Builder Base farming"
```

---

### Task 3: Builder names, screens and calibration checks

**Files:**
- Modify: `coc_bot/names.py`, `coc_bot/vision/screens.py`
- Test: `tests/test_builder_names.py` (new)

**Interfaces:**
- Consumes: `Settings.builder` (Task 2).
- Produces:
  - Template names `N.BB_BOAT, BB_ATTACK, BB_BTN_FIND_NOW, BB_SEARCHING, BB_PREP, BB_STAGE2_PREP, BB_BTN_SURRENDER, BB_BTN_END_BATTLE, BB_BTN_RETURN_HOME, BB_ELIXIR_CART, BB_BTN_COLLECT`; `N.BB_TEMPLATES` (tuple of all).
  - ROIs `N.ROI_BB_DAMAGE = "bb_damage"`, `N.ROI_BB_RESULT_GOLD = "bb_result_gold"`, `N.MAX_BB_DAMAGE = 200`, `N.MAX_BB_GOLD = 10_000_000`.
  - Points `N.BB_DEPLOY_STAGE1`, `N.BB_DEPLOY_STAGE2`, `N.bb_slot(n) -> str`.
  - `N.builder_slots(settings) -> tuple[int, ...]`, `N.builder_requirements(settings) -> list[tuple[str, str]]`, `N.missing_builder_calibration(settings, template_names) -> list[str]`, `N.missing_for_mode(settings, template_names, mode: str) -> list[str]`, `N.relevant_for_mode(settings, mode: str) -> list[tuple[str, str]]`.
  - `Screen.BB_HOME, BB_SEARCHING, BB_PREP, BB_STAGE2_PREP, BB_BATTLE, BB_RESULT`; `coc_bot.vision.screens.detect_builder_screen(image, templates) -> Screen`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_builder_names.py`:

```python
from dataclasses import replace

import numpy as np

from coc_bot import names as N
from coc_bot.config import BuilderConfig, Settings
from coc_bot.vision.screens import Screen, detect_builder_screen
from tests.fakes import FakeTemplates

IMG = np.zeros((720, 1280, 3), np.uint8)


def builder(**kw):
    return replace(Settings(), builder=BuilderConfig(**kw))


def test_elixir_mode_needs_one_slot_and_stage1_point():
    items = N.builder_requirements(builder(mode="elixir", troop_slot=2))
    assert ("point", "bb_slot_2") in items
    assert ("point", N.BB_DEPLOY_STAGE1) in items
    assert ("point", N.BB_DEPLOY_STAGE2) not in items
    assert ("template", N.BB_STAGE2_PREP) not in items
    assert ("template", N.BB_BOAT) in items and ("template", N.HOME_ATTACK) in items


def test_gold_mode_needs_stage2_and_damage_roi():
    items = N.builder_requirements(builder(mode="gold", hero_slot=1, tank_slot=2, main_slots=(3, 4),
                                           stage2_slots=(5,)))
    assert ("template", N.BB_STAGE2_PREP) in items
    assert ("roi", N.ROI_BB_DAMAGE) in items
    assert ("point", N.BB_DEPLOY_STAGE2) in items
    assert [n for k, n in items if n.startswith("bb_slot_")] == [f"bb_slot_{i}" for i in (1, 2, 3, 4, 5)]


def test_gold_without_stage2_skips_stage2_point_and_slots():
    s = builder(mode="gold", stage2=False, stage2_slots=(7,))
    items = N.builder_requirements(s)
    assert ("point", N.BB_DEPLOY_STAGE2) not in items
    assert ("point", "bb_slot_7") not in items


def test_missing_builder_calibration_lists_everything_then_nothing():
    s = builder(mode="elixir")
    assert "template:bb_boat" in N.missing_builder_calibration(s, set())
    cal = s.calibration
    names = set()
    for kind, name in N.builder_requirements(s):
        key = {"template": "templates", "roi": "rois", "point": "points"}[kind]
        cal = cal.with_entry(key, name, (1, 1, 5, 5) if kind != "point" else (1, 1))
        if kind == "template":
            names.add(name)
    s = replace(s, calibration=cal)
    assert N.missing_builder_calibration(s, names) == []


def test_missing_for_mode_dispatches():
    s = Settings()
    assert "template:home_attack" in N.missing_for_mode(s, set(), "home")
    assert "template:bb_boat" in N.missing_for_mode(s, set(), "builder")
    assert "template:bb_boat" not in N.missing_for_mode(s, set(), "home")


def test_valid_names_accept_builder_items():
    assert N.BB_BOAT in N.valid_names("template", (1,))
    assert N.ROI_BB_DAMAGE in N.valid_names("roi", (1,))
    assert "bb_slot_8" in N.valid_names("point", (1,))
    assert N.BB_DEPLOY_STAGE2 in N.valid_names("point", (1,))


def test_relevant_for_mode_builder_includes_optional_items():
    items = N.relevant_for_mode(builder(mode="gold"), "builder")
    assert ("template", N.BB_SEARCHING) in items
    assert ("roi", N.ROI_BB_RESULT_GOLD) in items
    assert len(items) == len(set(items))


def test_detect_builder_screens_in_priority_order():
    cases = [
        ({N.BB_BTN_RETURN_HOME, N.BB_BTN_SURRENDER}, Screen.BB_RESULT),
        ({N.BB_STAGE2_PREP, N.BB_BTN_END_BATTLE}, Screen.BB_STAGE2_PREP),
        ({N.BB_PREP, N.BB_BTN_SURRENDER}, Screen.BB_PREP),
        ({N.BB_BTN_SURRENDER}, Screen.BB_BATTLE),
        ({N.BB_BTN_END_BATTLE}, Screen.BB_BATTLE),
        ({N.BB_ATTACK, N.HOME_ATTACK}, Screen.BB_HOME),
        ({N.BB_SEARCHING}, Screen.BB_SEARCHING),
        ({N.HOME_ATTACK}, Screen.HOME),
        ({N.POPUP_OKAY, N.BB_BTN_SURRENDER}, Screen.POPUP),
        (set(), Screen.UNKNOWN),
    ]
    for visible, expected in cases:
        assert detect_builder_screen(IMG, FakeTemplates(visible)) is expected, visible
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_builder_names.py -q`
Expected: FAIL with `ImportError: cannot import name 'detect_builder_screen'`

- [ ] **Step 3: Add the builder names to `coc_bot/names.py`**

Insert after the popup block (before `REQUIRED_TEMPLATES`):

```python
# Builder Base (desa malam)
BB_BOAT = "bb_boat"                    # boat on the home village that sails to the Builder Base
BB_ATTACK = "bb_attack"                # Attack button on the Builder Base (also its screen marker)
BB_BTN_FIND_NOW = "bb_btn_find_now"    # "Find Now" in the Builder Base attack panel
BB_SEARCHING = "bb_searching"          # searching for an opponent
BB_PREP = "bb_prep"                    # stage-1 preparation banner ("battle starts in ...")
BB_STAGE2_PREP = "bb_stage2_prep"      # stage-2 preparation screen
BB_BTN_SURRENDER = "bb_btn_surrender"  # Surrender during a Builder Base battle
BB_BTN_END_BATTLE = "bb_btn_end_battle"  # End Battle (after stars, or on the stage-2 screen)
BB_BTN_RETURN_HOME = "bb_btn_return_home"  # Return Home on the Builder Base result screen
BB_ELIXIR_CART = "bb_elixir_cart"      # the Elixir Cart next to the boat
BB_BTN_COLLECT = "bb_btn_collect"      # Collect in the Elixir Cart window
BB_TEMPLATES = (
    BB_BOAT, BB_ATTACK, BB_BTN_FIND_NOW, BB_SEARCHING, BB_PREP, BB_STAGE2_PREP, BB_BTN_SURRENDER,
    BB_BTN_END_BATTLE, BB_BTN_RETURN_HOME, BB_ELIXIR_CART, BB_BTN_COLLECT,
)
```

Insert after `ROI_LIMITS`:

```python
ROI_BB_DAMAGE = "bb_damage"            # destruction % during a Builder Base battle (0-200)
ROI_BB_RESULT_GOLD = "bb_result_gold"  # Builder Gold won, on the result screen
BB_ROIS = (ROI_BB_DAMAGE, ROI_BB_RESULT_GOLD)
MAX_BB_DAMAGE = 200
MAX_BB_GOLD = 10_000_000
```

Insert after `MAP_CENTER`:

```python
BB_DEPLOY_STAGE1 = "bb_deploy_stage1"  # the single deploy point on stage 1
BB_DEPLOY_STAGE2 = "bb_deploy_stage2"  # the single deploy point on stage 2


def bb_slot(n: int) -> str:
    return f"bb_slot_{n}"
```

Change the config import at the top of `names.py` to `from coc_bot.config import BB_MAX_SLOTS, Settings`, then replace `valid_names` with:

```python
def valid_names(kind: str, troop_slots: tuple[int, ...]) -> tuple[str, ...]:
    if kind == "template":
        return REQUIRED_TEMPLATES + OPTIONAL_TEMPLATES + BB_TEMPLATES
    if kind == "roi":
        return REQUIRED_ROIS + OPTIONAL_ROIS + BB_ROIS
    if kind == "point":
        return (MAP_CLOCK_POINTS + MAP_CORNERS + (MAP_CENTER,) + tuple(troop_slot(n) for n in troop_slots)
                + (BB_DEPLOY_STAGE1, BB_DEPLOY_STAGE2)
                + tuple(bb_slot(n) for n in range(1, BB_MAX_SLOTS + 1)))
    raise ValueError(f"Unknown kind: {kind}")
```

Append at the end of the file:

```python
# --- Builder Base calibration -----------------------------------------------------------------
_BB_BASE_TEMPLATES = (
    HOME_ATTACK, BB_BOAT, BB_ATTACK, BB_BTN_FIND_NOW, BB_PREP, BB_BTN_SURRENDER, BB_BTN_RETURN_HOME,
    BB_ELIXIR_CART, BB_BTN_COLLECT, POPUP_OKAY,
)
_BB_OPTIONAL = (
    [("template", n) for n in (BB_SEARCHING, BB_BTN_END_BATTLE, BB_STAGE2_PREP,
                               POPUP_RELOAD, POPUP_TRY_AGAIN, POPUP_CLOSE)]
    + [("roi", ROI_BB_DAMAGE), ("roi", ROI_BB_RESULT_GOLD)]
)


def builder_slots(settings: Settings) -> tuple[int, ...]:
    """Builder Base card slots the current [builder] settings tap."""
    b = settings.builder
    if b.mode == "elixir":
        return (b.troop_slot,)
    slots = {b.hero_slot, *b.main_slots}
    if b.tank_slot > 0:
        slots.add(b.tank_slot)
    if b.stage2:
        slots |= set(b.stage2_slots)
    return tuple(sorted(slots))


def builder_requirements(settings: Settings) -> list[tuple[str, str]]:
    """(kind, name) of every calibration item the builder mode cannot run without."""
    b = settings.builder
    gold = b.mode == "gold"
    items = [("template", n) for n in _BB_BASE_TEMPLATES]
    if gold:
        items += [("template", BB_STAGE2_PREP), ("roi", ROI_BB_DAMAGE)]
    items.append(("point", BB_DEPLOY_STAGE1))
    if gold and b.stage2:
        items.append(("point", BB_DEPLOY_STAGE2))
    items += [("point", bb_slot(n)) for n in builder_slots(settings)]
    return items


def missing_builder_calibration(settings: Settings, template_names: set[str]) -> list[str]:
    cal = settings.calibration
    have = {"template": cal.templates, "roi": cal.rois, "point": cal.points}
    return [
        f"{kind}:{name}" for kind, name in builder_requirements(settings)
        if name not in have[kind] or (kind == "template" and name not in template_names)
    ]


def missing_for_mode(settings: Settings, template_names: set[str], mode: str) -> list[str]:
    if mode == "builder":
        return missing_builder_calibration(settings, template_names)
    return missing_calibration(settings, template_names)


def relevant_for_mode(settings: Settings, mode: str) -> list[tuple[str, str]]:
    if mode != "builder":
        return relevant_names(settings)
    required = builder_requirements(settings)
    return required + [item for item in _BB_OPTIONAL if item not in required]
```

- [ ] **Step 4: Add the builder screens to `coc_bot/vision/screens.py`**

Add members to `Screen` (after `RESULT`):

```python
    BB_HOME = "bb_home"
    BB_SEARCHING = "bb_searching"
    BB_PREP = "bb_prep"
    BB_STAGE2_PREP = "bb_stage2_prep"
    BB_BATTLE = "bb_battle"
    BB_RESULT = "bb_result"
```

Replace `detect_screen` with a shared helper plus the builder marker list:

```python
# Builder Base: result first (it may still show battle buttons), prep screens before battle (the
# surrender button is already visible while preparing), the home village last (boat target).
BUILDER_MARKERS: tuple[tuple[Screen, str], ...] = (
    (Screen.BB_RESULT, N.BB_BTN_RETURN_HOME),
    (Screen.BB_STAGE2_PREP, N.BB_STAGE2_PREP),
    (Screen.BB_PREP, N.BB_PREP),
    (Screen.BB_BATTLE, N.BB_BTN_SURRENDER),
    (Screen.BB_BATTLE, N.BB_BTN_END_BATTLE),
    (Screen.BB_HOME, N.BB_ATTACK),
    (Screen.BB_SEARCHING, N.BB_SEARCHING),
    (Screen.HOME, N.HOME_ATTACK),
)


def _detect(image: np.ndarray, templates: TemplateFinder,
            markers: tuple[tuple[Screen, str], ...]) -> Screen:
    for name in N.POPUP_TEMPLATES:
        if templates.find(image, name) is not None:
            return Screen.POPUP
    for screen, name in markers:
        if templates.find(image, name) is not None:
            return screen
    return Screen.UNKNOWN


def detect_screen(image: np.ndarray, templates: TemplateFinder) -> Screen:
    return _detect(image, templates, SCREEN_MARKERS)


def detect_builder_screen(image: np.ndarray, templates: TemplateFinder) -> Screen:
    return _detect(image, templates, BUILDER_MARKERS)
```

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all pass (the calibration-page TUI test still sees more rows with "show all", since `valid_names` grew).

- [ ] **Step 6: Commit (ask the user first)**

```bash
git add coc_bot/names.py coc_bot/vision/screens.py tests/test_builder_names.py
git commit -m "feat: Builder Base screens, names and calibration checks"
```

---

### Task 4: `BuilderGame` actions

**Files:**
- Create: `coc_bot/game/builder.py`
- Test: `tests/test_builder_game.py` (new)

**Interfaces:**
- Consumes: names from Task 3, `BuilderConfig` from Task 2, `Game` primitives (`tap`, `tap_template`, `wait_for`, `_image`, `go_back`, `dismiss_popup`, `restart_game`, `reconnect`, `save_debug_screenshot`).
- Produces: `coc_bot.game.builder.BuilderGame(Game)` with
  `screen() -> Screen`, `go_to_builder_base() -> bool`, `open_attack() -> bool`, `drop_one_troop() -> bool`,
  `deploy_stage(stage: int) -> None`, `hero_ability() -> None`, `troop_abilities() -> None`,
  `surrender() -> bool`, `read_damage() -> int | None`, `read_result_gold() -> int | None`,
  `return_home() -> bool`, `collect_cart() -> bool`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_builder_game.py`:

```python
import random
from dataclasses import replace

from coc_bot import names as N
from coc_bot.config import BuilderConfig, Calibration, Settings
from coc_bot.game.builder import BuilderGame
from coc_bot.vision.screens import Screen
from tests.fakes import FakeAdb, FakeOcr, FakeTemplates

POINTS = {
    N.BB_DEPLOY_STAGE1: (300, 300), N.BB_DEPLOY_STAGE2: (900, 300),
    **{N.bb_slot(i): (100 * i, 680) for i in range(1, 9)},
}
DAMAGE_ROI = (1100, 520, 120, 40)
GOLD_ROI = (600, 300, 200, 40)


def make(visible=(), ocr=None, **builder):
    cal = Calibration(points=dict(POINTS), rois={N.ROI_BB_DAMAGE: DAMAGE_ROI, N.ROI_BB_RESULT_GOLD: GOLD_ROI})
    settings = replace(Settings(calibration=cal), builder=BuilderConfig(**builder))
    settings = replace(settings, timing=replace(settings.timing, tap_jitter_px=0))
    adb = FakeAdb()
    game = BuilderGame(adb, FakeTemplates(visible), FakeOcr(ocr or {}), settings, random.Random(0),
                       sleep=lambda s: None)
    return game, adb


def near(tap, point, px=12):
    return abs(tap[0] - point[0]) <= px and abs(tap[1] - point[1]) <= px


def test_screen_uses_builder_markers():
    game, _ = make(visible={N.BB_ATTACK})
    assert game.screen() is Screen.BB_HOME


def test_go_to_builder_base_taps_boat():
    game, adb = make(visible={N.BB_BOAT})
    assert game.go_to_builder_base() is True
    assert adb.taps() == [(105, 105)]


def test_go_to_builder_base_fails_without_boat():
    game, adb = make()
    assert game.go_to_builder_base() is False
    assert adb.taps() == []


def test_open_attack_taps_attack_then_find_now():
    game, adb = make(visible={N.BB_ATTACK, N.BB_BTN_FIND_NOW})
    assert game.open_attack() is True
    assert len(adb.taps()) == 2


def test_drop_one_troop_taps_card_then_stage1_point():
    game, adb = make(troop_slot=2)
    assert game.drop_one_troop() is True
    taps = adb.taps()
    assert taps[0] == POINTS[N.bb_slot(2)]
    assert near(taps[1], POINTS[N.BB_DEPLOY_STAGE1]) and len(taps) == 2


def test_deploy_stage1_order_hero_tank_witches():
    game, adb = make(mode="gold", hero_slot=1, tank_slot=2, main_slots=(3, 4), taps_per_slot=2)
    game.deploy_stage(1)
    cards = [t for t in adb.taps() if t[1] == 680]
    assert cards == [POINTS[N.bb_slot(i)] for i in (1, 2, 3, 4)]
    drops = [t for t in adb.taps() if t[1] != 680]
    assert len(drops) == 1 + 2 + 2 + 2
    assert all(near(t, POINTS[N.BB_DEPLOY_STAGE1]) for t in drops)


def test_deploy_stage2_uses_stage2_point_and_extra_slots():
    game, adb = make(mode="gold", hero_slot=1, tank_slot=0, main_slots=(3,), stage2_slots=(6,),
                     taps_per_slot=1)
    game.deploy_stage(2)
    cards = [t for t in adb.taps() if t[1] == 680]
    assert cards == [POINTS[N.bb_slot(i)] for i in (1, 3, 6)]
    assert all(near(t, POINTS[N.BB_DEPLOY_STAGE2]) for t in adb.taps() if t[1] != 680)


def test_hero_and_troop_abilities_tap_cards():
    game, adb = make(mode="gold", hero_slot=1, main_slots=(3, 4))
    game.hero_ability()
    game.troop_abilities()
    assert adb.taps() == [POINTS[N.bb_slot(1)], POINTS[N.bb_slot(3)], POINTS[N.bb_slot(4)]]


def test_surrender_confirms_okay():
    game, adb = make(visible={N.BB_BTN_SURRENDER, N.POPUP_OKAY})
    assert game.surrender() is True
    assert len(adb.taps()) == 2


def test_surrender_falls_back_to_end_battle():
    game, adb = make(visible={N.BB_BTN_END_BATTLE})
    assert game.surrender() is True


def test_read_damage_and_gold():
    game, _ = make(ocr={DAMAGE_ROI: 134, GOLD_ROI: 98000})
    assert game.read_damage() == 134
    assert game.read_result_gold() == 98000


def test_collect_cart_taps_cart_collect_and_closes():
    game, adb = make(visible={N.BB_ELIXIR_CART, N.BB_BTN_COLLECT, N.POPUP_CLOSE})
    assert game.collect_cart() is True
    assert len(adb.taps()) == 3   # cart, collect, close
    assert ("back",) not in adb.calls


def test_collect_cart_without_window_backs_out():
    game, adb = make(visible={N.BB_ELIXIR_CART})
    assert game.collect_cart() is False
    assert ("back",) in adb.calls
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_builder_game.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'coc_bot.game.builder'`

- [ ] **Step 3: Create `coc_bot/game/builder.py`**

```python
"""Builder Base (desa malam) actions on top of the shared Game primitives."""
from __future__ import annotations

import logging

from coc_bot import names as N
from coc_bot.config import Point
from coc_bot.game.actions import Game
from coc_bot.vision.screens import Screen, detect_builder_screen

log = logging.getLogger(__name__)

DROP_SPREAD_PX = 12   # one deploy point, but not the same pixel every tap


class BuilderGame(Game):
    def screen(self) -> Screen:
        return detect_builder_screen(self.capture(), self.templates)

    # --- helpers ------------------------------------------------------------
    def _point(self, name: str) -> Point | None:
        return self.settings.calibration.points.get(name)

    def _spread(self, pt: Point) -> Point:
        s = DROP_SPREAD_PX
        return (pt[0] + self.rng.randint(-s, s), pt[1] + self.rng.randint(-s, s))

    def _drop(self, slot: int, target: Point, taps: int) -> bool:
        card = self._point(N.bb_slot(slot))
        if card is None:
            log.warning("Card bb_slot_%d is not calibrated, skipped", slot)
            return False
        self.tap(card)
        for _ in range(taps):
            self.tap(self._spread(target))
        return True

    def _tap_card(self, slot: int) -> None:
        card = self._point(N.bb_slot(slot))
        if card is not None:
            self.tap(card)

    # --- village / search -----------------------------------------------------
    def go_to_builder_base(self) -> bool:
        if not self.tap_template(N.BB_BOAT):
            return False
        self.sleep(6.0)   # sailing + loading
        return True

    def open_attack(self) -> bool:
        if not self.tap_template(N.BB_ATTACK, fresh=False):
            return False
        if not self.wait_for(N.BB_BTN_FIND_NOW, timeout_s=4.0):
            log.warning("Find Now did not appear after tapping Attack")
            return False
        return self.tap_template(N.BB_BTN_FIND_NOW, fresh=False)

    # --- deploy ---------------------------------------------------------------
    def drop_one_troop(self) -> bool:
        target = self._point(N.BB_DEPLOY_STAGE1)
        if target is None:
            return False
        return self._drop(self.settings.builder.troop_slot, target, taps=1)

    def deploy_stage(self, stage: int) -> None:
        b = self.settings.builder
        target = self._point(N.BB_DEPLOY_STAGE1 if stage == 1 else N.BB_DEPLOY_STAGE2)
        if target is None:
            log.warning("Deploy point for stage %d is not calibrated", stage)
            return
        self._drop(b.hero_slot, target, taps=1)
        self.sleep(1.0)
        if b.tank_slot > 0:
            self._drop(b.tank_slot, target, b.taps_per_slot)
            self.sleep(b.witch_delay_s)
        for slot in b.main_slots + (b.stage2_slots if stage == 2 else ()):
            self._drop(slot, target, b.taps_per_slot)

    def hero_ability(self) -> None:
        """Tap the hero card: fires the ability when charged, does nothing otherwise."""
        self._tap_card(self.settings.builder.hero_slot)

    def troop_abilities(self) -> None:
        """Tap the deployed Night Witch cards once (Bat Swarm)."""
        for slot in self.settings.builder.main_slots:
            self._tap_card(slot)

    # --- battle ---------------------------------------------------------------
    def surrender(self) -> bool:
        """Surrender / End Battle (also ends the battle on the stage-2 screen) and confirm."""
        tapped = (self.tap_template(N.BB_BTN_SURRENDER)
                  or self.tap_template(N.BB_BTN_END_BATTLE, fresh=False))
        if tapped and self.wait_for(N.POPUP_OKAY, timeout_s=3.0):
            self.tap_template(N.POPUP_OKAY, fresh=False)
        return tapped

    def read_damage(self) -> int | None:
        roi = self.settings.calibration.rois.get(N.ROI_BB_DAMAGE)
        if roi is None:
            return None
        return self.ocr.read_number(self._image(fresh=True), roi, N.MAX_BB_DAMAGE)

    def read_result_gold(self) -> int | None:
        roi = self.settings.calibration.rois.get(N.ROI_BB_RESULT_GOLD)
        if roi is None:
            return None
        return self.ocr.read_number(self._image(fresh=False), roi, N.MAX_BB_GOLD)

    def return_home(self) -> bool:
        return self.tap_template(N.BB_BTN_RETURN_HOME, fresh=False)

    # --- Elixir Cart ------------------------------------------------------------
    def collect_cart(self) -> bool:
        if not self.tap_template(N.BB_ELIXIR_CART, fresh=False):
            return False
        if not self.wait_for(N.BB_BTN_COLLECT, timeout_s=3.0):
            self.go_back()
            return False
        self.tap_template(N.BB_BTN_COLLECT, fresh=False)
        self.sleep(1.0)
        if not self.tap_template(N.POPUP_CLOSE):   # close the cart window
            self.go_back()
        return True
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit (ask the user first)**

```bash
git add coc_bot/game/builder.py tests/test_builder_game.py
git commit -m "feat: Builder Base game actions (boat, one-point deploy, surrender, Elixir Cart)"
```

---

### Task 5: `BuilderFarmTask` — village, cart and elixir mode

**Files:**
- Create: `coc_bot/bot/builder_task.py`
- Modify: `coc_bot/bot/records.py`, `tests/fakes.py`
- Test: `tests/test_builder_task.py` (new)

**Interfaces:**
- Consumes: `ScreenLoop` (Task 1), `BuilderConfig` (Task 2), `Screen.BB_*` (Task 3), `BuilderGame` method names (Task 4).
- Produces:
  - `coc_bot.bot.builder_task.BuilderFarmTask(mode: str | None = None, recorder=None)`; attribute `mode` resolved at `bind`.
  - `coc_bot.bot.records.CsvRecorder(directory, prefix="attacks", fields=FIELDS)`; `coc_bot.bot.records.BUILDER_FIELDS`.
  - `tests.fakes.FakeBuilderGame(screens)`.

- [ ] **Step 1: Add `FakeBuilderGame` to `tests/fakes.py`** (append at the end)

```python
class FakeBuilderGame(FakeGame):
    ACTIONS = {"go_to_builder_base", "open_attack", "drop_one_troop", "surrender", "return_home",
               "collect_cart", "dismiss_popup", "go_back", "reconnect", "hero_ability",
               "troop_abilities"}

    def __init__(self, screens):
        super().__init__(screens)
        self.damage = []          # values returned by read_damage, one per call (last one repeats)
        self.result_gold = None
        self.stages = []

    def deploy_stage(self, stage):
        self.calls.append("deploy_stage")
        self.stages.append(stage)

    def read_damage(self):
        if not self.damage:
            return None
        return self.damage.pop(0) if len(self.damage) > 1 else self.damage[0]

    def read_result_gold(self):
        return self.result_gold

    def __getattr__(self, name):
        if name in FakeBuilderGame.ACTIONS:
            return lambda: (self.calls.append(name), name not in self.failing)[1]
        raise AttributeError(name)
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_builder_task.py`:

```python
import random
from dataclasses import replace

import pytest

from coc_bot.bot.builder_task import BuilderFarmTask
from coc_bot.bot.engine import FatalError, ScreenLoop
from coc_bot.config import BuilderConfig
from coc_bot.vision.screens import Screen
from tests.fakes import FakeBuilderGame, FakeClock, FakePolicy, make_settings


def make(screens, mode="elixir", recorder=None, policy=None, **builder):
    settings = replace(make_settings(), builder=BuilderConfig(mode=mode, **builder))
    clock = FakeClock()
    game = FakeBuilderGame(screens)
    task = BuilderFarmTask(recorder=recorder)
    loop = ScreenLoop(game, task, policy or FakePolicy(), settings, random.Random(0),
                      clock=clock.now, sleep=clock.sleep)
    return loop, game, task, clock


def test_mode_comes_from_settings_or_override():
    loop, _, task, _ = make([Screen.BB_HOME], mode="gold")
    assert task.mode == "gold"
    settings = replace(make_settings(), builder=BuilderConfig(mode="gold"))
    override = BuilderFarmTask(mode="elixir")
    ScreenLoop(FakeBuilderGame([Screen.BB_HOME]), override, FakePolicy(), settings, random.Random(0),
               clock=FakeClock().now, sleep=FakeClock().sleep)
    assert override.mode == "elixir"


def test_unknown_override_rejected():
    with pytest.raises(ValueError):
        ScreenLoop(FakeBuilderGame([Screen.BB_HOME]), BuilderFarmTask(mode="dark"), FakePolicy(),
                   make_settings(), random.Random(0), clock=FakeClock().now, sleep=FakeClock().sleep)


def test_home_village_takes_the_boat():
    loop, game, _, _ = make([Screen.HOME])
    loop.tick()
    assert game.count("go_to_builder_base") == 1


def test_missing_boat_is_fatal_after_three_tries():
    loop, game, _, _ = make([Screen.HOME])
    game.failing.add("go_to_builder_base")
    loop.tick()
    loop.tick()
    with pytest.raises(FatalError, match="bb_boat"):
        loop.tick()


def test_first_builder_home_collects_cart_then_attacks():
    loop, game, _, _ = make([Screen.BB_HOME])
    loop.tick()
    assert game.count("collect_cart") == 1 and game.count("open_attack") == 0
    assert loop.stats.carts == 1
    loop.tick()
    assert game.count("open_attack") == 1


def test_elixir_prep_drops_one_troop_and_surrenders():
    loop, game, _, _ = make([Screen.BB_PREP])
    loop.tick()
    assert game.calls == ["drop_one_troop", "surrender"]
    assert loop.stats.attacks == 1


def test_elixir_battle_surrenders_again():
    loop, game, _, _ = make([Screen.BB_BATTLE])
    loop.tick()
    assert game.count("surrender") == 1


def test_cart_collected_every_n_attacks():
    loop, game, task, _ = make([Screen.BB_HOME], cart_every=3)
    loop.tick()                       # first visit: collect
    for _ in range(3):
        task._on_prep(loop.clock())   # three attacks
    loop.tick()
    assert game.count("collect_cart") == 2
    loop.tick()
    assert game.count("open_attack") == 1


def test_failed_cart_retried_after_next_attack():
    loop, game, task, _ = make([Screen.BB_HOME], cart_every=3)
    game.failing.add("collect_cart")
    loop.tick()
    assert loop.stats.carts == 0
    loop.tick()
    assert game.count("open_attack") == 1      # no retry before the next attack
    task._on_prep(loop.clock())
    game.failing.clear()
    loop.tick()
    assert game.count("collect_cart") == 2 and loop.stats.carts == 1


def test_result_records_and_returns_home():
    rows = []
    loop, game, task, _ = make([Screen.BB_RESULT], recorder=rows.append)
    game.result_gold = 1234
    task._on_prep(loop.clock())
    loop.tick()
    assert game.count("return_home") == 1
    assert rows[0]["mode"] == "elixir" and rows[0]["gold"] == 1234 and rows[0]["stage2"] is False


def test_rest_on_builder_home():
    policy = FakePolicy(rest=True, rest_s=600)
    loop, game, _, clock = make([Screen.BB_HOME], policy=policy)
    loop.tick()
    assert clock.slept == [600]
    assert game.count("collect_cart") == 0


def test_restart_lands_on_home_and_boats_back():
    loop, game, _, _ = make([Screen.UNKNOWN])
    game.on_restart = lambda: game.screens.__setitem__(slice(None), [Screen.HOME])
    loop._recover_level = 1          # skip Back, go straight to a restart
    loop._recover(Screen.UNKNOWN)
    loop.tick()
    assert game.count("restart_game") == 1 and game.count("go_to_builder_base") == 1
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_builder_task.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'coc_bot.bot.builder_task'`

- [ ] **Step 4: Generalise `coc_bot/bot/records.py`**

Replace the `CsvRecorder` class and add `BUILDER_FIELDS`:

```python
BUILDER_FIELDS = ("time", "mode", "cycle_s", "battle_s", "damage_pct", "gold", "stage2")


class CsvRecorder:
    def __init__(self, directory: Path, prefix: str = "attacks", fields: tuple[str, ...] = FIELDS) -> None:
        self.directory = directory
        self.prefix = prefix
        self.fields = fields

    def __call__(self, row: dict) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = row["time"] if isinstance(row["time"], datetime) else datetime.now()
        path = self.directory / f"{self.prefix}-{stamp:%Y-%m-%d}.csv"
        new_file = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=self.fields)
            if new_file:
                writer.writeheader()
            writer.writerow({k: _fmt(row.get(k)) for k in self.fields})
```

Update the module docstring to: `"""Per-attack CSV logs (logs/attacks-*.csv for the home village, logs/builder-*.csv for the Builder Base)."""`

- [ ] **Step 5: Create `coc_bot/bot/builder_task.py`** (elixir mode + shared handlers; the gold battle handler is completed in Task 6)

```python
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
        self.sleep(2.0)   # replaced in Task 6

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
```

- [ ] **Step 6: Run the tests**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all pass. (`test_records.py` still passes: `CsvRecorder(directory)` keeps the old defaults.)

- [ ] **Step 7: Commit (ask the user first)**

```bash
git add coc_bot/bot/builder_task.py coc_bot/bot/records.py tests/fakes.py tests/test_builder_task.py
git commit -m "feat: Builder Base farming task with elixir mode and Elixir Cart collection"
```

---

### Task 6: Gold mode battle (hero ability, Bat Swarm, stagnation, stage 2)

**Files:**
- Modify: `coc_bot/bot/builder_task.py` (`_gold_battle`)
- Test: `tests/test_builder_task.py` (append)

**Interfaces:**
- Consumes: everything from Task 5; `BuilderConfig.ability_every_s`, `bat_swarm_after_s`, `damage_stagnant_s`, `battle_timeout_s`, `stage2`.
- Produces: final `BuilderFarmTask._gold_battle(now)` behaviour.

- [ ] **Step 1: Append the failing tests to `tests/test_builder_task.py`**

```python
def gold(screens, **kw):
    return make(screens, mode="gold", **kw)


def test_gold_prep_deploys_stage1():
    loop, game, task, _ = gold([Screen.BB_PREP])
    loop.tick()
    assert game.stages == [1] and game.count("surrender") == 0
    assert loop.stats.attacks == 1


def test_gold_battle_fires_hero_ability_on_interval():
    loop, game, task, clock = gold([Screen.BB_BATTLE], ability_every_s=3.0)
    task._start_stage(1)
    loop.tick()                 # t=0: first ability tap
    loop.tick()                 # t=2: too soon
    loop.tick()                 # t=4: again
    assert game.count("hero_ability") == 2


def test_gold_battle_bat_swarm_once():
    loop, game, task, _ = gold([Screen.BB_BATTLE], bat_swarm_after_s=3.0)
    task._start_stage(1)
    for _ in range(5):
        loop.tick()
    assert game.count("troop_abilities") == 1


def test_gold_battle_ends_on_stagnant_damage():
    loop, game, task, _ = gold([Screen.BB_BATTLE], damage_stagnant_s=6.0)
    game.damage = [10, 20, 30]  # then stays at 30
    task._start_stage(1)
    for _ in range(4):
        loop.tick()             # t=0..6, damage rises until t=4
    assert game.count("surrender") == 0
    for _ in range(4):
        loop.tick()             # t=8..14, 30% for > 6 s
    assert game.count("surrender") >= 1
    assert task._last_damage == 30


def test_gold_battle_without_damage_reading_waits_for_timeout():
    loop, game, task, _ = gold([Screen.BB_BATTLE], battle_timeout_s=20, damage_stagnant_s=4.0)
    task._start_stage(1)
    for _ in range(10):         # t=0..18
        loop.tick()
    assert game.count("surrender") == 0
    loop.tick()                 # t=20
    assert game.count("surrender") == 1


def test_stage2_prep_deploys_stage2():
    loop, game, task, _ = gold([Screen.BB_STAGE2_PREP])
    loop.tick()
    assert game.stages == [2] and loop.stats.stage2 == 1


def test_stage2_off_ends_battle():
    loop, game, task, _ = gold([Screen.BB_STAGE2_PREP], stage2=False)
    loop.tick()
    assert game.stages == [] and game.count("surrender") == 1


def test_stage2_recorded_in_result():
    rows = []
    loop, game, task, _ = gold([Screen.BB_RESULT], recorder=rows.append)
    task._on_prep(loop.clock())
    task._on_stage2_prep(loop.clock())
    loop.tick()
    assert rows[0]["stage2"] is True and rows[0]["mode"] == "gold"


def test_gold_battle_overrun_triggers_recovery():
    loop, game, task, clock = gold([Screen.BB_BATTLE], battle_timeout_s=10)
    task._start_stage(1)
    clock.sleep(10 + 121)
    loop.tick()
    assert game.count("go_back") == 1 and loop.stats.recoveries == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_builder_task.py -q`
Expected: FAIL in `test_gold_battle_fires_hero_ability_on_interval` (hero_ability count 0) and the stagnation/timeout tests.

- [ ] **Step 3: Replace `_gold_battle` in `coc_bot/bot/builder_task.py`**

```python
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
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit (ask the user first)**

```bash
git add coc_bot/bot/builder_task.py tests/test_builder_task.py
git commit -m "feat: gold mode battle with hero ability, Bat Swarm, stagnation and stage 2"
```

---

### Task 7: Wire builder mode into control, CLI, dashboard and docs

**Files:**
- Modify: `coc_bot/control.py`, `coc_bot/main.py`, `coc_bot/tui/app.py`, `coc_bot/tui/pages.py`, `coc_bot/tui/info.py`, `README.md`, `docs/ROADMAP.md`, `docs/superpowers/specs/2026-11-14-builder-base-farm-design.md` (status line only)
- Test: `tests/test_control.py`, `tests/test_cli.py` (append), `tests/test_tui.py` (append)

**Interfaces:**
- Consumes: `ScreenLoop`, `HomeFarmTask`, `BuilderFarmTask`, `BuilderGame`, `CsvRecorder(prefix, fields)`, `BUILDER_FIELDS`, `N.missing_for_mode`, `N.relevant_for_mode`.
- Produces: `BotRunner(paths=None, mode=Mode.HOME, builder_mode: str | None = None)`, `Status.builder_mode`, `control.mode_label(mode, builder_mode) -> str`, `DashboardApp.set_mode(mode, builder_mode=None)`, `gather(paths, probe_emulator=True, mode="home")`, CLI `run --builder-mode {elixir,gold}` and `check --mode {home,builder,...}`.

- [ ] **Step 1: Update and add the control tests**

In `tests/test_control.py`, change `test_unavailable_mode_fails_without_touching_adb` to use `Mode.WALLS` and assert `"walls"` in the error; append:

```python
def test_builder_mode_checks_builder_calibration(tmp_path):
    runner = BotRunner(tmp_paths(tmp_path), Mode.BUILDER)
    assert runner.run() == 2
    error = runner.status().error
    assert "template:bb_boat" in error and "template:btn_next" not in error


def test_builder_sub_mode_label(tmp_path):
    from coc_bot.control import mode_label
    runner = BotRunner(tmp_paths(tmp_path), Mode.BUILDER, builder_mode="gold")
    assert runner.status().builder_mode == "gold"
    assert mode_label(Mode.BUILDER, "gold") == "builder (gold)"
    assert mode_label(Mode.HOME, "gold") == "home"
```

Append to `tests/test_cli.py` (uses the file's existing `base_args` helper):

```python
def test_check_builder_mode_lists_builder_items(tmp_path, capsys):
    assert main(base_args(tmp_path) + ["check", "--mode", "builder"]) == 2
    out = capsys.readouterr().out
    assert "template:bb_boat" in out
    assert "template:btn_next" not in out
```

Append to `tests/test_tui.py`:

```python
def test_mode_page_offers_builder_sub_modes(tmp_path):
    async def go():
        app = make_app(tmp_path)
        async with app.run_test(size=(130, 40)) as pilot:
            await pilot.press("3")
            await pilot.pause(0.3)
            mode_list = app.query_one("#mode-list")
            ids = [mode_list.get_option_at_index(i).id for i in range(mode_list.option_count)]
            assert "builder:elixir" in ids and "builder:gold" in ids
            app.set_mode(Mode.BUILDER, "gold")
            assert app.runner.mode is Mode.BUILDER and app.runner.builder_mode == "gold"
    asyncio.run(go())
```

and add `Mode` to the `from coc_bot.control import ...` line in `tests/test_tui.py`.

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_control.py tests/test_cli.py tests/test_tui.py -q`
Expected: FAIL (`builder_mode` unexpected keyword, `mode_label` missing, unknown `--mode` for check, no builder options).

- [ ] **Step 3: Update `coc_bot/control.py`**

Imports: replace `from coc_bot.bot.state_machine import Bot, FatalError, Stats` with

```python
from coc_bot.bot.engine import FatalError, ScreenLoop, Stats
from coc_bot.bot.home_task import HomeFarmTask
from coc_bot.bot.records import BUILDER_FIELDS, CsvRecorder
```

(and drop the separate `from coc_bot.bot.records import CsvRecorder` line).

Replace the `Mode` docstring and `MODE_INFO`:

```python
class Mode(str, Enum):
    """What the bot does when started."""
    HOME = "home"
    BUILDER = "builder"
    WALLS = "walls"
    AUTO = "auto"


MODE_INFO: dict[Mode, tuple[str, bool]] = {   # mode -> (description, available)
    Mode.HOME: ("Farm desa siang terus-menerus (E-Drag, spell, cek storage)", True),
    Mode.BUILDER: ("Farm desa malam: elixir (1 troop + menyerah) / gold (Copter + Night Witch)", True),
    Mode.WALLS: ("Habiskan resource ke wall lalu selesai", False),
    Mode.AUTO: ("Semua tugas lewat penjadwal", False),
}
BUILDER_SUB_MODES: dict[str, str] = {
    "elixir": "1 troop lalu menyerah, klaim Elixir Cart tiap N serangan (trofi turun)",
    "gold": "Copter + Giant + Night Witch di satu titik, serang tahap 2",
}


def mode_label(mode: Mode, builder_mode: str | None) -> str:
    if mode is Mode.BUILDER and builder_mode:
        return f"{mode.value} ({builder_mode})"
    return mode.value
```

Add `builder_mode: str | None = None` to `Status` (after `error`).

`BotRunner.__init__`: new signature `def __init__(self, paths: Paths | None = None, mode: Mode = Mode.HOME, builder_mode: str | None = None) -> None:`, store `self.builder_mode = builder_mode`, and type `self._bot: ScreenLoop | None = None`.

`status()`: pass `builder_mode=self.builder_mode` as a keyword to `Status(...)`.

In `run()`, replace the block from `if self.mode is not Mode.HOME:` through `self._bot.check_storage = self.check_storage` with:

```python
            if self.mode not in (Mode.HOME, Mode.BUILDER):
                return self._fail(f"Mode '{self.mode.value}' belum tersedia", 2)
            settings = load_settings(self.paths.settings, self.paths.calibration)
            templates = load_templates(self.paths, settings)
            missing = N.missing_for_mode(settings, set(templates.names()), self.mode.value)
            if missing:
                return self._fail("Calibration incomplete, missing: " + ", ".join(missing), 2)
            adb = connect(settings)
            shape = adb.screencap().shape[:2]
            if shape != EXPECTED_SHAPE:
                return self._fail(f"Emulator resolution must be 1280x720, got {shape[1]}x{shape[0]}", 2)
            if self._stop.is_set():
                return 0
            rng = random.Random()
            ocr = OcrReader(rapidocr_engine())
            if self.mode is Mode.BUILDER:
                from coc_bot.bot.builder_task import BuilderFarmTask
                from coc_bot.game.builder import BuilderGame
                game = BuilderGame(adb, templates, ocr, settings, rng, sleep=self._sleep)
                task = BuilderFarmTask(self.builder_mode,
                                       CsvRecorder(self.paths.logs, "builder", BUILDER_FIELDS))
            else:
                game = Game(adb, templates, ocr, settings, rng, sleep=self._sleep)
                task = HomeFarmTask(CsvRecorder(self.paths.logs))
            self._bot = ScreenLoop(game, task, SessionPolicy(settings.session, rng), settings, rng,
                                   clock=datetime.now, sleep=self._sleep)
            self._bot.check_storage = self.check_storage
```

- [ ] **Step 4: Update `coc_bot/main.py`**

In `build_parser`:

```python
    run = sub.add_parser("run", help="run the bot (Ctrl+C to stop)")
    run.add_argument("--mode", choices=[m.value for m in Mode], default=Mode.HOME.value)
    run.add_argument("--builder-mode", choices=list(BUILDER_MODES), default=None,
                     help="Builder Base sub-mode (default: [builder] mode in settings.toml)")
    check = sub.add_parser("check", help="list missing calibration items")
    check.add_argument("--mode", choices=[m.value for m in Mode], default=Mode.HOME.value)
```

(replacing the old `run`/`check` lines) and add `from coc_bot.config import BUILDER_MODES` to the imports (merge with the existing `coc_bot.config` import if there is one).

`cmd_check`: `missing = N.missing_for_mode(settings, set(_templates(args, settings).names()), getattr(args, "mode", "home"))`.

`cmd_run`: use `N.missing_for_mode(..., args.mode)` for the pre-check, and build the runner with
`BotRunner(_paths(args), Mode(args.mode), getattr(args, "builder_mode", None))`.

- [ ] **Step 5: Update the dashboard**

`coc_bot/tui/app.py`:
- import `mode_label` from `coc_bot.control`.
- `set_mode`:

```python
    def set_mode(self, mode: Mode, builder_mode: str | None = None) -> None:
        self.mode = mode
        self.runner.mode = mode
        self.runner.builder_mode = builder_mode if mode is Mode.BUILDER else None
        self._tick()
```

- Replace the three displays of `self.mode.value` / `status.mode.value` (start notification, status bar, sidebar) with `mode_label(self.mode, self.runner.builder_mode)` / `mode_label(status.mode, status.builder_mode)`.

`coc_bot/tui/pages.py`:
- import `BUILDER_SUB_MODES, mode_label` from `coc_bot.control`.
- `ModePage.compose` loop becomes:

```python
        for mode, (desc, available) in MODE_INFO.items():
            if mode is Mode.BUILDER:
                for sub, sub_desc in BUILDER_SUB_MODES.items():
                    prompt = Text.assemble((f"{'builder ' + sub:<15}", "bold"), ("  " + sub_desc, ""))
                    options.append(Option(prompt, id=f"builder:{sub}"))
                continue
            prompt = Text.assemble((f"{mode.value:<15}", "bold"), ("  " + desc, "" if available else "dim"),
                                   ("" if available else "  (segera)", "italic dim"))
            options.append(Option(prompt, id=mode.value, disabled=not available))
```

- `on_option_list_option_selected`:

```python
        value, _, sub = event.option.id.partition(":")
        mode = Mode(value)
        if self.dash.runner.active:
            self.app.notify("Hentikan bot dulu untuk ganti mode.", severity="warning")
            return
        self.dash.set_mode(mode, sub or None)
        self.app.notify(f"Mode: {mode_label(mode, sub or None)}")
```

- `HomePage.load_info`: `gather(self.dash.paths, self.dash.probe_emulator, self.dash.mode.value)`.
- `render_info` / `_show_info`: pass and show `mode_label(self.dash.mode, self.dash.runner.builder_mode)` instead of `mode.value` (change the parameter to `mode_text: str`).
- `BotPage.update_status`: `table.add_row("Mode", mode_label(status.mode, status.builder_mode))`; add rows `table.add_row("Cart diklaim", str(status.stats.carts))` and `table.add_row("Tahap 2", str(status.stats.stage2))` when `status.mode is Mode.BUILDER`.
- `CalibrationPage.refresh_page`: `mode = self.dash.mode.value`; use `N.missing_for_mode(settings, set(templates.names()), mode)` and `N.relevant_for_mode(settings, mode)`.

`coc_bot/tui/info.py`: `def gather(paths: Paths, probe_emulator: bool = True, mode: str = "home") -> SystemInfo:` and `info.missing = N.missing_for_mode(settings, set(templates.names()), mode)`.

- [ ] **Step 6: Run the whole suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all pass.

- [ ] **Step 7: Docs**

- `README.md`: add a short "Desa malam (Builder Base)" section: `python -m coc_bot run --mode builder --builder-mode elixir|gold`, the `[builder]` keys, the calibration items from `python -m coc_bot check --mode builder`, and the trophy note for elixir mode.
- `docs/ROADMAP.md` section 4: mark ✅ first version (2026-11-14) with a one-line summary; tick "Aturan loot BB" with the research result (no daily cap; Star Bonus 7–12 stars, 22 h).
- Spec status line: `Status: diimplementasikan (rencana docs/superpowers/plans/2026-11-14-builder-base-farm.md)`.

- [ ] **Step 8: Commit (ask the user first)**

```bash
git add coc_bot/control.py coc_bot/main.py coc_bot/tui/app.py coc_bot/tui/pages.py coc_bot/tui/info.py tests/test_control.py tests/test_cli.py tests/test_tui.py README.md docs/superpowers/specs/2026-11-14-builder-base-farm-design.md
git commit -m "feat: builder run mode in the CLI and dashboard"
```

(`docs/ROADMAP.md` is local-only and stays uncommitted.)

---

### Task 8: In-game calibration and smoke test (with the user)

Not code — needs the user's LDPlayer with the Builder Base open. Do it together after Task 7.

- [ ] **Step 1:** User puts Battle Copter + Giant + Night Witches in the Builder Base army (gold) and notes the card order.
- [ ] **Step 2:** For each item from `python -m coc_bot check --mode builder`, open the screen in game and run `python -m coc_bot calibrate <kind> <name>` (or the dashboard Calibration page in builder mode). Screens needed: home village (boat), Builder Base home (attack button, Elixir Cart), attack panel (Find Now), stage-1 prep (banner, card slots, deploy point), battle (surrender, damage %), stage-2 prep (marker, deploy point), result (return home, gold), cart window (collect, close X).
- [ ] **Step 3:** `python -m coc_bot test-vision <screenshot>` on each saved screen to confirm the builder screen is detected (add `detect_builder_screen` output to `cmd_test_vision` only if the report shows the wrong screen — otherwise skip).
- [ ] **Step 4:** Run `python -m coc_bot run --mode builder --builder-mode elixir` for ~5 attacks with `cart_every = 2`; watch logs for: boat → attack → surrender → result → cart collected.
- [ ] **Step 5:** Run gold mode for ~3 attacks; check deploy at one point, hero ability taps, stage-2 handling, `logs/builder-*.csv` rows.
- [ ] **Step 6:** Fix what the real game shows differently (e.g. cart window closing, prep marker) as small follow-up commits, each approved by the user.
