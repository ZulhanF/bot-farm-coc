import random
from dataclasses import replace

import pytest

from coc_bot.bot.state_machine import Bot, FatalError
from coc_bot.game.loot import Loot
from coc_bot.vision.screens import Screen
from tests.fakes import FakeClock, FakeGame, FakePolicy, make_settings

RICH = Loot(1_000_000, 1_000_000, 0)
POOR = Loot(1_000, 1_000, 0)


def make_bot(game, policy=None, settings=None):
    clock = FakeClock()
    bot = Bot(game, policy or FakePolicy(), settings or make_settings(), random.Random(0),
              clock=clock.now, sleep=clock.sleep)
    return bot, clock


def with_timing(**kw):
    s = make_settings()
    return replace(s, timing=replace(s.timing, **kw))


def with_loot(**kw):
    s = make_settings()
    return replace(s, loot=replace(s.loot, **kw))


def test_home_opens_attack_menu():
    game = FakeGame([Screen.HOME])
    make_bot(game)[0].tick()
    assert game.count("open_attack_menu") == 1


def test_attack_menu_finds_match():
    game = FakeGame([Screen.ATTACK_MENU])
    make_bot(game)[0].tick()
    assert game.count("find_match") == 1


def test_poor_base_skipped():
    game = FakeGame([Screen.BASE_PREVIEW], loot=POOR)
    bot, _ = make_bot(game)
    bot.tick()
    assert game.count("next_base") == 1 and game.count("deploy_army") == 0
    assert bot.stats.skipped == 1


def test_rich_base_attacked():
    game = FakeGame([Screen.BASE_PREVIEW], loot=RICH)
    bot, _ = make_bot(game)
    bot.tick()
    assert game.count("deploy_army") == 1 and bot.stats.attacks == 1


def test_unreadable_loot_skipped():
    game = FakeGame([Screen.BASE_PREVIEW], loot=None)
    make_bot(game)[0].tick()
    assert game.count("next_base") == 1


def test_attacks_after_max_next():
    game = FakeGame([Screen.BASE_PREVIEW], loot=POOR)
    bot, _ = make_bot(game, settings=with_loot(max_next=3))
    for _ in range(4):
        bot.tick()
    assert game.count("next_base") == 3 and game.count("deploy_army") == 1


def test_battle_ends_after_timeout():
    game = FakeGame([Screen.BATTLE])
    bot, _ = make_bot(game, settings=with_timing(battle_timeout_s=9))
    for _ in range(3):
        bot.tick()
    assert game.count("end_battle") == 0
    bot.tick()
    assert game.count("end_battle") == 1


def test_battle_ends_at_50_percent():
    game = FakeGame([Screen.BATTLE])
    game.damage_percent = 51
    bot, _ = make_bot(game)
    bot.tick()
    assert game.count("end_battle") == 1


def test_battle_ends_on_stagnant_damage():
    game = FakeGame([Screen.BATTLE])
    bot, clock = make_bot(game, settings=with_timing(damage_stagnant_s=5.0))
    bot.tick()  # start battle at t=0
    assert game.count("end_battle") == 0
    clock.sleep(10)  # elapsed 10s, no damage increase
    bot.tick()
    assert game.count("end_battle") == 1


@pytest.mark.parametrize("screen, call", [
    (Screen.RESULT, "return_home"),
    (Screen.POPUP, "dismiss_popup"),
    (Screen.ARMY, "close_army"),
])
def test_simple_handlers(screen, call):
    game = FakeGame([screen])
    make_bot(game)[0].tick()
    assert game.count(call) == 1


def test_rest_at_home():
    game = FakeGame([Screen.HOME])
    policy = FakePolicy(rest=True, rest_s=600)
    bot, clock = make_bot(game, policy=policy)
    bot.tick()
    assert policy.events == ["end", "start"]
    assert clock.slept == [600]
    assert game.count("open_attack_menu") == 0


def test_repeated_action_screen_triggers_back():
    game = FakeGame([Screen.ATTACK_MENU])
    bot, _ = make_bot(game)
    for _ in range(6):
        bot.tick()
    assert game.count("find_match") == 5
    assert game.count("go_back") == 1
    assert bot.stats.recoveries == 1


