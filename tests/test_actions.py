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


def test_read_storage_uncalibrated_returns_none():
    game, _ = make_game()
    assert game.read_storage() is None


def test_read_storage_reads_home_counters():
    HG, HE = (900, 20, 150, 25), (900, 60, 150, 25)
    game, _ = make_game(ocr={HG: 5_000_000, HE: 4_000_000},
                        settings=with_rois(home_gold=HG, home_elixir=HE))
    game.capture()
    assert game.read_storage() == Loot(5_000_000, 4_000_000, 0)


def test_read_storage_unreadable_counter_returns_none():
    HG, HE = (900, 20, 150, 25), (900, 60, 150, 25)
    game, _ = make_game(ocr={HG: 5_000_000}, settings=with_rois(home_gold=HG, home_elixir=HE))
    game.capture()
    assert game.read_storage() is None

