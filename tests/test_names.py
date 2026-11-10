from coc_bot import names as N
from coc_bot.config import Calibration, Settings


def full_calibration():
    cal = Calibration()
    for name in N.REQUIRED_TEMPLATES:
        cal = cal.with_entry("templates", name, (0, 0, 10, 10))
    for name in N.REQUIRED_ROIS:
        cal = cal.with_entry("rois", name, (0, 0, 10, 10))
    for name in N.required_points((1,)):
        cal = cal.with_entry("points", name, (5, 5))
    return cal


def test_missing_everything():
    missing = N.missing_calibration(Settings(), set())
    assert "template:home_attack" in missing
    assert "roi:gold" in missing
    assert "point:map_top" in missing
    assert "point:troop_slot_1" in missing
    assert "roi:de" not in missing  # optional


def test_template_needs_both_png_and_box():
    settings = Settings(calibration=full_calibration())
    missing = N.missing_calibration(settings, set(N.REQUIRED_TEMPLATES) - {"btn_next"})
    assert missing == ["template:btn_next"]


def test_complete():
    settings = Settings(calibration=full_calibration())
    assert N.missing_calibration(settings, set(N.REQUIRED_TEMPLATES)) == []


def test_valid_names():
    assert "popup_reload" in N.valid_names("template", (1,))
    assert N.valid_names("roi", (1,)) == ("gold", "elixir", "de")
    assert N.valid_names("point", (1, 2))[-2:] == ("troop_slot_1", "troop_slot_2")
