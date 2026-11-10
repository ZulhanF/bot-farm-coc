import csv
from datetime import datetime

from coc_bot.bot.records import FIELDS, CsvRecorder


def test_writes_header_once_and_rows(tmp_path):
    rec = CsvRecorder(tmp_path)
    row = {"time": datetime(2026, 11, 11, 9, 30), "cycle_s": 42.345, "battle_s": 20.0,
           "damage_pct": 55, "preview_gold": 400000, "preview_elixir": None}
    rec(row)
    rec(row)
    path = tmp_path / "attacks-2026-11-11.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert len(rows) == 2
    assert tuple(rows[0]) == FIELDS
    assert rows[0]["time"] == "2026-11-11T09:30:00"
    assert rows[0]["cycle_s"] == "42.3"
    assert rows[0]["preview_elixir"] == ""
