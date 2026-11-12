"""Render README screenshots of the dashboard with demo data (no emulator needed).

    .venv\\Scripts\\python scripts\\dashboard_screenshots.py
"""
from __future__ import annotations

import asyncio
import random
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from coc_bot.bot.records import CsvRecorder  # noqa: E402
from coc_bot.bot.state_machine import Stats  # noqa: E402
from coc_bot.control import BotRunner, Paths, State, Status  # noqa: E402
from coc_bot.tui import pages  # noqa: E402
from coc_bot.tui.app import DashboardApp  # noqa: E402
from coc_bot.tui.info import SystemInfo  # noqa: E402

SIZE = (132, 34)
OUT = ROOT / "assets"
NOW = datetime.now().replace(hour=14, minute=25, second=10, microsecond=0)


def demo_info(paths: Paths, probe: bool = True) -> SystemInfo:
    return SystemInfo(
        serial="127.0.0.1:5555", online=True, resolution=(1280, 720), screen="HOME",
        storage={"gold": 0.62, "elixir": 0.48, "de": 0.81}, storage_checks=["gold", "elixir", "de"],
        pattern="v_top", troop_slots=(1,), spell_slots=(6,), min_loot=(0, 0, 0),
        session="on, 08:00-23:00, maks 10 jam/hari", os="Windows 11",
    )


class DemoRunner(BotRunner):
    def __init__(self, paths: Paths) -> None:
        super().__init__(paths)
        self._demo_state = State.IDLE

    @property
    def active(self) -> bool:
        return self._demo_state is State.RUNNING

    def status(self) -> Status:
        if self._demo_state is State.IDLE:
            return Status(State.IDLE, self.mode)
        return Status(State.RUNNING, self.mode, "BATTLE", datetime.now() - timedelta(minutes=47, seconds=12),
                      Stats(attacks=61, skipped=3, recoveries=1))


DEMO_LOG = [
    "Attacking (loot ok) Loot(gold=0, elixir=0, de=0) after 0 skips",
    "Spells cast (slots [6])",
    "Battle damage: 31%",
    "Battle damage: 44%",
    "Battle damage: 53%",
    "Target 50% reached (53%)! Ending battle immediately for rank win.",
    "Battle finished: damage 53%, cycle 41s. Stats(attacks=60, skipped=3, recoveries=1, restarts=0) | 77 attacks/h",
    "Storage: gold 62%, elixir 48%, de 81%",
    "Opening attack menu",
    "Attacking (loot ok) Loot(gold=0, elixir=0, de=0) after 0 skips",
    "Spells cast (slots [6])",
    "Battle damage: 38%",
]


def demo_logs(directory: Path) -> None:
    rng = random.Random(7)
    rec = CsvRecorder(directory)
    t = NOW.replace(hour=8, minute=5)
    while t < NOW:
        if 12 <= t.hour < 13:      # lunch break
            t = t.replace(hour=13, minute=4)
        damage = rng.choice([50, 51, 52, 53, 54, 55, 57, 60, 38, 46])
        rec({"time": t, "cycle_s": rng.uniform(36, 55), "battle_s": rng.uniform(24, 38), "damage_pct": damage})
        t += timedelta(seconds=rng.uniform(38, 58))
    log = directory / f"bot-{datetime.now():%Y-%m-%d}.log"
    lines = [f"{datetime.now():%Y-%m-%d} 14:24:{10 + i:02d},000 INFO    coc_bot.bot.state_machine: {m}"
             for i, m in enumerate(DEMO_LOG)]
    lines.insert(3, f"{datetime.now():%Y-%m-%d} 14:24:12,500 WARNING coc_bot.bot.state_machine: "
                    "Stuck on POPUP, pressing Back")
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def shoot() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        logs = Path(tmp)
        demo_logs(logs)
        paths = Paths(ROOT / "settings.example.toml", ROOT / "calibration.toml", ROOT / "assets/templates", logs)
        pages.gather = demo_info
        runner = DemoRunner(paths)
        app = DashboardApp(paths, runner, probe_emulator=False)
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause(0.5)
            app.save_screenshot(str(OUT / "dashboard-home.svg"))

            runner._demo_state = State.RUNNING
            for i, message in enumerate(DEMO_LOG):
                app._log_lines.append(f"14:24:{10 + i:02d} INFO    coc_bot.bot.state_machine: {message}")
            await pilot.press("2")
            await pilot.pause(0.8)
            app.save_screenshot(str(OUT / "dashboard-bot.svg"))

            await pilot.press("7")
            await pilot.pause(0.5)
            app.save_screenshot(str(OUT / "dashboard-stats.svg"))
            runner._demo_state = State.IDLE


if __name__ == "__main__":
    asyncio.run(shoot())
    print("Saved assets/dashboard-{home,bot,stats}.svg")
