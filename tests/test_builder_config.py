import pytest

from coc_bot.config import BUILDER_MODES, BuilderConfig, Settings, load_settings


def write(tmp_path, text):
    path = tmp_path / "settings.toml"
    path.write_text(text, encoding="utf-8")
    return load_settings(path, tmp_path / "calibration.toml")


def test_defaults():
    b = Settings().builder
    assert b.mode == "elixir" and b.cart_every == 15 and b.stage2 is True
    assert BUILDER_MODES == ("elixir", "gold")


def test_loaded_from_toml(tmp_path):
    s = write(tmp_path, '[builder]\nmode = "gold"\ncart_every = 5\nmain_slots = [3, 4]\n')
    assert s.builder.mode == "gold"
    assert s.builder.cart_every == 5
    assert s.builder.main_slots == (3, 4)


def test_unknown_mode_rejected(tmp_path):
    with pytest.raises(ValueError, match="mode"):
        write(tmp_path, '[builder]\nmode = "dark"\n')


def test_cart_every_must_be_positive():
    with pytest.raises(ValueError, match="cart_every"):
        BuilderConfig(cart_every=0)


def test_slots_start_at_one():
    with pytest.raises(ValueError, match="slot"):
        BuilderConfig(main_slots=(0, 3))


def test_tank_slot_zero_means_no_tank():
    assert BuilderConfig(tank_slot=0).tank_slot == 0


def test_unknown_key_rejected(tmp_path):
    with pytest.raises(ValueError, match="Unknown key"):
        write(tmp_path, "[builder]\nbogus = 1\n")
