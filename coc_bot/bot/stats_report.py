"""Summaries of the per-attack CSV logs (logs/attacks-YYYY-MM-DD.csv) for the dashboard."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from statistics import mean

WIN_DAMAGE = 50  # the bot ends the battle at 50 %, which wins one star


@dataclass(frozen=True)
class Attack:
    time: datetime
    cycle_s: float | None
    battle_s: float | None
    damage_pct: int | None


@dataclass(frozen=True)
class Summary:
    attacks: int = 0
    wins: int = 0
    avg_cycle_s: float | None = None
    avg_battle_s: float | None = None
    avg_damage: float | None = None
    per_hour: list[int] = field(default_factory=lambda: [0] * 24)   # attacks in each hour of the day

    @property
    def win_rate(self) -> float | None:
        return self.wins / self.attacks if self.attacks else None


def _num(text: str | None) -> float | None:
    try:
        return float(text) if text not in (None, "") else None
    except ValueError:
        return None


def read_attacks(path: Path) -> list[Attack]:
    attacks = []
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                try:
                    when = datetime.fromisoformat(row["time"])
                except (KeyError, TypeError, ValueError):
                    continue
                damage = _num(row.get("damage_pct"))
                attacks.append(Attack(when, _num(row.get("cycle_s")), _num(row.get("battle_s")),
                                      None if damage is None else int(damage)))
    except OSError:
        return []
    return attacks


def attack_logs(log_dir: Path) -> list[Path]:
    return sorted(log_dir.glob("attacks-*.csv"))


def log_for(log_dir: Path, day: date) -> Path:
    return log_dir / f"attacks-{day:%Y-%m-%d}.csv"


def summarize(attacks: list[Attack]) -> Summary:
    if not attacks:
        return Summary()
    per_hour = [0] * 24
    for a in attacks:
        per_hour[a.time.hour] += 1

    def avg(values):
        values = [v for v in values if v is not None]
        return mean(values) if values else None

    return Summary(
        attacks=len(attacks),
        wins=sum(1 for a in attacks if a.damage_pct is not None and a.damage_pct >= WIN_DAMAGE),
        avg_cycle_s=avg(a.cycle_s for a in attacks),
        avg_battle_s=avg(a.battle_s for a in attacks),
        avg_damage=avg(a.damage_pct for a in attacks),
        per_hour=per_hour,
    )
