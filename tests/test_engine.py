import random

from coc_bot.bot.engine import ScreenLoop
from coc_bot.vision.screens import Screen
from tests.fakes import FakeClock, FakeGame, FakePolicy, make_settings


class DummyTask:
    forward_transitions = frozenset({(Screen.HOME, Screen.ATTACK_MENU)})
    action_screens = frozenset({Screen.ATTACK_MENU})
    wait_screens = frozenset({Screen.UNKNOWN})

    def __init__(self, stuck=False):
        self.events = []
        self.stuck = stuck
        self.loop = None
        self.handlers = {Screen.ATTACK_MENU: lambda now: self.events.append("menu")}

    def bind(self, loop):
        self.loop = loop

    def on_start(self, now):
        self.events.append("start")

    def is_stuck(self, screen, same_ticks, now):
        return self.stuck

    def on_recover(self):
        self.events.append("recover")

    def on_resume(self, now):
        self.events.append("resume")


def make_loop(screens, task):
    clock = FakeClock()
    game = FakeGame(screens)
    loop = ScreenLoop(game, task, FakePolicy(), make_settings(), random.Random(0),
                      clock=clock.now, sleep=clock.sleep)
    return loop, game, clock


def test_bind_and_dispatch():
    task = DummyTask()
    loop, _, _ = make_loop([Screen.ATTACK_MENU], task)
    assert task.loop is loop
    loop.tick()
    assert task.events == ["menu"]


def test_on_start_called_once_per_run():
    task = DummyTask()
    loop, _, _ = make_loop([Screen.ATTACK_MENU], task)
    loop.run(max_ticks=3)
    assert task.events.count("start") == 1


def test_unhandled_screen_waits():
    task = DummyTask()
    loop, _, clock = make_loop([Screen.RESULT], task)
    loop.tick()
    assert clock.slept == [2.0]


def test_task_stuck_rule_triggers_back_and_on_recover():
    task = DummyTask(stuck=True)
    loop, game, _ = make_loop([Screen.ATTACK_MENU], task)
    loop.tick()
    assert game.count("go_back") == 1
    assert "recover" in task.events
    assert loop.stats.recoveries == 1


def test_reset_timers_notifies_task():
    task = DummyTask()
    loop, _, _ = make_loop([Screen.ATTACK_MENU], task)
    loop.reset_timers()
    assert task.events == ["resume"]


def test_stats_has_builder_counters():
    task = DummyTask()
    loop, _, _ = make_loop([Screen.ATTACK_MENU], task)
    assert loop.stats.carts == 0 and loop.stats.stage2 == 0
