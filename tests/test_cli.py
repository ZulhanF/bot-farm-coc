import cv2
import numpy as np

from coc_bot import names as N
from coc_bot.config import Calibration, save_calibration
from coc_bot.main import main


def base_args(tmp_path):
    return ["--settings", str(tmp_path / "settings.toml"),
            "--calibration", str(tmp_path / "calibration.toml"),
            "--templates", str(tmp_path / "templates")]


def test_check_reports_missing(tmp_path, capsys):
    assert main(base_args(tmp_path) + ["check"]) == 2
    out = capsys.readouterr().out
    assert "template:home_attack" in out
    assert "roi:gold" in out
    assert "point:map_top" in out


def test_check_complete(tmp_path, capsys):
    tpl = tmp_path / "templates"
    tpl.mkdir()
    cal = Calibration()
    for name in N.REQUIRED_TEMPLATES:
        cv2.imwrite(str(tpl / f"{name}.png"), np.full((10, 10, 3), 128, np.uint8))
        cal = cal.with_entry("templates", name, (0, 0, 10, 10))
    for name in N.REQUIRED_ROIS:
        cal = cal.with_entry("rois", name, (0, 0, 10, 10))
    for name in N.required_points((1,)):
        cal = cal.with_entry("points", name, (5, 5))
    save_calibration(tmp_path / "calibration.toml", cal)
    assert main(base_args(tmp_path) + ["check"]) == 0
    assert "complete" in capsys.readouterr().out.lower()


def test_check_unreadable_template_png_returns_2(tmp_path, capsys):
    tpl = tmp_path / "templates"
    tpl.mkdir()
    (tpl / "home_attack.png").write_bytes(b"not a png")
    settings_cal = Calibration().with_entry("templates", "home_attack", (0, 0, 10, 10))
    save_calibration(tmp_path / "calibration.toml", settings_cal)
    assert main(base_args(tmp_path) + ["check"]) == 2
    assert "Error" in capsys.readouterr().out


def test_calibrate_rejects_unknown_name(tmp_path, capsys):
    assert main(base_args(tmp_path) + ["calibrate", "template", "bogus"]) == 2
    assert "Valid" in capsys.readouterr().out


def test_test_vision_missing_image(tmp_path, capsys):
    assert main(base_args(tmp_path) + ["test-vision", str(tmp_path / "nope.png")]) == 2


def test_test_vision_prints_screen(tmp_path, capsys):
    img_path = tmp_path / "shot.png"
    cv2.imwrite(str(img_path), np.zeros((720, 1280, 3), np.uint8))
    assert main(base_args(tmp_path) + ["test-vision", str(img_path)]) == 0
    assert "Screen: UNKNOWN" in capsys.readouterr().out
