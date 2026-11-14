"""Identify which game screen is showing."""
from __future__ import annotations

from enum import Enum
from typing import Protocol

import numpy as np

from coc_bot import names as N
from coc_bot.vision.stage import is_stage2_map
from coc_bot.vision.templates import Match


class Screen(Enum):
    HOME = "home"
    ATTACK_MENU = "attack_menu"
    SEARCHING = "searching"
    BASE_PREVIEW = "base_preview"
    BATTLE = "battle"
    RESULT = "result"
    BB_HOME = "bb_home"
    BB_SEARCHING = "bb_searching"
    BB_PREP = "bb_prep"
    BB_STAGE2_PREP = "bb_stage2_prep"
    BB_BATTLE = "bb_battle"
    BB_RESULT = "bb_result"
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
    (Screen.HOME, N.HOME_ATTACK),
    (Screen.SEARCHING, N.SEARCHING),
)


# Builder Base: result first (it may still show battle buttons), the prep banner before battle buttons,
# the home village last (boat target). Stage-2 prep = prep banner + End Battle (see detect_builder_screen).
BUILDER_MARKERS: tuple[tuple[Screen, str], ...] = (
    (Screen.BB_RESULT, N.BB_BTN_RETURN_HOME),
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
    screen = _detect(image, templates, BUILDER_MARKERS)
    # Both stages show the same "battle starts in" banner; stage 2 offers End Battle while preparing
    # and is a dark blue cave instead of a green field (either sign is enough).
    if screen is Screen.BB_PREP and (templates.find(image, N.BB_BTN_END_BATTLE) is not None
                                     or is_stage2_map(image)):
        return Screen.BB_STAGE2_PREP
    return screen
