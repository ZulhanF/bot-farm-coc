"""Run and control the bot from outside its loop (CLI, terminal dashboard, later a web UI).

`BotRunner.run()` blocks; `start()` runs it on a background thread. `pause()`, `resume()` and `stop()`
are safe to call from any thread: the bot only ever waits through `_sleep`, which wakes up at once on
stop and blocks while paused.
"""
from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

from coc_bot import names as N
from coc_bot.bot.records import CsvRecorder
from coc_bot.bot.session import SessionPolicy
from coc_bot.bot.state_machine import Bot, FatalError, Stats
from coc_bot.config import Settings, load_settings
from coc_bot.device.adb import AdbError, EmulatorAdb, find_adb
from coc_bot.vision.templates import TemplateLibrary

log = logging.getLogger("coc_bot")
EXPECTED_SHAPE = (720, 1280)


class Mode(str, Enum):
    """What the bot does when started. Only `home` exists so far; the rest are on the roadmap."""
    HOME = "home"
    BUILDER = "builder"
    WALLS = "walls"
    AUTO = "auto"


MODE_INFO: dict[Mode, tuple[str, bool]] = {   # mode -> (description, available)
    Mode.HOME: ("Farm desa siang terus-menerus (E-Drag, spell, cek storage)", True),
    Mode.BUILDER: ("Farm desa malam (Night Witch + Battle Copter)", False),
    Mode.WALLS: ("Habiskan resource ke wall lalu selesai", False),
    Mode.AUTO: ("Semua tugas lewat penjadwal", False),
}


class State(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class Paths:
    settings: Path = Path("settings.toml")
    calibration: Path = Path("calibration.toml")
    templates: Path = Path("assets/templates")
    logs: Path = Path("logs")


@dataclass
class Status:
    state: State
    mode: Mode
    screen: str | None = None
    started_at: datetime | None = None
    stats: Stats = field(default_factory=Stats)
    error: str | None = None


def load_templates(paths: Paths, settings: Settings) -> TemplateLibrary:
    return TemplateLibrary.load(paths.templates, settings.calibration.templates,
                                settings.vision.threshold, settings.vision.search_margin_px)


def connect(settings: Settings) -> EmulatorAdb:
    adb = EmulatorAdb(find_adb(settings.adb.adb_path), settings.adb.serial)
    adb.connect()
    return adb


class BotRunner:
    def __init__(self, paths: Paths | None = None, mode: Mode = Mode.HOME) -> None:
        self.paths = paths or Paths()
        self.mode = mode
        self.check_storage = True   # False = keep attacking with full storages (testing)
        self._state = State.IDLE
        self._error: str | None = None
        self._bot: Bot | None = None
        self._started_at: datetime | None = None
        self._stop = threading.Event()
        self._running = threading.Event()   # cleared while paused
        self._running.set()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # --- control (any thread) ---------------------------------------------
    @property
    def active(self) -> bool:
        return self._state in (State.STARTING, State.RUNNING, State.PAUSED, State.STOPPING)

    def start(self, mode: Mode | None = None) -> bool:
        """Run on a background thread. False if already running."""
        with self._lock:
            if self.active:
                return False
            if mode is not None:
                self.mode = mode
            self._state = State.STARTING
            self._thread = threading.Thread(target=self.run, name="coc-bot", daemon=True)
            self._thread.start()
            return True

    def stop(self) -> None:
        if not self.active:
            return
        self._state = State.STOPPING
        self._stop.set()
        self._running.set()
        if self._bot is not None:
            self._bot.stop()

    def pause(self) -> None:
        if self._state is State.RUNNING:
            self._running.clear()
            self._state = State.PAUSED
            log.info("Paused")

    def resume(self) -> None:
        if self._state is State.PAUSED:
            if self._bot is not None:
                self._bot.reset_timers()
            self._state = State.RUNNING
            self._running.set()
            log.info("Resumed")

    def set_check_storage(self, on: bool) -> None:
        """Switch the storage-full check; applies at once to a running bot."""
        self.check_storage = on
        if self._bot is not None:
            self._bot.check_storage = on
        if self.active:
            log.info("Storage check %s", "ON" if on else "OFF (attacking even with full storages)")

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def status(self) -> Status:
        bot = self._bot
        screen = bot.current_screen.name if bot is not None and bot.current_screen is not None else None
        return Status(self._state, self.mode, screen, self._started_at,
                      bot.stats if bot is not None else Stats(), self._error)

    # --- the run itself -----------------------------------------------------
    def _sleep(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while not self._stop.is_set():
            if not self._running.is_set():
                self._running.wait(0.5)
                deadline = max(deadline, time.monotonic())
                continue
            left = deadline - time.monotonic()
            if left <= 0:
                return
            self._stop.wait(min(left, 0.5))

    def run(self) -> int:
        """Blocking run. Returns a process exit code (0 ok, 1 failed, 2 not ready)."""
        from coc_bot.game.actions import Game          # heavy imports (OpenCV, OCR) only when running
        from coc_bot.vision.ocr import OcrReader, rapidocr_engine

        self._stop.clear()
        self._running.set()
        self._error = None
        self._bot = None
        self._state = State.STARTING
        self._started_at = datetime.now()
        game = None
        code = 0
        try:
            if self.mode is not Mode.HOME:
                return self._fail(f"Mode '{self.mode.value}' belum tersedia", 2)
            settings = load_settings(self.paths.settings, self.paths.calibration)
            templates = load_templates(self.paths, settings)
            missing = N.missing_calibration(settings, set(templates.names()))
            if missing:
                return self._fail("Calibration incomplete, missing: " + ", ".join(missing), 2)
            adb = connect(settings)
            shape = adb.screencap().shape[:2]
            if shape != EXPECTED_SHAPE:
                return self._fail(f"Emulator resolution must be 1280x720, got {shape[1]}x{shape[0]}", 2)
            if self._stop.is_set():
                return 0
            rng = random.Random()
            game = Game(adb, templates, OcrReader(rapidocr_engine()), settings, rng, sleep=self._sleep)
            self._bot = Bot(game, SessionPolicy(settings.session, rng), settings, rng,
                            clock=datetime.now, sleep=self._sleep,
                            recorder=CsvRecorder(self.paths.logs))
            self._bot.check_storage = self.check_storage
            if self._stop.is_set():
                return 0
            self._state = State.RUNNING
            self._bot.run()
        except KeyboardInterrupt:
            log.info("Stopped by user (Ctrl+C).")
        except FatalError as exc:
            if game is not None:
                game.save_debug_screenshot("fatal")
            code = self._fail(f"Fatal: {exc}", 1)
        except (AdbError, ValueError) as exc:
            code = self._fail(f"{type(exc).__name__}: {exc}", 3 if isinstance(exc, AdbError) else 2)
        except Exception as exc:  # noqa: BLE001 - report anything, the dashboard must survive
            log.exception("Unexpected error")
            if game is not None:
                game.save_debug_screenshot("crash")
            code = self._fail(f"Unexpected error: {exc}", 1)
        finally:
            if self._state is not State.ERROR:
                self._state = State.STOPPED
        return code

    def _fail(self, message: str, code: int) -> int:
        log.error(message)
        self._error = message
        self._state = State.ERROR
        return code
