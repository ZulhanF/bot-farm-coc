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


def test_de_roi_required_when_min_de_positive():
    from dataclasses import replace
    settings = Settings(calibration=full_calibration())
    settings = replace(settings, loot=replace(settings.loot, min_de=1000))
    assert N.missing_calibration(settings, set(N.REQUIRED_TEMPLATES)) == ["roi:de"]


def test_template_needs_both_png_and_box():
    settings = Settings(calibration=full_calibration())
    missing = N.missing_calibration(settings, set(N.REQUIRED_TEMPLATES) - {"btn_next"})
    assert missing == ["template:btn_next"]


def test_complete():
    settings = Settings(calibration=full_calibration())
    assert N.missing_calibration(settings, set(N.REQUIRED_TEMPLATES)) == []


def test_valid_names():
    assert "popup_reload" in N.valid_names("template", (1,))
    assert N.valid_names("roi", (1,))[:3] == ("gold", "elixir", "de")
    assert "home_gold" in N.valid_names("roi", (1,))
    assert "result_gold" not in N.valid_names("roi", (1,))
    assert N.valid_names("point", (1, 2))[-2:] == ("troop_slot_1", "troop_slot_2")


def test_home_roi_required_only_for_capped_resources():
    from dataclasses import replace
    settings = Settings(calibration=full_calibration())
    settings = replace(settings, storage=replace(settings.storage, gold_cap=1000))
    missing = N.missing_calibration(settings, set(N.REQUIRED_TEMPLATES))
    assert "roi:home_gold" in missing
    assert "roi:home_elixir" not in missing


def test_spells_require_center_and_card_points():
    from dataclasses import replace
    settings = Settings(calibration=full_calibration())
    settings = replace(settings, spells=replace(settings.spells, slots=(6,)))
    missing = N.missing_calibration(settings, set(N.REQUIRED_TEMPLATES))
    assert missing == ["point:map_center", "point:troop_slot_6"]
    assert N.used_slots(settings) == (1, 6)
    assert "map_center" in N.valid_names("point", (1,))


def test_storage_checks_prefer_bar_over_cap():
    from dataclasses import replace
    cal = full_calibration().with_entry("rois", "home_gold_bar", (1000, 30, 230, 24))
    settings = Settings(calibration=cal)
    settings = replace(settings, storage=replace(settings.storage, gold_cap=1000, elixir_cap=1000))
    assert N.storage_checks(settings) == [("gold", "bar"), ("elixir", "cap")]
    missing = N.missing_calibration(settings, set(N.REQUIRED_TEMPLATES))
    assert "roi:home_gold" not in missing      # bar replaces the counter
    assert "roi:home_elixir" in missing
