from __future__ import annotations

from dataclasses import dataclass

from coc_bot.config import LootConfig, StorageConfig


@dataclass(frozen=True)
class Loot:
    gold: int
    elixir: int
    de: int


def is_worth_attacking(loot: Loot | None, cfg: LootConfig) -> bool:
    if cfg.min_gold == 0 and cfg.min_elixir == 0 and cfg.min_de == 0:
        return True
    if loot is None:
        return False
    return loot.gold >= cfg.min_gold and loot.elixir >= cfg.min_elixir and loot.de >= cfg.min_de


def storage_full(storage: Loot | None, cfg: StorageConfig) -> bool:
    """True when every resource that has a cap configured is at least full_ratio full."""
    checks = [(amount, cap) for amount, cap in
              ((storage.gold if storage else 0, cfg.gold_cap),
               (storage.elixir if storage else 0, cfg.elixir_cap),
               (storage.de if storage else 0, cfg.de_cap))
              if cap > 0]
    if storage is None or not checks:
        return False
    return all(amount >= cap * cfg.full_ratio for amount, cap in checks)
