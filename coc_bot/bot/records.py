"""Per-attack CSV logs (logs/attacks-*.csv for the home village, logs/builder-*.csv for the Builder Base)."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

FIELDS = (
    "time", "cycle_s", "battle_s", "damage_pct",
    "preview_gold", "preview_elixir", "preview_de",
)


BUILDER_FIELDS = ("time", "mode", "cycle_s", "battle_s", "damage_pct", "gold", "stage2")


class CsvRecorder:
    def __init__(self, directory: Path, prefix: str = "attacks", fields: tuple[str, ...] = FIELDS) -> None:
        self.directory = directory
        self.prefix = prefix
        self.fields = fields

    def __call__(self, row: dict) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = row["time"] if isinstance(row["time"], datetime) else datetime.now()
        path = self.directory / f"{self.prefix}-{stamp:%Y-%m-%d}.csv"
        new_file = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=self.fields)
            if new_file:
                writer.writeheader()
            writer.writerow({k: _fmt(row.get(k)) for k in self.fields})


def _fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)
