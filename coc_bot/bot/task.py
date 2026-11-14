"""What a task plugs into the screen loop: one handler per screen plus its own stuck rules."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Callable, Protocol

from coc_bot.vision.screens import Screen

if TYPE_CHECKING:
    from coc_bot.bot.engine import ScreenLoop

Handler = Callable[[datetime], None]


class Task(Protocol):
    handlers: dict[Screen, Handler]
    forward_transitions: frozenset[tuple[Screen, Screen]]  # moving along these = progress
    action_screens: frozenset[Screen]   # stuck if the same screen repeats too many ticks
    wait_screens: frozenset[Screen]     # stuck if shown longer than timing.stuck_timeout_s

    def bind(self, loop: ScreenLoop) -> None: ...
    def on_start(self, now: datetime) -> None: ...
    def is_stuck(self, screen: Screen, same_ticks: int, now: datetime) -> bool: ...
    def on_recover(self) -> None: ...
    def on_resume(self, now: datetime) -> None: ...
