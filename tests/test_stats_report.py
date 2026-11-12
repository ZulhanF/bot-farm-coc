from datetime import date

from coc_bot.bot.records import CsvRecorder
from coc_bot.bot.stats_report import log_for, read_attacks, summarize
from datetime import datetime


def test_summary_from_csv(tmp_path):
    rec = CsvRecorder(tmp_path)
    rec({"time": datetime(2026, 11, 12, 8, 0, 0), "cycle_s": None, "battle_s": 30.0, "damage_pct": 55})
    rec({"time": datetime(2026, 11, 12, 8, 1, 0), "cycle_s": 40.0, "battle_s": 20.0, "damage_pct": 35})
    rec({"time": datetime(2026, 11, 12, 9, 0, 0), "cycle_s": 50.0, "battle_s": 25.0, "damage_pct": 50})
    attacks = read_attacks(log_for(tmp_path, date(2026, 11, 12)))
    s = summarize(attacks)
    assert s.attacks == 3 and s.wins == 2
    assert s.avg_cycle_s == 45.0
    assert s.avg_battle_s == 25.0
    assert s.per_hour[8] == 2 and s.per_hour[9] == 1
    assert round(s.win_rate, 2) == 0.67


def test_missing_or_bad_file(tmp_path):
    assert read_attacks(tmp_path / "nope.csv") == []
    bad = tmp_path / "attacks-2026-01-01.csv"
    bad.write_text("time,cycle_s\nnot-a-date,1\n", encoding="utf-8")
    assert read_attacks(bad) == []
    assert summarize([]).attacks == 0 and summarize([]).win_rate is None
