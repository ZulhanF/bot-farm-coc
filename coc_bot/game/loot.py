from __future__ import annotations

from dataclasses import dataclass

from coc_bot.config import LootConfig


@dataclass(frozen=True)
class Loot:
    gold: int
    elixir: int
    de: int


def is_worth_attacking(loot: Loot | None, cfg: LootConfig) -> bool:
    if loot is None:
        return False
    return loot.gold >= cfg.min_gold and loot.elixir >= cfg.min_elixir and loot.de >= cfg.min_de
