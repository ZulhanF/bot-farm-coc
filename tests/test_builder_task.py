import random
from dataclasses import replace

import pytest

from coc_bot.bot.builder_task import BuilderFarmTask
from coc_bot.bot.engine import FatalError, ScreenLoop
from coc_bot.config import BuilderConfig
from coc_bot.vision.screens import Screen
from tests.fakes import FakeBuilderGame, FakeClock, FakePolicy, make_settings


def make(screens, mode="elixir", recorder=None, policy=None, **builder):
    settings = replace(make_settings(), builder=BuilderConfig(mode=mode, **builder))
    clock = FakeClock()
    game = FakeBuilderGame(screens)
    task = BuilderFarmTask(recorder=recorder)
    loop = ScreenLoop(game, task, policy or FakePolicy(), settings, random.Random(0),
                      clock=clock.now, sleep=clock.sleep)
    return loop, game, task, clock


def test_mode_comes_from_settings_or_override():
    loop, _, task, _ = make([Screen.BB_HOME], mode="gold")
    assert task.mode == "gold"
    settings = replace(make_settings(), builder=BuilderConfig(mode="gold"))
    override = BuilderFarmTask(mode="elixir")
    ScreenLoop(FakeBuilderGame([Screen.BB_HOME]), override, FakePolicy(), settings, random.Random(0),
               clock=FakeClock().now, sleep=FakeClock().sleep)
    assert override.mode == "elixir"


def test_unknown_override_rejected():
    with pytest.raises(ValueError):
        ScreenLoop(FakeBuilderGame([Screen.BB_HOME]), BuilderFarmTask(mode="dark"), FakePolicy(),
                   make_settings(), random.Random(0), clock=FakeClock().now, sleep=FakeClock().sleep)


def test_home_village_takes_the_boat():
    loop, game, _, _ = make([Screen.HOME])
    loop.tick()
    assert game.count("go_to_builder_base") == 1


def test_missing_boat_is_fatal_after_three_tries():
    loop, game, _, _ = make([Screen.HOME])
    game.failing.add("go_to_builder_base")
    loop.tick()
    loop.tick()
    with pytest.raises(FatalError, match="bb_boat"):
        loop.tick()


def test_first_builder_home_collects_cart_then_attacks():
    loop, game, _, _ = make([Screen.BB_HOME])
    loop.tick()
    assert game.count("collect_cart") == 1 and game.count("open_attack") == 0
    assert loop.stats.carts == 1
    loop.tick()
    assert game.count("open_attack") == 1


def test_elixir_prep_drops_one_troop_and_surrenders():
    loop, game, _, _ = make([Screen.BB_PREP])
    loop.tick()
    assert game.calls == ["drop_one_troop", "surrender"]
    assert loop.stats.attacks == 1


def test_elixir_battle_surrenders_again():
    loop, game, _, _ = make([Screen.BB_BATTLE])
    loop.tick()
    assert game.count("surrender") == 1


def test_cart_collected_every_n_attacks():
    loop, game, task, _ = make([Screen.BB_HOME], cart_every=3)
    loop.tick()                       # first visit: collect
    for _ in range(3):                # three attacks, each ending on the result screen
        task._on_prep(loop.clock())
        task._on_result(loop.clock())
    loop.tick()
    assert game.count("collect_cart") == 2
    loop.tick()
    assert game.count("open_attack") == 1


def test_failed_cart_retried_after_next_attack():
    loop, game, task, _ = make([Screen.BB_HOME], cart_every=3)
    game.failing.add("collect_cart")
    loop.tick()
    assert loop.stats.carts == 0
    loop.tick()
    assert game.count("open_attack") == 1      # no retry before the next attack
    task._on_prep(loop.clock())
    game.failing.clear()
    loop.tick()
    assert game.count("collect_cart") == 2 and loop.stats.carts == 1


def test_result_records_and_returns_home():
    rows = []
    loop, game, task, _ = make([Screen.BB_RESULT], recorder=rows.append)
    game.result_gold = 1234
    task._on_prep(loop.clock())
    loop.tick()
    assert game.count("return_home") == 1
    assert rows[0]["mode"] == "elixir" and rows[0]["gold"] == 1234 and rows[0]["stage2"] is False


def test_rest_on_builder_home():
    policy = FakePolicy(rest=True, rest_s=600)
    loop, game, _, clock = make([Screen.BB_HOME], policy=policy)
    loop.tick()
    assert clock.slept == [600]
    assert game.count("collect_cart") == 0


def test_restart_lands_on_home_and_boats_back():
    loop, game, _, _ = make([Screen.UNKNOWN])
    game.on_restart = lambda: game.screens.__setitem__(slice(None), [Screen.HOME])
    loop._recover_level = 1          # skip Back, go straight to a restart
    loop._recover(Screen.UNKNOWN)
    loop.tick()
    assert game.count("restart_game") == 1 and game.count("go_to_builder_base") == 1