def test_stuck_unknown_escalates_to_fatal():
    game = FakeGame([Screen.UNKNOWN])
    bot, _ = make_bot(game, settings=with_timing(stuck_timeout_s=60, max_restarts=3))
    with pytest.raises(FatalError):
        bot.run(max_ticks=1000)
    assert game.count("go_back") == 1
    assert game.count("restart_game") == 3
    assert game.count("save_debug_screenshot") == 5  # back + 3 restarts + the fatal one; none on entering UNKNOWN


def test_progress_screen_resets_escalation():
    screens = ([Screen.UNKNOWN] * 32 + [Screen.HOME, Screen.ATTACK_MENU]
               + [Screen.UNKNOWN] * 40)
    game = FakeGame(screens)
    bot, _ = make_bot(game, settings=with_timing(stuck_timeout_s=60))
    for _ in range(len(screens)):
        bot.tick()
    assert game.count("go_back") == 2
    assert game.count("restart_game") == 0


def test_home_without_forward_progress_trips_watchdog():
    game = FakeGame([Screen.HOME])  # army ready, open_attack_menu "succeeds", screen never moves
    bot, clock = make_bot(game, settings=with_timing(progress_timeout_s=900))
    for _ in range(300):
        bot.tick()
    assert game.count("go_back") == 0
    for _ in range(500):
        bot.tick()
    assert game.count("go_back") == 1
    assert bot.stats.recoveries == 1
    for _ in range(700):
        bot.tick()
    assert game.count("restart_game") >= 1


def test_restart_does_not_consume_stuck_timer():
    game = FakeGame([Screen.UNKNOWN])
    bot, clock = make_bot(game, settings=with_timing(stuck_timeout_s=60, max_restarts=3))
    game.on_restart = lambda: clock.sleep(33)
    while game.count("restart_game") < 1:
        bot.tick()
    t0 = clock.current  # restart returned (33 s elapsed inside it)
    while game.count("restart_game") < 2:
        bot.tick()
    assert (clock.current - t0).total_seconds() >= 60


def test_unknown_entry_takes_no_screenshot():
    game = FakeGame([Screen.UNKNOWN])
    bot, _ = make_bot(game)
    bot.tick()
    assert game.count("save_debug_screenshot") == 0


def test_adb_errors_reconnect_then_fatal():
    game = FakeGame([Screen.HOME])
    game.fail_screen_times = 10
    bot, _ = make_bot(game)
    with pytest.raises(FatalError):
        bot.run(max_ticks=10)
    assert game.count("reconnect") == 3


def test_adb_error_recovers():
    game = FakeGame([Screen.HOME])
    game.fail_screen_times = 2
    bot, _ = make_bot(game)
    bot.run(max_ticks=4)
    assert game.count("reconnect") == 2
    assert game.count("open_attack_menu") == 2


def test_run_starts_play_and_stop_flag():
    game = FakeGame([Screen.HOME])
    policy = FakePolicy()
    bot, _ = make_bot(game, policy=policy)
    bot.stop()
    bot.run()
    assert policy.events == ["start", "end"]
    assert game.calls == []


def test_failed_home_action_triggers_recovery():
    game = FakeGame([Screen.HOME])
    game.failing = {"open_attack_menu"}
    bot, _ = make_bot(game)
    for _ in range(5):
        bot.tick()
    assert game.count("go_back") == 1


def test_failed_actions_escalate_to_restart():
    game = FakeGame([Screen.HOME])
    game.failing = {"open_attack_menu"}
    bot, _ = make_bot(game)
    for _ in range(10):
        bot.tick()
    assert game.count("go_back") == 1
    assert game.count("restart_game") == 1


def test_battle_overrun_recovers():
    game = FakeGame([Screen.BATTLE])
    bot, _ = make_bot(game, settings=with_timing(battle_timeout_s=9))
    bot.run(max_ticks=60)
    assert game.count("end_battle") >= 1
    assert game.count("go_back") >= 1


def test_run_ends_play_on_fatal():
    game = FakeGame([Screen.UNKNOWN])
    policy = FakePolicy()
    bot, _ = make_bot(game, policy=policy,
                      settings=with_timing(stuck_timeout_s=60, max_restarts=3))
    with pytest.raises(FatalError):
        bot.run(max_ticks=1000)
    assert policy.events[-1] == "end"
