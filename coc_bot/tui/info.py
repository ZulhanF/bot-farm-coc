"""System info for the dashboard's neofetch-style home page (gathered off the UI thread)."""
from __future__ import annotations

import platform
from dataclasses import dataclass, field

from coc_bot import __version__
from coc_bot import names as N
from coc_bot.config import Settings, load_settings
from coc_bot.control import EXPECTED_SHAPE, Paths, connect, load_templates


@dataclass
class SystemInfo:
    version: str = __version__
    python: str = platform.python_version()
    os: str = f"{platform.system()} {platform.release()}"
    settings_error: str | None = None
    serial: str = "-"
    online: bool = False
    adb_error: str | None = None
    resolution: tuple[int, int] | None = None
    screen: str | None = None
    missing: list[str] = field(default_factory=list)
    storage: dict[str, float | None] = field(default_factory=dict)
    storage_checks: list[str] = field(default_factory=list)
    full_ratio: float = 0.95
    on_full: str = "stop"
    pattern: str = "-"
    troop_slots: tuple[int, ...] = ()
    spell_slots: tuple[int, ...] = ()
    min_loot: tuple[int, int, int] = (0, 0, 0)
    session: str = "off"

    @property
    def resolution_ok(self) -> bool:
        return self.resolution == (EXPECTED_SHAPE[1], EXPECTED_SHAPE[0])


def describe_settings(info: SystemInfo, settings: Settings) -> None:
    info.serial = settings.adb.serial
    info.storage_checks = N.storage_checks(settings)
    info.full_ratio = settings.storage.full_ratio
    info.on_full = settings.storage.on_full
    info.pattern = settings.deploy.pattern
    info.troop_slots = settings.deploy.troop_slots
    info.spell_slots = settings.spells.slots
    info.min_loot = (settings.loot.min_gold, settings.loot.min_elixir, settings.loot.min_de)
    s = settings.session
    info.session = (f"on, {s.active_hours[0]}-{s.active_hours[1]}, maks {s.max_hours_per_day:g} jam/hari"
                    if s.enabled else "off")


def gather(paths: Paths, probe_emulator: bool = True) -> SystemInfo:
    """Read config and (optionally) take one screenshot to check the emulator. Never raises."""
    info = SystemInfo()
    try:
        settings = load_settings(paths.settings, paths.calibration)
        templates = load_templates(paths, settings)
    except (ValueError, OSError) as exc:
        info.settings_error = str(exc)
        return info
    describe_settings(info, settings)
    info.missing = N.missing_calibration(settings, set(templates.names()))
    if not probe_emulator:
        return info
    try:
        image = connect(settings).screencap()
    except Exception as exc:  # noqa: BLE001 - shown in the dashboard, never fatal
        info.adb_error = str(exc)
        return info
    from coc_bot.vision.report import bar_levels
    from coc_bot.vision.screens import Screen, detect_screen

    info.online = True
    info.resolution = (image.shape[1], image.shape[0])
    screen = detect_screen(image, templates)
    info.screen = screen.name
    if screen is Screen.HOME:   # the resource bars are only on the home village
        info.storage = bar_levels(image, settings)
    return info
