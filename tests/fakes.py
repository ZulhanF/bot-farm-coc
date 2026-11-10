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
