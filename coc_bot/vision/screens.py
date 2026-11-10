"""Identify which game screen is showing."""
from __future__ import annotations

from enum import Enum
from typing import Protocol

import numpy as np

from coc_bot import names as N
from coc_bot.vision.templates import Match


class Screen(Enum):
    HOME = "home"
    ATTACK_MENU = "attack_menu"
    ARMY = "army"
    SEARCHING = "searching"
    BASE_PREVIEW = "base_preview"
    BATTLE = "battle"
    RESULT = "result"
    POPUP = "popup"
    UNKNOWN = "unknown"


class TemplateFinder(Protocol):
    def find(self, image: np.ndarray, name: str, threshold: float | None = None) -> Match | None: ...


# Order matters: BASE_PREVIEW also shows End Battle, so it is checked before BATTLE.
SCREEN_MARKERS: tuple[tuple[Screen, str], ...] = (
    (Screen.RESULT, N.BTN_RETURN_HOME),
    (Screen.BASE_PREVIEW, N.BTN_NEXT),
    (Screen.BATTLE, N.BTN_SURRENDER),
    (Screen.BATTLE, N.BTN_END_BATTLE),
    (Screen.ATTACK_MENU, N.BTN_ATTACK),
    (Screen.ATTACK_MENU, N.BTN_FIND_MATCH),
    (Screen.ARMY, N.ARMY_CLOSE),
    (Screen.HOME, N.HOME_ATTACK),
    (Screen.SEARCHING, N.SEARCHING),
)


def detect_screen(image: np.ndarray, templates: TemplateFinder) -> Screen:
    for name in N.POPUP_TEMPLATES:
        if templates.find(image, name) is not None:
            return Screen.POPUP
    for screen, name in SCREEN_MARKERS:
        if templates.find(image, name) is not None:
            return screen
    return Screen.UNKNOWN
