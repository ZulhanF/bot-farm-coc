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


def test_boat_is_searched_anywhere():
    class Recording(FakeTemplates):
        def find(self, image, name, threshold=None, anywhere=False):
            self.anywhere = anywhere
            return super().find(image, name, threshold)
    game, _ = make()
    game.templates = Recording({N.BB_BOAT})
    assert game.go_to_builder_base() is True
    assert game.templates.anywhere is True


def test_boat_not_visible_swipes_map_then_gives_up():
    game, adb = make()
    assert game.go_to_builder_base() is False
    assert sum(1 for c in adb.calls if c[0] == "swipe") == 2


def test_boat_found_without_swiping():
    game, adb = make(visible={N.BB_BOAT})
    assert game.go_to_builder_base() is True
    assert not any(c[0] == "swipe" for c in adb.calls)


def test_cart_is_searched_anywhere():
    class Recording(FakeTemplates):
        def find(self, image, name, threshold=None, anywhere=False, scales=(1.0,)):
            if name == N.BB_ELIXIR_CART:
                self.cart_anywhere = anywhere
            return super().find(image, name, threshold)
    game, _ = make()
    game.templates = Recording({N.BB_ELIXIR_CART, N.BB_BTN_COLLECT})
    assert game.collect_cart() is True
    assert game.templates.cart_anywhere is True


def test_cart_not_visible_swipes_towards_dock_then_gives_up():
    game, adb = make()
    assert game.collect_cart() is False
    assert sum(1 for c in adb.calls if c[0] == "swipe") == 2


def test_drop_waits_after_selecting_the_card():
    slept = []
    game, adb = make(troop_slot=2)
    game.sleep = slept.append
    game.drop_one_troop()
    assert any(s >= 0.4 for s in slept)


def test_battle_stage_from_map_colour():
    import cv2
    import numpy as np
    game, adb = make()
    hsv = np.zeros((720, 1280, 3), np.uint8)
    hsv[...] = (110, 150, 110)
    adb.image = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    game.capture()
    assert game.battle_stage() == 2
    adb.image = np.zeros((720, 1280, 3), np.uint8)
    game.capture()
    assert game.battle_stage() == 1
