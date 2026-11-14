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
    assert ("template", N.BB_BTN_END_BATTLE) not in items
    assert ("template", N.BB_BOAT) in items and ("template", N.HOME_ATTACK) in items


def test_gold_mode_needs_stage2_and_damage_roi():
    items = N.builder_requirements(builder(mode="gold", hero_slot=1, tank_slot=2, main_slots=(3, 4),
                                           stage2_slots=(5,)))
    assert ("template", N.BB_BTN_END_BATTLE) in items
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
        ({N.BB_PREP, N.BB_BTN_END_BATTLE}, Screen.BB_STAGE2_PREP),   # stage 2 prep has End Battle
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


def test_dark_blue_map_marks_stage2_prep_without_end_battle_button():
    hsv = np.zeros((720, 1280, 3), np.uint8)
    hsv[...] = (110, 150, 110)
    import cv2
    blue = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    assert detect_builder_screen(blue, FakeTemplates({N.BB_PREP})) is Screen.BB_STAGE2_PREP
    assert detect_builder_screen(IMG, FakeTemplates({N.BB_PREP})) is Screen.BB_PREP