def gold(screens, **kw):
    return make(screens, mode="gold", **kw)


def test_gold_prep_deploys_stage1():
    loop, game, task, _ = gold([Screen.BB_PREP])
    loop.tick()
    assert game.stages == [1] and game.count("surrender") == 0
    assert loop.stats.attacks == 1


def test_gold_battle_fires_hero_ability_on_interval():
    loop, game, task, clock = gold([Screen.BB_BATTLE], ability_every_s=3.0)
    task._start_stage(1)
    loop.tick()                 # t=0: first ability tap
    loop.tick()                 # t=2: too soon
    loop.tick()                 # t=4: again
    assert game.count("hero_ability") == 2


def test_gold_battle_bat_swarm_once():
    loop, game, task, _ = gold([Screen.BB_BATTLE], bat_swarm_after_s=3.0)
    task._start_stage(1)
    for _ in range(5):
        loop.tick()
    assert game.count("troop_abilities") == 1


def test_gold_battle_ends_on_stagnant_damage():
    loop, game, task, _ = gold([Screen.BB_BATTLE], damage_stagnant_s=6.0)
    game.damage = [10, 20, 30]  # then stays at 30
    task._start_stage(1)
    for _ in range(4):
        loop.tick()             # t=0..6, damage rises until t=4
    assert game.count("surrender") == 0
    for _ in range(4):
        loop.tick()             # t=8..14, 30% for > 6 s
    assert game.count("surrender") >= 1
    assert task._last_damage == 30


def test_gold_battle_without_damage_reading_waits_for_timeout():
    loop, game, task, _ = gold([Screen.BB_BATTLE], battle_timeout_s=20, damage_stagnant_s=4.0)
    task._start_stage(1)
    for _ in range(10):         # t=0..18
        loop.tick()
    assert game.count("surrender") == 0
    loop.tick()                 # t=20
    assert game.count("surrender") == 1


def test_stage2_prep_deploys_stage2():
    loop, game, task, _ = gold([Screen.BB_STAGE2_PREP])
    task._on_prep(loop.clock())          # stage 1 of this battle
    loop.tick()
    assert game.stages == [1, 2] and loop.stats.stage2 == 1


def test_stage2_off_ends_battle():
    loop, game, task, _ = gold([Screen.BB_STAGE2_PREP], stage2=False)
    task._on_prep(loop.clock())          # stage 1 of this battle
    loop.tick()
    assert game.stages == [1] and game.count("surrender") == 1


def test_stage2_recorded_in_result():
    rows = []
    loop, game, task, _ = gold([Screen.BB_RESULT], recorder=rows.append)
    task._on_prep(loop.clock())
    task._on_stage2_prep(loop.clock())
    loop.tick()
    assert rows[0]["stage2"] is True and rows[0]["mode"] == "gold"


def test_gold_battle_overrun_triggers_recovery():
    loop, game, task, clock = gold([Screen.BB_BATTLE], battle_timeout_s=10)
    task._start_stage(1)
    clock.sleep(10 + 121)
    loop.tick()
    assert game.count("go_back") == 1 and loop.stats.recoveries == 1


def test_prep_seen_twice_counts_one_attack_and_retries_deploy():
    loop, game, task, _ = make([Screen.BB_PREP])
    loop.tick()
    loop.tick()
    assert loop.stats.attacks == 1
    assert game.count("drop_one_troop") == 2


def test_next_battle_counts_again_after_result():
    loop, game, task, _ = make([Screen.BB_PREP, Screen.BB_RESULT, Screen.BB_PREP])
    loop.tick()
    loop.tick()
    loop.tick()
    assert loop.stats.attacks == 2


def test_battle_after_recovery_takes_stage_from_the_map():
    loop, game, task, _ = gold([Screen.BB_BATTLE])
    game.stage_seen = 2
    loop.tick()                 # no stage started (e.g. after a recovery)
    assert task._stage == 2


def test_stage2_prep_before_any_stage1_is_treated_as_stage1():
    # search clouds are dark blue: the first prep of a battle can look like stage 2
    loop, game, task, _ = gold([Screen.BB_STAGE2_PREP])
    loop.tick()
    assert game.stages == [1] and loop.stats.attacks == 1 and loop.stats.stage2 == 0


def test_real_stage2_after_stage1():
    loop, game, task, _ = gold([Screen.BB_PREP, Screen.BB_STAGE2_PREP])
    loop.tick()
    loop.tick()
    assert game.stages == [1, 2] and loop.stats.stage2 == 1
