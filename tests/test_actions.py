import random
from dataclasses import replace

from coc_bot.game.actions import Game
from coc_bot.game.loot import Loot
from coc_bot.vision.screens import Screen
from tests.fakes import FakeAdb, FakeOcr, FakeTemplates, make_settings

GOLD, ELIXIR, DE = (10, 10, 100, 20), (10, 40, 100, 20), (10, 70, 100, 20)


def make_game(visible=(), positions=None, ocr=None, settings=None, debug_dir=None):
    adb = FakeAdb()
    kwargs = {"debug_dir": debug_dir} if debug_dir else {}
    game = Game(adb, FakeTemplates(visible, positions), FakeOcr(ocr or {}),
                settings or make_settings(), random.Random(0), sleep=lambda s: None, **kwargs)
    return game, adb


def near(point, target, tol=4):
    return abs(point[0] - target[0]) <= tol and abs(point[1] - target[1]) <= tol


def test_screen_uses_fresh_capture():
    game, adb = make_game({"home_attack"})
    assert game.screen() is Screen.HOME
    assert adb.calls[0] == ("screencap",)
    assert game.last_image is not None


def test_tap_template_taps_near_center():
    game, adb = make_game({"btn_next"}, {"btn_next": (500, 300)})
    assert game.tap_template("btn_next")
    assert near(adb.taps()[0], (505, 305))


def test_tap_template_missing():
    game, adb = make_game()
    assert not game.tap_template("btn_next")
    assert adb.taps() == []


def test_read_loot():
    game, _ = make_game(ocr={GOLD: 400_000, ELIXIR: 350_000, DE: 2_000})
    game.capture()
    assert game.read_loot() == Loot(400_000, 350_000, 2_000)


def test_read_loot_de_optional():
    game, _ = make_game(ocr={GOLD: 1, ELIXIR: 2})
    assert game.read_loot() == Loot(1, 2, 0)


def test_read_loot_requires_de_when_min_de_set():
    s = make_settings()
    s = replace(s, loot=replace(s.loot, min_de=100))
    game, _ = make_game(ocr={GOLD: 1, ELIXIR: 2}, settings=s)
    assert game.read_loot() is None


def test_read_loot_none_when_gold_unreadable():
    game, adb = make_game(ocr={ELIXIR: 2})
    assert game.read_loot() is None
    assert sum(1 for c in adb.calls if c[0] == "screencap") == 2  # initial + one retry


def test_deploy_army_tap_count():
    s = make_settings()
    s = replace(s, deploy=replace(s.deploy, troop_slots=(1, 2), sides=4, points_per_side=5, taps_per_point=2))
    game, adb = make_game(settings=s)
    game.capture()
    game.deploy_army()
    taps = adb.taps()
    assert len(taps) == 2 * (1 + 20 * 2)
    assert near(taps[0], (200, 680))
    assert all(y <= s.deploy.max_y for _, y in taps[1:41])


def test_dismiss_popup_prefers_reload():
    pos = {"popup_close": (1200, 50), "popup_reload": (600, 400)}
    game, adb = make_game(set(pos), pos)
    assert game.dismiss_popup()
    assert near(adb.taps()[0], (605, 405))


def test_dismiss_popup_nothing():
    game, _ = make_game()
    assert not game.dismiss_popup()


def test_end_battle_confirms():
    pos = {"btn_end_battle": (50, 550), "popup_okay": (700, 450)}
    game, adb = make_game(set(pos), pos)
    game.end_battle()
    taps = adb.taps()
    assert near(taps[0], (55, 555)) and near(taps[1], (705, 455))


def test_restart_game_stops_then_starts():
    game, adb = make_game()
    game.restart_game()
    kinds = [c for c in adb.calls if c[0] in ("stop", "start")]
    assert kinds == [("stop", "com.supercell.clashofclans"), ("start", "com.supercell.clashofclans")]


def test_go_back_and_reconnect():
    game, adb = make_game()
    game.go_back()
    game.reconnect()
    assert ("back",) in adb.calls and ("connect",) in adb.calls


def test_save_debug_screenshot(tmp_path):
    game, _ = make_game(debug_dir=tmp_path)
    assert game.save_debug_screenshot("x") is None
    game.capture()
    path = game.save_debug_screenshot("stuck")
    assert path is not None and path.exists() and path.name.endswith("_stuck.png")


def test_save_debug_screenshot_write_failure_returns_none(tmp_path, monkeypatch):
    import cv2
    game, _ = make_game(debug_dir=tmp_path)
    game.capture()
    monkeypatch.setattr(cv2, "imwrite", lambda *a, **k: False)
    assert game.save_debug_screenshot("x") is None


def with_rois(**rois):
    s = make_settings()
    return replace(s, calibration=replace(s.calibration, rois={**s.calibration.rois, **rois}))


GOLD_BAR, ELIXIR_BAR = (1000, 30, 230, 24), (1000, 80, 230, 24)


