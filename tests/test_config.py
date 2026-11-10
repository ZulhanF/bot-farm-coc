import pytest

from coc_bot.config import Calibration, load_calibration, load_settings, save_calibration


def test_defaults_when_files_missing(tmp_path):
    s = load_settings(tmp_path / "missing.toml", tmp_path / "missing_cal.toml")
    assert s.adb.serial == "127.0.0.1:5555"
    assert s.loot.max_next == 50
    assert s.timing.tap_delay_ms == (120, 350)
    assert s.deploy.troop_slots == (1,)
    assert s.calibration.rois == {}


def test_overrides_from_toml(tmp_path):
    path = tmp_path / "settings.toml"
    path.write_text("[loot]\nmin_gold = 123\n[deploy]\ntroop_slots = [1, 2]\n", encoding="utf-8")
    s = load_settings(path, tmp_path / "cal.toml")
    assert s.loot.min_gold == 123
    assert s.loot.min_elixir == 300_000
    assert s.deploy.troop_slots == (1, 2)


def test_unknown_key_raises(tmp_path):
    path = tmp_path / "settings.toml"
    path.write_text("[loot]\nmin_gld = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="min_gld"):
        load_settings(path, tmp_path / "cal.toml")


def test_unknown_section_raises(tmp_path):
    path = tmp_path / "settings.toml"
    path.write_text("[lot]\nx = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="lot"):
        load_settings(path, tmp_path / "cal.toml")


def test_calibration_roundtrip(tmp_path):
    cal = (
        Calibration()
        .with_entry("rois", "gold", (10, 20, 30, 40))
        .with_entry("points", "map_top", (640, 100))
    )
    path = tmp_path / "calibration.toml"
    save_calibration(path, cal)
    loaded = load_calibration(path)
    assert loaded.rois == {"gold": (10, 20, 30, 40)}
    assert loaded.points == {"map_top": (640, 100)}
    assert loaded.templates == {}


def test_with_entry_rejects_unknown_kind():
    with pytest.raises(ValueError):
        Calibration().with_entry("buttons", "x", (1, 2))


def test_calibration_loaded_into_settings(tmp_path):
    cal_path = tmp_path / "calibration.toml"
    save_calibration(cal_path, Calibration().with_entry("templates", "btn_next", (1, 2, 3, 4)))
    s = load_settings(tmp_path / "settings.toml", cal_path)
    assert s.calibration.templates == {"btn_next": (1, 2, 3, 4)}
