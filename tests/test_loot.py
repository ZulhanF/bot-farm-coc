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


from coc_bot.config import StorageConfig
from coc_bot.game.loot import storage_full

STORE = StorageConfig(gold_cap=1000, elixir_cap=2000, de_cap=0, full_ratio=0.9)


def test_storage_full_needs_every_capped_resource():
    assert storage_full(Loot(900, 1800, 0), STORE)
    assert not storage_full(Loot(900, 1799, 0), STORE)
    assert not storage_full(Loot(899, 2000, 0), STORE)


def test_storage_uncapped_resource_ignored():
    assert storage_full(Loot(1000, 2000, 0), STORE)  # DE has no cap


def test_storage_not_checked_without_caps_or_reading():
    assert not storage_full(Loot(10**9, 10**9, 10**9), StorageConfig())
    assert not storage_full(None, STORE)
