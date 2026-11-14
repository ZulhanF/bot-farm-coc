"""Shared test doubles. Later tasks append more fakes to this file."""
from coc_bot.vision.templates import Match


class FakeTemplates:
    def __init__(self, visible=(), positions=None):
        self.visible = set(visible)
        self.positions = positions or {}

    def find(self, image, name, threshold=None):
        if name not in self.visible:
            return None
        x, y = self.positions.get(name, (100, 100))
        return Match(name, x, y, 10, 10, 0.99)

    def names(self):
        return sorted(self.visible)


from dataclasses import replace

import numpy as np

from coc_bot.config import Calibration, Settings


class FakeAdb:
    def __init__(self, image=None):
        self.image = image if image is not None else np.zeros((720, 1280, 3), np.uint8)
        self.calls = []

    def screencap(self):
        self.calls.append(("screencap",))
        return self.image

    def tap(self, x, y):
        self.calls.append(("tap", x, y))

    def key_back(self):
        self.calls.append(("back",))

    def start_app(self, package):
        self.calls.append(("start", package))

    def stop_app(self, package):
        self.calls.append(("stop", package))

    def connect(self):
        self.calls.append(("connect",))

    def taps(self):
        return [(c[1], c[2]) for c in self.calls if c[0] == "tap"]


class FakeOcr:
    def __init__(self, values):
        self.values = values  # roi tuple -> int | None

    def read_number(self, image, roi, max_value):
        return self.values.get(tuple(roi))


def make_settings(**overrides):
    cal = Calibration(
        templates={},
        rois={"gold": (10, 10, 100, 20), "elixir": (10, 40, 100, 20), "de": (10, 70, 100, 20)},
        points={
            "map_top": (640, 100), "map_right": (1100, 360),
            "map_bottom": (640, 620), "map_left": (180, 360),
            "troop_slot_1": (200, 680), "troop_slot_2": (280, 680),
        },
    )
    return replace(Settings(calibration=cal), **overrides)


from datetime import datetime, timedelta

from coc_bot.device.adb import AdbError


class FakeClock:
    def __init__(self, start=datetime(2026, 11, 10, 9, 0)):
        self.current = start
        self.slept = []

    def now(self):
        return self.current

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.current += timedelta(seconds=seconds)


class FakeGame:
    def __init__(self, screens, loot=None):
        self.screens = list(screens)
        self.loot = loot
        self.fail_screen_times = 0
        self.failing = set()
        self.calls = []
        self.on_restart = None

    def count(self, name):
        return sum(1 for c in self.calls if c == name)

    def screen(self):
        if self.fail_screen_times > 0:
            self.fail_screen_times -= 1
            raise AdbError("boom")
        return self.screens.pop(0) if len(self.screens) > 1 else self.screens[0]

    def read_loot(self):
        self.calls.append("read_loot")
        return self.loot

    def storage_levels(self):
        self.calls.append("storage_levels")
        return getattr(self, "levels", {})

    def read_damage_percent(self):
        return getattr(self, "damage_percent", None)

    def save_debug_screenshot(self, tag):
        self.calls.append("save_debug_screenshot")
        return None

    def restart_game(self):
        self.calls.append("restart_game")
        if self.on_restart:
            self.on_restart()
        return "restart_game" not in self.failing

    def __getattr__(self, name):
        if name in {"open_attack_menu", "find_match", "next_base",
                    "deploy_army", "cast_spells", "end_battle", "return_home", "dismiss_popup", "go_back",
                    "reconnect"}:
            return lambda: (self.calls.append(name), name not in self.failing)[1]
        raise AttributeError(name)


class FakePolicy:
    def __init__(self, rest=False, rest_s=600.0):
        self.rest = rest
        self.rest_s = rest_s
        self.events = []

    def start_play(self, now):
        self.events.append("start")

    def end_play(self, now):
        self.events.append("end")

    def should_rest(self, now):
        return self.rest

    def rest_seconds(self, now):
        self.rest = False
        return self.rest_s


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
