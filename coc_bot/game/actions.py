"""High-level game actions built on the ADB device and vision modules."""
from __future__ import annotations

import logging
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from coc_bot import names as N
from coc_bot.config import Point, Settings
from coc_bot.game.deploy import edge_points
from coc_bot.game.loot import Loot
from coc_bot.vision.screens import Screen, detect_screen

log = logging.getLogger(__name__)


class Game:
    def __init__(
        self,
        adb,
        templates,
        ocr,
        settings: Settings,
        rng: random.Random,
        sleep: Callable[[float], None] = time.sleep,
        debug_dir: Path = Path("logs/screens"),
    ) -> None:
        self.adb = adb
        self.templates = templates
        self.ocr = ocr
        self.settings = settings
        self.rng = rng
        self.sleep = sleep
        self.debug_dir = debug_dir
        self.last_image: np.ndarray | None = None

    # --- primitives -------------------------------------------------------
    def capture(self) -> np.ndarray:
        self.last_image = self.adb.screencap()
        return self.last_image

    def screen(self) -> Screen:
        return detect_screen(self.capture(), self.templates)

    def _pause(self) -> None:
        low, high = self.settings.timing.tap_delay_ms
        self.sleep(self.rng.uniform(low, high) / 1000)

    def tap(self, point: Point) -> None:
        j = self.settings.timing.tap_jitter_px
        self.adb.tap(point[0] + self.rng.randint(-j, j), point[1] + self.rng.randint(-j, j))
        self._pause()

    def _image(self, fresh: bool) -> np.ndarray:
        if fresh or self.last_image is None:
            return self.capture()
        return self.last_image

    def tap_template(self, name: str, fresh: bool = True) -> bool:
        match = self.templates.find(self._image(fresh), name)
        if match is None:
            log.debug("Template not found: %s", name)
            return False
        self.tap(match.center)
        return True

    def wait_for(self, name: str, timeout_s: float = 5.0, interval_s: float = 0.5) -> bool:
        waited = 0.0
        while True:
            if self.templates.find(self.capture(), name) is not None:
                return True
            if waited >= timeout_s:
                return False
            self.sleep(interval_s)
            waited += interval_s

    # --- army -------------------------------------------------------------
    def army_ready(self) -> bool:
        if not self.tap_template(N.BTN_ARMY) or not self.wait_for(N.ARMY_CLOSE):
            return False
        ready = self.templates.find(self.last_image, N.ARMY_FULL) is not None
        self.tap_template(N.ARMY_CLOSE, fresh=False)
        return ready

    def quick_train(self) -> bool:
        if not self.tap_template(N.BTN_ARMY) or not self.wait_for(N.ARMY_CLOSE):
            return False
        ok = (
            self.tap_template(N.TAB_QUICK_TRAIN)
            and self.wait_for(N.BTN_TRAIN_SAVED)
            and self.tap_template(N.BTN_TRAIN_SAVED, fresh=False)
        )
        self.tap_template(N.ARMY_CLOSE)
        return bool(ok)

    def close_army(self) -> bool:
        return self.tap_template(N.ARMY_CLOSE, fresh=False)

    # --- attack flow ------------------------------------------------------
    def open_attack_menu(self) -> bool:
        return self.tap_template(N.HOME_ATTACK)

    def find_match(self) -> bool:
        return self.tap_template(N.BTN_FIND_MATCH, fresh=False)

    def next_base(self) -> bool:
        return self.tap_template(N.BTN_NEXT, fresh=False)

    def read_loot(self) -> Loot | None:
        for attempt in range(2):
            image = self._image(fresh=attempt > 0)
            loot = self._read_loot_once(image)
            if loot is not None:
                return loot
        return None

    def _read_loot_once(self, image: np.ndarray) -> Loot | None:
        rois = self.settings.calibration.rois
        gold = self.ocr.read_number(image, rois[N.ROI_GOLD], N.MAX_GOLD)
        elixir = self.ocr.read_number(image, rois[N.ROI_ELIXIR], N.MAX_ELIXIR)
        if gold is None or elixir is None:
            return None
        de = self.ocr.read_number(image, rois[N.ROI_DE], N.MAX_DE) if N.ROI_DE in rois else None
        if de is None:
            if self.settings.loot.min_de > 0:
                return None
            de = 0
        return Loot(gold, elixir, de)

    def deploy_army(self) -> None:
        d = self.settings.deploy
        points = self.settings.calibration.points
        corners = [points[name] for name in N.MAP_CORNERS]
        height, width = self.last_image.shape[:2] if self.last_image is not None else (720, 1280)
        targets = edge_points(corners, d.sides, d.points_per_side, d.outward_px,
                              self.settings.timing.tap_jitter_px, self.rng, (width, height), d.max_y)
        for slot in d.troop_slots:
            self.tap(points[N.troop_slot(slot)])
            for x, y in targets:
                for _ in range(d.taps_per_point):
                    self.adb.tap(x, y)
                    self.sleep(self.rng.uniform(0.04, 0.11))

    def end_battle(self) -> None:
        if self.tap_template(N.BTN_END_BATTLE) and self.wait_for(N.POPUP_OKAY, timeout_s=3.0):
            self.tap_template(N.POPUP_OKAY, fresh=False)

    def return_home(self) -> bool:
        return self.tap_template(N.BTN_RETURN_HOME, fresh=False)

    # --- recovery ---------------------------------------------------------
    def dismiss_popup(self) -> bool:
        image = self._image(fresh=False)
        for name in N.POPUP_TEMPLATES:
            match = self.templates.find(image, name)
            if match is not None:
                log.info("Dismissing popup: %s", name)
                self.tap(match.center)
                return True
        return False

    def go_back(self) -> None:
        self.adb.key_back()
        self._pause()

    def restart_game(self) -> None:
        package = self.settings.adb.package
        log.warning("Restarting %s", package)
        self.adb.stop_app(package)
        self.sleep(3.0)
        self.adb.start_app(package)
        self.sleep(30.0)

    def reconnect(self) -> None:
        self.adb.connect()

    def save_debug_screenshot(self, tag: str) -> Path | None:
        if self.last_image is None:
            return None
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        path = self.debug_dir / f"{datetime.now():%Y%m%d_%H%M%S_%f}_{tag}.png"
        cv2.imwrite(str(path), self.last_image)
        log.info("Saved screenshot %s", path)
        return path
