"""Home-village farming bot: the shared screen loop running the home farming task.

Kept as the import point for existing callers and tests; the loop lives in `engine.py`,
the home handlers in `home_task.py`.
"""
from __future__ import annotations

import random
from datetime import datetime
from typing import Callable

from coc_bot.bot.engine import FatalError, ScreenLoop, Stats
from coc_bot.bot.home_task import HomeFarmTask
from coc_bot.config import Settings

__all__ = ["Bot", "FatalError", "Stats"]


class Bot(ScreenLoop):
    def __init__(
        self,
        game,
        policy,
        settings: Settings,
        rng: random.Random,
        clock: Callable[[], datetime],
        sleep: Callable[[float], None],
        recorder: Callable[[dict], None] | None = None,
    ) -> None:
        super().__init__(game, HomeFarmTask(recorder), policy, settings, rng, clock, sleep)