def bar_screen(gold_fill, elixir_fill):
    """1280x720 frame with flat gold / elixir bars filled from the right."""
    import cv2
    import numpy as np
    from coc_bot.vision.bars import BAR_HUES
    hsv = np.zeros((720, 1280, 3), np.uint8)
    hsv[..., 0], hsv[..., 1], hsv[..., 2] = 110, 60, 80
    for (x, y, w, h), fill, hue in ((GOLD_BAR, gold_fill, BAR_HUES["gold"]),
                                    (ELIXIR_BAR, elixir_fill, BAR_HUES["elixir"])):
        n = int(round(w * fill))
        hsv[y:y + h, x + w - n:x + w] = (hue, 200, 220)
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)


def test_storage_levels_empty_when_nothing_configured():
    game, _ = make_game()
    assert game.storage_levels() == {}


def test_storage_levels_from_bars_need_no_capacity():
    game, adb = make_game(settings=with_rois(home_gold_bar=GOLD_BAR, home_elixir_bar=ELIXIR_BAR))
    adb.image = bar_screen(1.0, 0.5)
    game.capture()
    levels = game.storage_levels()
    assert set(levels) == {"gold", "elixir"}
    assert levels["gold"] >= 0.97 and abs(levels["elixir"] - 0.5) < 0.04


def test_storage_levels_from_counter_and_cap():
    HG = (900, 20, 150, 25)
    s = with_rois(home_gold=HG)
    s = replace(s, storage=replace(s.storage, gold_cap=10_000_000))
    game, _ = make_game(ocr={HG: 9_000_000}, settings=s)
    game.capture()
    assert game.storage_levels() == {"gold": 0.9}


def test_bar_wins_over_cap_and_unreadable_counter_is_none():
    HE = (900, 60, 150, 25)
    s = with_rois(home_gold_bar=GOLD_BAR, home_elixir=HE)
    s = replace(s, storage=replace(s.storage, gold_cap=10_000_000, elixir_cap=10_000_000))
    game, adb = make_game(ocr={}, settings=s)
    adb.image = bar_screen(1.0, 0.0)
    game.capture()
    levels = game.storage_levels()
    assert levels["gold"] >= 0.97 and levels["elixir"] is None


def spell_game(depth=0.5, casts=2, center=(640, 360)):
    s = make_settings()
    pts = dict(s.calibration.points, troop_slot_6=(700, 680))
    if center is not None:
        pts["map_center"] = center
    s = replace(s, calibration=replace(s.calibration, points=pts),
                spells=replace(s.spells, slots=(6,), casts=casts, depth=depth))
    return make_game(settings=s)


def test_spell_rows_are_troop_rows_shifted_forward():
    game, _ = spell_game(depth=0.5, casts=8)       # 4 wings -> 2 spells per row
    game.capture()
    game.deploy_army()
    rows = game.spell_rows()
    assert [len(r) for r in rows] == [2, 2, 2, 2]
    for wing, row in zip(game.wings, rows):
        mx = sum(p[0] for p in wing) / len(wing)
        my = sum(p[1] for p in wing) / len(wing)
        shift = ((640 - mx) * 0.5, (360 - my) * 0.5)
        (ax, ay), (bx, by) = wing[0], wing[-1]
        for k, (x, y) in enumerate(row):
            t = (k + 0.5) / 2
            ex, ey = ax + (bx - ax) * t + shift[0], ay + (by - ay) * t + shift[1]
            assert abs(x - ex) <= 1 and abs(y - min(ey, 600)) <= 1


def test_spell_rows_split_casts_over_wings():
    game, _ = spell_game(casts=6)                  # 4 wings -> 2, 2, 1, 1
    game.capture()
    game.deploy_army()
    assert [len(r) for r in game.spell_rows()] == [2, 2, 1, 1]


def test_depth_zero_keeps_spells_on_the_deploy_line():
    game, _ = spell_game(depth=0.0, casts=4)
    game.capture()
    game.deploy_army()
    for wing, row in zip(game.wings, game.spell_rows()):
        (ax, ay), (bx, by) = wing[0], wing[-1]
        x, y = row[0]
        assert abs(x - (ax + (bx - ax) * 0.5)) <= 1 and abs(y - (ay + (by - ay) * 0.5)) <= 1


def test_cast_spells_taps_card_then_each_row():
    game, adb = spell_game(casts=4)
    game.capture()
    game.deploy_army()
    before = len(adb.taps())
    targets = [pt for row in game.spell_rows() for pt in row]
    assert game.cast_spells()
    taps = adb.taps()[before:]
    assert len(taps) == 1 + len(targets) == 5
    assert near(taps[0], (700, 680))
    for tap, target in zip(taps[1:], targets):
        assert near(tap, target)


def test_cast_spells_needs_center_and_a_deploy():
    game, adb = spell_game(center=None)
    game.capture()
    game.deploy_army()
    before = len(adb.taps())
    assert not game.cast_spells()
    assert len(adb.taps()) == before
    fresh, adb2 = spell_game()
    assert not fresh.cast_spells()   # nothing deployed yet
    assert adb2.taps() == []
