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
from coc_bot.game.deploy import edge_points, line_points
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
        self.wings: list[list[Point]] = []  # deploy points of the last attack, one list per side

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

    # --- army window (only closed if it opens by accident) ----------------
    def close_army(self) -> bool:
        if self.tap_template(N.ARMY_CLOSE, fresh=False):
            return True
        self.go_back()
        return True

    # --- attack flow ------------------------------------------------------
    def open_attack_menu(self) -> bool:
        return self.tap_template(N.HOME_ATTACK)

    def find_match(self) -> bool:
        if self.tap_template(N.BTN_FIND_MATCH, fresh=False):
            if self.wait_for(N.BTN_ATTACK, timeout_s=3.0):
                self.tap_template(N.BTN_ATTACK, fresh=False)
            return True
        if self.tap_template(N.BTN_ATTACK, fresh=False):
            return True
        return False

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
        if N.ROI_GOLD not in rois or N.ROI_ELIXIR not in rois:
            if self.settings.loot.min_gold == 0 and self.settings.loot.min_elixir == 0 and self.settings.loot.min_de == 0:
                return Loot(0, 0, 0)
            return None
        gold = self.ocr.read_number(image, rois[N.ROI_GOLD], N.MAX_GOLD)
        elixir = self.ocr.read_number(image, rois[N.ROI_ELIXIR], N.MAX_ELIXIR)
        if gold is None or elixir is None:
            if self.settings.loot.min_gold == 0 and self.settings.loot.min_elixir == 0 and self.settings.loot.min_de == 0:
                return Loot(0, 0, 0)
            return None
        de = self.ocr.read_number(image, rois[N.ROI_DE], N.MAX_DE) if N.ROI_DE in rois else None
        if de is None:
            if self.settings.loot.min_de > 0:
                return None
            de = 0
        return Loot(gold, elixir, de)

    def _read_resources(self, names: tuple[str, str, str]) -> Loot | None:
        """OCR three counters from the current frame; uncalibrated ones read as 0."""
        rois = self.settings.calibration.rois
        if not any(name in rois for name in names):
            return None
        image = self._image(fresh=False)
        values = []
        for name in names:
            if name not in rois:
                values.append(0)
                continue
            value = self.ocr.read_number(image, rois[name], N.ROI_LIMITS[name])
            if value is None:
                log.warning("Could not read %s", name)
                return None
            values.append(value)
        return Loot(*values)

    def read_storage(self) -> Loot | None:
        """Own gold/elixir/DE on the home village."""
        return self._read_resources(N.HOME_ROIS)

    def deploy_army(self) -> None:
        d = self.settings.deploy
        points = self.settings.calibration.points
        height, width = self.last_image.shape[:2] if self.last_image is not None else (720, 1280)
        if all(k in points for k in ("map_11", "map_9", "map_1", "map_3")):
            left_targets = line_points(points["map_11"], points["map_9"], d.points_per_side,
                                       self.settings.timing.tap_jitter_px, self.rng, (width, height), d.max_y)
            right_targets = line_points(points["map_1"], points["map_3"], d.points_per_side,
                                        self.settings.timing.tap_jitter_px, self.rng, (width, height), d.max_y)
            targets = left_targets + right_targets
            self.wings = [left_targets, right_targets]
        else:
            corners = [points[name] for name in N.MAP_CORNERS]
            targets = edge_points(corners, d.sides, d.points_per_side, d.outward_px,
                                  self.settings.timing.tap_jitter_px, self.rng, (width, height), d.max_y,
                                  pattern=d.pattern)
            per = max(d.points_per_side, 1)
            self.wings = [targets[i:i + per] for i in range(0, len(targets), per)]
        for slot in d.troop_slots:
            slot_name = N.troop_slot(slot)
            if slot_name in points:
                self.tap(points[slot_name])
                for x, y in targets:
                    for _ in range(d.taps_per_point):
                        self.adb.tap(x, y)
                        self.sleep(self.rng.uniform(0.04, 0.11))

        def _jitter_point(pt: Point, jitter: int = 15) -> Point:
            jx = self.rng.randint(-jitter, jitter)
            jy = self.rng.randint(-jitter, jitter)
            return (
                min(max(pt[0] + jx, 0), width - 1),
                min(max(pt[1] + jy, 0), min(height - 1, d.max_y)),
            )

        if d.siege_slot > 0:
            siege_name = N.troop_slot(d.siege_slot)
            if siege_name in points and targets:
                drop_pt = _jitter_point(self.rng.choice(targets), jitter=20)
                self.tap(points[siege_name])
                self.tap(drop_pt)
                self.sleep(0.2)

        if d.hero_slots:
            chosen_targets = (
                self.rng.sample(targets, len(d.hero_slots))
                if len(targets) >= len(d.hero_slots)
                else [self.rng.choice(targets) for _ in d.hero_slots]
            )
            for slot, target_pt in zip(d.hero_slots, chosen_targets):
                hero_name = N.troop_slot(slot)
                if hero_name in points:
                    card_pt = points[hero_name]
                    drop_pt = _jitter_point(target_pt, jitter=15)
                    self.tap(card_pt)
                    self.tap(drop_pt)
                    self.sleep(0.3)
                    self.tap(card_pt)
                    self.sleep(0.2)

    def spell_rows(self) -> list[list[Point]]:
        """Spell drop points: one row per deploy wing, like the troop rows but shifted forward.

        Each wing's row is moved `depth` of the way from its middle towards map_center (0 = on the
        deploy line, 1 = at the centre). `casts` spells per slot are split evenly over the wings and
        spread along each shifted row.
        """
        cfg = self.settings.spells
        center = self.settings.calibration.points.get(N.MAP_CENTER)
        wings = [w for w in self.wings if w]
        if center is None or not wings or cfg.casts <= 0:
            return []
        height, width = self.last_image.shape[:2] if self.last_image is not None else (720, 1280)
        max_y = min(height - 1, self.settings.deploy.max_y)
        per_wing, extra = divmod(cfg.casts, len(wings))
        rows: list[list[Point]] = []
        for i, wing in enumerate(wings):
            count = per_wing + (1 if i < extra else 0)
            if count == 0:
                continue
            mx = sum(p[0] for p in wing) / len(wing)
            my = sum(p[1] for p in wing) / len(wing)
            dx, dy = (center[0] - mx) * cfg.depth, (center[1] - my) * cfg.depth
            (ax, ay), (bx, by) = wing[0], wing[-1]
            row = []
            for k in range(count):
                t = (k + 0.5) / count  # middle of each equal segment of the row
                x = ax + (bx - ax) * t + dx
                y = ay + (by - ay) * t + dy
                row.append((min(max(int(round(x)), 0), width - 1), min(max(int(round(y)), 0), max_y)))
            rows.append(row)
        return rows

    def cast_spells(self) -> bool:
        """Drop each spell slot along rows in front of the deployed troops."""
        cfg = self.settings.spells
        points = self.settings.calibration.points
        targets = [pt for row in self.spell_rows() for pt in row]
        if not cfg.slots or not targets:
            return False
        cast = False
        for slot in cfg.slots:
            card = points.get(N.troop_slot(slot))
            if card is None:
                continue
            self.tap(card)
            for target in targets:
                self.tap(target)
            cast = True
        return cast

    def end_battle(self) -> None:
        tapped = self.tap_template(N.BTN_SURRENDER) or self.tap_template(N.BTN_END_BATTLE)
        if tapped and self.wait_for(N.POPUP_OKAY, timeout_s=3.0):
            self.tap_template(N.POPUP_OKAY, fresh=False)

    def read_damage_percent(self) -> int | None:
        image = self._image(fresh=True)
        crop = image[520:570, 1140:1260]
        if crop.size == 0:
            return None
        big = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        try:
            texts = [text for text, conf in self.ocr._engine(big) if conf >= 0.5]
            digits = "".join(ch for text in texts for ch in text if ch.isdigit())
            if digits:
                val = int(digits)
                if 0 <= val <= 100:
                    return val
        except Exception:
            pass
        return None

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
        if not cv2.imwrite(str(path), self.last_image):
            log.warning("Could not write screenshot %s", path)
            return None
        log.info("Saved screenshot %s", path)
        return path
