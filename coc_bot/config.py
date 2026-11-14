"""Settings (settings.toml, hand-edited) and calibration data (calibration.toml, tool-written)."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

Box = tuple[int, int, int, int]  # x, y, w, h
Point = tuple[int, int]

_CAL_KINDS = ("templates", "rois", "points")


@dataclass(frozen=True)
class AdbConfig:
    serial: str = "127.0.0.1:5555"
    adb_path: str = ""
    package: str = "com.supercell.clashofclans"


@dataclass(frozen=True)
class LootConfig:
    min_gold: int = 300_000
    min_elixir: int = 300_000
    min_de: int = 0
    max_next: int = 50


@dataclass(frozen=True)
class DeployConfig:
    sides: int = 4
    points_per_side: int = 5
    taps_per_point: int = 2
    troop_slots: tuple[int, ...] = (1,)
    hero_slots: tuple[int, ...] = ()
    siege_slot: int = 0
    outward_px: int = 12
    max_y: int = 600
    pattern: str = "all"


@dataclass(frozen=True)
class SpellConfig:
    slots: tuple[int, ...] = ()  # spell card slots (calibrate troop_slot_N); empty = no spells
    casts: int = 2               # casts per slot, spread over the deploy wings (left, right, ...)
    delay_s: float = 5.0         # seconds after the troops are deployed
    depth: float = 0.35          # 0 = on the deploy line, 1 = at map_center (in front of the troops)


@dataclass(frozen=True)
class TimingConfig:
    tap_delay_ms: tuple[int, int] = (120, 350)
    tap_jitter_px: int = 4
    battle_timeout_s: int = 180
    stuck_timeout_s: int = 60
    damage_stagnant_s: float = 5.0
    max_restarts: int = 3
    progress_timeout_s: int = 900   # no forward progress for this long -> recover


@dataclass(frozen=True)
class StorageConfig:
    full_ratio: float = 0.95  # "full" = every calibrated resource bar is at least this full
    on_full: str = "stop"     # "stop" = end the run, "wait" = sleep wait_minutes then check again
    wait_minutes: int = 30


@dataclass(frozen=True)
class SessionConfig:
    enabled: bool = True
    play_minutes: tuple[int, int] = (40, 70)
    break_minutes: tuple[int, int] = (10, 25)
    active_hours: tuple[str, str] = ("08:00", "23:00")
    max_hours_per_day: float = 10.0


@dataclass(frozen=True)
class VisionConfig:
    threshold: float = 0.85
    search_margin_px: int = 40


BUILDER_MODES = ("elixir", "gold")
BB_MAX_SLOTS = 8


@dataclass(frozen=True)
class BuilderConfig:
    mode: str = "elixir"             # "elixir" = 1 troop + surrender, "gold" = hero + tank + Night Witch push
    cart_every: int = 15             # collect the Elixir Cart every N attacks (both modes)
    troop_slot: int = 1              # elixir: the card dropped before surrendering (hero: no swap button)
    surrender_after_s: float = 1.5
    hero_slot: int = 1               # gold: hero card (pick Battle Copter in the army screen)
    tank_slot: int = 2               # gold: Giant; 0 = no tank
    main_slots: tuple[int, ...] = (3, 4, 5, 6)   # gold: Night Witch cards
    taps_per_slot: int = 3           # taps on the deploy point per card (empties the card)
    witch_delay_s: float = 2.0       # wait after the tank before the Night Witches
    ability_every_s: float = 3.0     # tap the hero card this often (does nothing until charged)
    bat_swarm_after_s: float = 6.0   # tap the Night Witch cards once (Bat Swarm) after this long
    damage_stagnant_s: float = 12.0  # end the stage if the damage % stops rising this long
    battle_timeout_s: int = 150      # per stage (the game's own timer is 2 minutes)
    stage2: bool = True              # attack stage 2 when it appears
    stage2_slots: tuple[int, ...] = ()   # extra cards on stage 2 (Reinforcement Camp troops)

    def __post_init__(self) -> None:
        if self.mode not in BUILDER_MODES:
            raise ValueError(f"[builder] mode must be one of {', '.join(BUILDER_MODES)}, got {self.mode!r}")
        if self.cart_every < 1:
            raise ValueError("[builder] cart_every must be at least 1")
        slots = (self.troop_slot, self.hero_slot, *self.main_slots, *self.stage2_slots)
        if any(not 1 <= s <= BB_MAX_SLOTS for s in slots) or not 0 <= self.tank_slot <= BB_MAX_SLOTS:
            raise ValueError(f"[builder] card slots run from 1 to {BB_MAX_SLOTS} (tank_slot 0 = no tank)")


@dataclass(frozen=True)
class Calibration:
    templates: dict[str, Box] = field(default_factory=dict)
    rois: dict[str, Box] = field(default_factory=dict)
    points: dict[str, Point] = field(default_factory=dict)

    def with_entry(self, kind: str, name: str, value: tuple[int, ...]) -> Calibration:
        if kind not in _CAL_KINDS:
            raise ValueError(f"Unknown calibration kind: {kind}")
        updated = dict(getattr(self, kind))
        updated[name] = tuple(int(v) for v in value)
        return replace(self, **{kind: updated})


@dataclass(frozen=True)
class Settings:
    adb: AdbConfig = field(default_factory=AdbConfig)
    loot: LootConfig = field(default_factory=LootConfig)
    deploy: DeployConfig = field(default_factory=DeployConfig)
    spells: SpellConfig = field(default_factory=SpellConfig)
    timing: TimingConfig = field(default_factory=TimingConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    builder: BuilderConfig = field(default_factory=BuilderConfig)
    calibration: Calibration = field(default_factory=Calibration)


_SECTIONS: dict[str, type] = {
    "adb": AdbConfig,
    "loot": LootConfig,
    "deploy": DeployConfig,
    "spells": SpellConfig,
    "timing": TimingConfig,
    "session": SessionConfig,
    "storage": StorageConfig,
    "vision": VisionConfig,
    "builder": BuilderConfig,
}


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _build(name: str, cls: type, data: dict[str, Any]) -> Any:
    known = {f.name for f in fields(cls)}
    unknown = sorted(set(data) - known)
    if unknown:
        raise ValueError(f"Unknown key(s) in [{name}]: {', '.join(unknown)}")
    kwargs = {k: tuple(v) if isinstance(v, list) else v for k, v in data.items()}
    return cls(**kwargs)


def load_calibration(path: Path) -> Calibration:
    data = _read_toml(path)
    unknown = sorted(set(data) - set(_CAL_KINDS))
    if unknown:
        raise ValueError(f"Unknown section(s) in {path.name}: {', '.join(unknown)}")
    return Calibration(
        **{
            kind: {name: tuple(int(v) for v in value) for name, value in data.get(kind, {}).items()}
            for kind in _CAL_KINDS
        }
    )


def save_calibration(path: Path, cal: Calibration) -> None:
    lines: list[str] = []
    for kind in _CAL_KINDS:
        lines.append(f"[{kind}]")
        entries = getattr(cal, kind)
        for name in sorted(entries):
            values = ", ".join(str(int(v)) for v in entries[name])
            lines.append(f"{name} = [{values}]")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def load_settings(settings_path: Path, calibration_path: Path) -> Settings:
    data = _read_toml(settings_path)
    unknown = sorted(set(data) - set(_SECTIONS))
    if unknown:
        raise ValueError(f"Unknown section(s) in {settings_path.name}: {', '.join(unknown)}")
    sections = {name: _build(name, cls, data.get(name, {})) for name, cls in _SECTIONS.items()}
    return Settings(**sections, calibration=load_calibration(calibration_path))
