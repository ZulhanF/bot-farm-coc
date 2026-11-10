from coc_bot.config import LootConfig
from coc_bot.game.loot import Loot, is_worth_attacking

CFG = LootConfig(min_gold=100, min_elixir=200, min_de=0, max_next=50)


def test_worth_when_all_thresholds_met():
    assert is_worth_attacking(Loot(100, 200, 0), CFG)


def test_not_worth_when_one_below():
    assert not is_worth_attacking(Loot(99, 500, 0), CFG)
    assert not is_worth_attacking(Loot(500, 199, 0), CFG)


def test_de_threshold():
    cfg = LootConfig(min_gold=0, min_elixir=0, min_de=50, max_next=50)
    assert not is_worth_attacking(Loot(0, 0, 49), cfg)
    assert is_worth_attacking(Loot(0, 0, 50), cfg)


def test_none_is_not_worth():
    assert not is_worth_attacking(None, CFG)
