import random
from datetime import datetime

from coc_bot.bot.session import SessionPolicy
from coc_bot.config import SessionConfig

CFG = SessionConfig(play_minutes=(40, 40), break_minutes=(10, 10),
                    active_hours=("08:00", "23:00"), max_hours_per_day=10.0)

NIGHT_CFG = SessionConfig(play_minutes=(40, 40), break_minutes=(10, 10),
                          active_hours=("22:00", "06:00"), max_hours_per_day=1.0)


def dt(h, m=0, day=10):
    return datetime(2026, 11, day, h, m)


def policy(cfg=CFG):
    return SessionPolicy(cfg, random.Random(0))


def test_active_hours():
    p = policy()
    assert p.in_active_hours(dt(8))
    assert p.in_active_hours(dt(22, 59))
    assert not p.in_active_hours(dt(23))
    assert not p.in_active_hours(dt(7, 59))


def test_overnight_window():
    cfg = SessionConfig(play_minutes=(40, 40), break_minutes=(10, 10),
                        active_hours=("22:00", "06:00"), max_hours_per_day=10.0)
    p = policy(cfg)
    assert p.in_active_hours(dt(23))
    assert p.in_active_hours(dt(5))
    assert not p.in_active_hours(dt(12))


def test_should_rest_after_play_duration():
    p = policy()
    p.start_play(dt(9))
    assert not p.should_rest(dt(9, 39))
    assert p.should_rest(dt(9, 40))


def test_not_resting_before_play_started_inside_hours():
    assert not policy().should_rest(dt(9))


def test_break_length():
    p = policy()
    p.start_play(dt(9))
    p.end_play(dt(9, 40))
    assert p.rest_seconds(dt(9, 40)) == 600


def test_rest_until_window_after_hours():
    p = policy()
    assert p.should_rest(dt(23, 30))
    assert p.rest_seconds(dt(23, 30)) == 8.5 * 3600


def test_rest_until_window_before_hours():
    assert policy().rest_seconds(dt(6)) == 2 * 3600


def test_daily_cap():
    cfg = SessionConfig(play_minutes=(40, 40), break_minutes=(10, 10),
                        active_hours=("08:00", "23:00"), max_hours_per_day=1.0)
    p = policy(cfg)
    p.start_play(dt(9))
    p.end_play(dt(9, 40))
    p.start_play(dt(10))
    assert p.played_seconds(dt(10, 20)) == 3600
    assert p.should_rest(dt(10, 20))
    p.end_play(dt(10, 20))
    assert p.rest_seconds(dt(10, 20)) == (21 * 60 + 40) * 60


def test_overnight_cap_counts_across_midnight():
    p = policy(NIGHT_CFG)
    p.start_play(dt(23, 30, day=10))
    assert p.played_seconds(dt(0, 30, day=11)) == 3600
    assert p.should_rest(dt(0, 30, day=11))


def test_overnight_cap_rests_until_next_night():
    p = policy(NIGHT_CFG)
    p.start_play(dt(23, 30, day=10))
    p.end_play(dt(0, 30, day=11))
    assert p.rest_seconds(dt(0, 30, day=11)) == 21.5 * 3600
    assert not p.should_rest(dt(22, 0, day=11))


def test_overnight_outside_hours_rest():
    assert policy(NIGHT_CFG).rest_seconds(dt(12, 0, day=11)) == 10 * 3600


def test_disabled_session_never_rests():
    from dataclasses import replace
    disabled_p = policy(replace(CFG, enabled=False))
    # Outside active hours
    assert not disabled_p.should_rest(dt(4))
    assert not disabled_p.should_rest(dt(23))

