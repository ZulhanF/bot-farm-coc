# CoC Auto-Farm v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Clash of Clans goblin/barch farming bot for LDPlayer that trains, searches, evaluates loot, attacks, returns home and recovers from errors unattended.

**Architecture:** Screen-driven loop: each tick takes an ADB screenshot, identifies the current screen with OpenCV template matching, and runs the handler for that screen. Loot is read with RapidOCR from fixed ROIs. Template boxes, loot ROIs, map corners and troop slots are captured by the user with a `calibrate` command. All vision/decision logic is pure and unit-tested with fakes (no emulator needed).

**Tech Stack:** Python 3.12, opencv-python, numpy, rapidocr_onnxruntime (ONNX on CPU), pytest, ADB (bundled with LDPlayer).

**Spec:** `docs/superpowers/specs/2026-11-10-coc-auto-farm-design.md`

## Global Constraints

- Python **3.12** in `.venv` (system Python 3.14 is NOT used).
- Windows 11; LDPlayer 9 at **1280×720, 240 DPI**, ADB local connection enabled, default serial `127.0.0.1:5555`.
- Runtime dependencies are only: `opencv-python`, `numpy`, `rapidocr_onnxruntime`. Test dependency: `pytest`. No PyTorch, no YOLO in v1.
- Only `coc_bot/device/adb.py` invokes ADB. `coc_bot/vision/*` never touches ADB.
- All unit tests run without an emulator.
- Single emulator instance, goblin/barch edge deployment on the home village only.
- CoC package name: `com.supercell.clashofclans`.
- Commands below are for Git Bash from the project root `D:\Bot Farm COC` (drive C: is nearly full — never write caches or installs to C:).
- `.venv` (Python 3.12.13, created by uv with interpreter in `.python/`) already exists. Install packages with `--no-cache-dir`.

## File Map

| File | Responsibility |
|---|---|
| `coc_bot/config.py` | `Settings` dataclasses, `load_settings`, `Calibration`, `load_calibration`, `save_calibration` |
| `coc_bot/names.py` | Template/ROI/point name constants, `missing_calibration`, `valid_names` |
| `coc_bot/device/adb.py` | `EmulatorAdb`, `AdbError`, `find_adb` |
| `coc_bot/vision/templates.py` | `Match`, `TemplateLibrary` |
| `coc_bot/vision/ocr.py` | `OcrReader`, `parse_number`, `rapidocr_engine` |
| `coc_bot/vision/screens.py` | `Screen` enum, `detect_screen` |
| `coc_bot/game/loot.py` | `Loot`, `is_worth_attacking` |
| `coc_bot/game/deploy.py` | `edge_points` |
| `coc_bot/game/actions.py` | `Game` (high-level actions on top of adb + vision) |
| `coc_bot/bot/session.py` | `SessionPolicy` (active hours, play/break, daily cap) |
| `coc_bot/bot/state_machine.py` | `Bot`, `FatalError`, `Stats` |
| `coc_bot/logs.py` | `setup_logging` |
| `coc_bot/main.py`, `coc_bot/__main__.py` | CLI: `run`, `check`, `screenshot`, `test-vision`, `calibrate` |
| `tests/fakes.py` | Shared fakes: `FakeTemplates`, `FakeAdb`, `FakeOcr`, `make_settings`, `FakeClock`, `FakeGame`, `FakePolicy` |

---

### Task 1: Project scaffold + configuration

**Files:**
- Create: `requirements.txt`, `pyproject.toml`, `.gitignore`, `settings.example.toml`
- Create (empty): `coc_bot/__init__.py`, `coc_bot/device/__init__.py`, `coc_bot/vision/__init__.py`, `coc_bot/game/__init__.py`, `coc_bot/bot/__init__.py`, `tests/__init__.py`
- Create: `coc_bot/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Box = tuple[int, int, int, int]` (x, y, w, h), `Point = tuple[int, int]`
  - Frozen dataclasses `AdbConfig(serial, adb_path, package)`, `LootConfig(min_gold, min_elixir, min_de, max_next)`, `DeployConfig(sides, points_per_side, taps_per_point, troop_slots, outward_px, max_y)`, `TimingConfig(tap_delay_ms, tap_jitter_px, battle_timeout_s, stuck_timeout_s, army_poll_s, max_restarts)`, `SessionConfig(play_minutes, break_minutes, active_hours, max_hours_per_day)`, `VisionConfig(threshold, search_margin_px)`
  - `Calibration(templates: dict[str, Box], rois: dict[str, Box], points: dict[str, Point])` with `with_entry(kind: str, name: str, value: tuple[int, ...]) -> Calibration`
  - `Settings(adb, loot, deploy, timing, session, vision, calibration)`
  - `load_settings(settings_path: Path, calibration_path: Path) -> Settings`
  - `load_calibration(path: Path) -> Calibration`, `save_calibration(path: Path, cal: Calibration) -> None`

- [ ] **Step 1: Verify the existing venv**

Run: `.venv/Scripts/python --version`
Expected: `Python 3.12.13` (already created — do NOT recreate it)

- [ ] **Step 2: Create repo and scaffold files**

```bash
git init
mkdir -p coc_bot/device coc_bot/vision coc_bot/game coc_bot/bot tests assets/templates
touch coc_bot/__init__.py coc_bot/device/__init__.py coc_bot/vision/__init__.py coc_bot/game/__init__.py coc_bot/bot/__init__.py tests/__init__.py
```

`requirements.txt`:
```
opencv-python>=4.9,<5
numpy>=1.26,<3
rapidocr_onnxruntime>=1.3,<2
pytest>=8
```

`pyproject.toml`:
```toml
[project]
name = "coc-bot"
version = "0.1.0"
requires-python = ">=3.12,<3.13"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

`.gitignore`:
```
.venv/
.python/
.uv-cache/
__pycache__/
.pytest_cache/
logs/
settings.toml
```

`settings.example.toml`:
```toml
# Copy to settings.toml and adjust. Every key is optional; defaults are shown.

[adb]
serial = "127.0.0.1:5555"
adb_path = ""            # empty = auto-detect (LDPlayer folder, then PATH)
package = "com.supercell.clashofclans"

[loot]
min_gold = 300000
min_elixir = 300000
min_de = 0
max_next = 50            # after this many skips, attack the current base anyway

[deploy]
sides = 4                # how many diamond edges to deploy along (1-4)
points_per_side = 5
taps_per_point = 2
troop_slots = [1]        # troop card slots to deploy (calibrate troop_slot_N for each)
outward_px = 12          # push deploy points this far outside the map edge
max_y = 600              # never tap below this y (troop bar)

[timing]
tap_delay_ms = [120, 350]
tap_jitter_px = 4
battle_timeout_s = 180
stuck_timeout_s = 60
army_poll_s = [60, 120]
max_restarts = 3

[session]
play_minutes = [40, 70]
break_minutes = [10, 25]
active_hours = ["08:00", "23:00"]
max_hours_per_day = 10.0

[vision]
threshold = 0.85
search_margin_px = 40
```

Install dependencies:
```bash
.venv/Scripts/python -m pip install --no-cache-dir -r requirements.txt
```
Expected: ends with `Successfully installed ...` (no errors).

- [ ] **Step 3: Write the failing test**

`tests/test_config.py`:
```python
import pytest

from coc_bot.config import Calibration, load_calibration, load_settings, save_calibration


def test_defaults_when_files_missing(tmp_path):
    s = load_settings(tmp_path / "missing.toml", tmp_path / "missing_cal.toml")
    assert s.adb.serial == "127.0.0.1:5555"
    assert s.loot.max_next == 50
    assert s.timing.tap_delay_ms == (120, 350)
    assert s.deploy.troop_slots == (1,)
    assert s.calibration.rois == {}


def test_overrides_from_toml(tmp_path):
    path = tmp_path / "settings.toml"
    path.write_text("[loot]\nmin_gold = 123\n[deploy]\ntroop_slots = [1, 2]\n", encoding="utf-8")
    s = load_settings(path, tmp_path / "cal.toml")
    assert s.loot.min_gold == 123
    assert s.loot.min_elixir == 300_000
    assert s.deploy.troop_slots == (1, 2)


def test_unknown_key_raises(tmp_path):
    path = tmp_path / "settings.toml"
    path.write_text("[loot]\nmin_gld = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="min_gld"):
        load_settings(path, tmp_path / "cal.toml")


def test_unknown_section_raises(tmp_path):
    path = tmp_path / "settings.toml"
    path.write_text("[lot]\nx = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="lot"):
        load_settings(path, tmp_path / "cal.toml")


def test_calibration_roundtrip(tmp_path):
    cal = (
        Calibration()
        .with_entry("rois", "gold", (10, 20, 30, 40))
        .with_entry("points", "map_top", (640, 100))
    )
    path = tmp_path / "calibration.toml"
    save_calibration(path, cal)
    loaded = load_calibration(path)
    assert loaded.rois == {"gold": (10, 20, 30, 40)}
    assert loaded.points == {"map_top": (640, 100)}
    assert loaded.templates == {}


def test_with_entry_rejects_unknown_kind():
    with pytest.raises(ValueError):
        Calibration().with_entry("buttons", "x", (1, 2))


def test_calibration_loaded_into_settings(tmp_path):
    cal_path = tmp_path / "calibration.toml"
    save_calibration(cal_path, Calibration().with_entry("templates", "btn_next", (1, 2, 3, 4)))
    s = load_settings(tmp_path / "settings.toml", cal_path)
    assert s.calibration.templates == {"btn_next": (1, 2, 3, 4)}
```

- [ ] **Step 4: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'coc_bot.config'`

- [ ] **Step 5: Write implementation**

`coc_bot/config.py`:
```python
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
    outward_px: int = 12
    max_y: int = 600


@dataclass(frozen=True)
class TimingConfig:
    tap_delay_ms: tuple[int, int] = (120, 350)
    tap_jitter_px: int = 4
    battle_timeout_s: int = 180
    stuck_timeout_s: int = 60
    army_poll_s: tuple[int, int] = (60, 120)
    max_restarts: int = 3


@dataclass(frozen=True)
class SessionConfig:
    play_minutes: tuple[int, int] = (40, 70)
    break_minutes: tuple[int, int] = (10, 25)
    active_hours: tuple[str, str] = ("08:00", "23:00")
    max_hours_per_day: float = 10.0


@dataclass(frozen=True)
class VisionConfig:
    threshold: float = 0.85
    search_margin_px: int = 40


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
    timing: TimingConfig = field(default_factory=TimingConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    calibration: Calibration = field(default_factory=Calibration)


_SECTIONS: dict[str, type] = {
    "adb": AdbConfig,
    "loot": LootConfig,
    "deploy": DeployConfig,
    "timing": TimingConfig,
    "session": SessionConfig,
    "vision": VisionConfig,
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
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_config.py -v`
Expected: 7 passed

- [ ] **Step 7: Commit**

```bash
git add .gitignore requirements.txt pyproject.toml settings.example.toml coc_bot tests docs
git commit -m "feat: project scaffold and settings/calibration loading"
```

---

### Task 2: ADB device layer

**Files:**
- Create: `coc_bot/device/adb.py`
- Test: `tests/test_adb.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class AdbError(RuntimeError)`
  - `Runner = Callable[[list[str]], bytes]` (returns stdout, raises `AdbError` on failure)
  - `find_adb(explicit: str = "", candidates=LDPLAYER_ADB_CANDIDATES, which=shutil.which, exists=os.path.isfile) -> str`
  - `EmulatorAdb(adb_path: str, serial: str, run: Runner = subprocess_runner)` with `connect() -> None`, `screencap() -> np.ndarray` (BGR), `tap(x: int, y: int)`, `key_back()`, `start_app(package: str)`, `stop_app(package: str)`

- [ ] **Step 1: Write the failing test**

`tests/test_adb.py`:
```python
import cv2
import numpy as np
import pytest

from coc_bot.device.adb import AdbError, EmulatorAdb, find_adb

SERIAL = "127.0.0.1:5555"


class FakeRunner:
    def __init__(self, outputs=None):
        self.calls = []
        self.outputs = outputs or {}

    def __call__(self, args):
        self.calls.append(args)
        joined = " ".join(args[1:])
        for pattern, out in self.outputs.items():
            if pattern in joined:
                if isinstance(out, Exception):
                    raise out
                return out
        return b""


def make(outputs=None):
    runner = FakeRunner(outputs)
    return EmulatorAdb("adb.exe", SERIAL, run=runner), runner


def test_connect_ok():
    adb, runner = make({"connect": b"connected to 127.0.0.1:5555\n"})
    adb.connect()
    assert runner.calls[0] == ["adb.exe", "connect", SERIAL]


def test_connect_already_connected_ok():
    adb, _ = make({"connect": b"already connected to 127.0.0.1:5555\n"})
    adb.connect()


def test_connect_failure_raises():
    adb, _ = make({"connect": b"unable to connect to 127.0.0.1:5555\n"})
    with pytest.raises(AdbError):
        adb.connect()


def test_screencap_decodes_png():
    img = np.zeros((720, 1280, 3), np.uint8)
    img[10, 20] = (1, 2, 3)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    adb, runner = make({"screencap": buf.tobytes()})
    out = adb.screencap()
    assert out.shape == (720, 1280, 3)
    assert tuple(out[10, 20]) == (1, 2, 3)
    assert runner.calls[0] == ["adb.exe", "-s", SERIAL, "exec-out", "screencap", "-p"]


def test_screencap_invalid_bytes_raises():
    adb, _ = make({"screencap": b"not a png"})
    with pytest.raises(AdbError):
        adb.screencap()


def test_tap_args():
    adb, runner = make()
    adb.tap(100, 200)
    assert runner.calls[0] == ["adb.exe", "-s", SERIAL, "shell", "input", "tap", "100", "200"]


def test_key_back_args():
    adb, runner = make()
    adb.key_back()
    assert runner.calls[0] == ["adb.exe", "-s", SERIAL, "shell", "input", "keyevent", "4"]


def test_app_start_stop_args():
    adb, runner = make()
    adb.stop_app("com.x")
    adb.start_app("com.x")
    assert runner.calls[0] == ["adb.exe", "-s", SERIAL, "shell", "am", "force-stop", "com.x"]
    assert runner.calls[1] == [
        "adb.exe", "-s", SERIAL, "shell", "monkey", "-p", "com.x",
        "-c", "android.intent.category.LAUNCHER", "1",
    ]


def test_find_adb_explicit():
    assert find_adb("C:/x/adb.exe", exists=lambda p: True) == "C:/x/adb.exe"


def test_find_adb_explicit_missing_raises():
    with pytest.raises(AdbError):
        find_adb("C:/x/adb.exe", exists=lambda p: False)


def test_find_adb_candidate_then_path():
    assert find_adb(candidates=("C:/ld/adb.exe",), exists=lambda p: p == "C:/ld/adb.exe",
                    which=lambda n: None) == "C:/ld/adb.exe"
    assert find_adb(candidates=("C:/ld/adb.exe",), exists=lambda p: False,
                    which=lambda n: "C:/sdk/adb.exe") == "C:/sdk/adb.exe"


def test_find_adb_nothing_raises():
    with pytest.raises(AdbError):
        find_adb(candidates=(), exists=lambda p: False, which=lambda n: None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_adb.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'coc_bot.device.adb'`

- [ ] **Step 3: Write implementation**

`coc_bot/device/adb.py`:
```python
"""The only module that talks to the emulator (via adb.exe)."""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Callable

import cv2
import numpy as np

Runner = Callable[[list[str]], bytes]

LDPLAYER_ADB_CANDIDATES = (
    r"C:\LDPlayer\LDPlayer9\adb.exe",
    r"D:\LDPlayer\LDPlayer9\adb.exe",
    r"C:\Program Files\LDPlayer\LDPlayer9\adb.exe",
)


class AdbError(RuntimeError):
    """ADB command failed or the emulator is unreachable."""


def subprocess_runner(args: list[str]) -> bytes:
    try:
        proc = subprocess.run(args, capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AdbError(f"adb failed: {exc}") from exc
    if proc.returncode != 0:
        stderr = proc.stderr.decode(errors="replace").strip()
        raise AdbError(f"adb {' '.join(args[1:])} exited {proc.returncode}: {stderr}")
    return proc.stdout


def find_adb(
    explicit: str = "",
    candidates: tuple[str, ...] = LDPLAYER_ADB_CANDIDATES,
    which: Callable[[str], str | None] = shutil.which,
    exists: Callable[[str], bool] = os.path.isfile,
) -> str:
    if explicit:
        if exists(explicit):
            return explicit
        raise AdbError(f"adb_path not found: {explicit}")
    for candidate in candidates:
        if exists(candidate):
            return candidate
    found = which("adb")
    if found:
        return found
    raise AdbError("adb.exe not found; set [adb] adb_path in settings.toml")


class EmulatorAdb:
    def __init__(self, adb_path: str, serial: str, run: Runner = subprocess_runner) -> None:
        self.adb_path = adb_path
        self.serial = serial
        self._run = run

    def _cmd(self, *args: str) -> bytes:
        return self._run([self.adb_path, "-s", self.serial, *args])

    def connect(self) -> None:
        out = self._run([self.adb_path, "connect", self.serial]).decode(errors="replace")
        if "connected" not in out:
            raise AdbError(f"Cannot connect to {self.serial}: {out.strip()}")

    def screencap(self) -> np.ndarray:
        data = self._cmd("exec-out", "screencap", "-p")
        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise AdbError("screencap returned an invalid image")
        return image

    def tap(self, x: int, y: int) -> None:
        self._cmd("shell", "input", "tap", str(int(x)), str(int(y)))

    def key_back(self) -> None:
        self._cmd("shell", "input", "keyevent", "4")

    def start_app(self, package: str) -> None:
        self._cmd("shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1")

    def stop_app(self, package: str) -> None:
        self._cmd("shell", "am", "force-stop", package)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_adb.py -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add coc_bot/device/adb.py tests/test_adb.py
git commit -m "feat: ADB device layer"
```

---

### Task 3: Template matching

**Files:**
- Create: `coc_bot/vision/templates.py`
- Test: `tests/test_templates.py`

**Interfaces:**
- Consumes: `Box` from `coc_bot.config`.
- Produces:
  - `Match(name: str, x: int, y: int, w: int, h: int, score: float)` with property `center -> tuple[int, int]`
  - `TemplateLibrary(templates: dict[str, np.ndarray], boxes: dict[str, Box], threshold: float = 0.85, margin: int = 40)`
  - `TemplateLibrary.load(directory: Path, boxes: dict[str, Box], threshold: float, margin: int) -> TemplateLibrary` (missing directory → empty library)
  - `find(image: np.ndarray, name: str, threshold: float | None = None) -> Match | None`
  - `names() -> list[str]`

- [ ] **Step 1: Write the failing test**

`tests/test_templates.py`:
```python
import cv2
import numpy as np

from coc_bot.vision.templates import TemplateLibrary


def noise(seed):
    return np.random.default_rng(seed).integers(0, 256, (720, 1280, 3), dtype=np.uint8)


def save_template(directory, name, image, box):
    x, y, w, h = box
    cv2.imwrite(str(directory / f"{name}.png"), image[y:y + h, x:x + w])


def test_finds_template_inside_its_box(tmp_path):
    img = noise(0)
    box = (100, 200, 50, 40)
    save_template(tmp_path, "btn", img, box)
    lib = TemplateLibrary.load(tmp_path, {"btn": box}, threshold=0.85, margin=40)
    m = lib.find(img, "btn")
    assert m is not None
    assert (m.x, m.y, m.w, m.h) == (100, 200, 50, 40)
    assert m.center == (125, 220)
    assert m.score > 0.95


def test_finds_template_without_box_full_search(tmp_path):
    img = noise(1)
    save_template(tmp_path, "btn", img, (700, 500, 60, 30))
    lib = TemplateLibrary.load(tmp_path, {}, threshold=0.85, margin=40)
    m = lib.find(img, "btn")
    assert m is not None and (m.x, m.y) == (700, 500)


def test_box_limits_search_region(tmp_path):
    img = noise(2)
    save_template(tmp_path, "btn", img, (100, 200, 50, 40))
    lib = TemplateLibrary.load(tmp_path, {"btn": (900, 500, 50, 40)}, threshold=0.85, margin=40)
    assert lib.find(img, "btn") is None


def test_absent_template_returns_none(tmp_path):
    save_template(tmp_path, "btn", noise(3), (100, 200, 50, 40))
    lib = TemplateLibrary.load(tmp_path, {}, threshold=0.85, margin=40)
    assert lib.find(noise(4), "btn") is None


def test_threshold_override_returns_low_score_match(tmp_path):
    save_template(tmp_path, "btn", noise(3), (100, 200, 50, 40))
    lib = TemplateLibrary.load(tmp_path, {}, threshold=0.85, margin=40)
    m = lib.find(noise(4), "btn", threshold=-1.0)
    assert m is not None and m.score < 0.85


def test_unknown_name_returns_none(tmp_path):
    lib = TemplateLibrary.load(tmp_path, {}, threshold=0.85, margin=40)
    assert lib.find(noise(0), "nope") is None


def test_missing_directory_gives_empty_library(tmp_path):
    lib = TemplateLibrary.load(tmp_path / "nope", {}, threshold=0.85, margin=40)
    assert lib.names() == []


def test_names_sorted(tmp_path):
    img = noise(0)
    save_template(tmp_path, "b", img, (0, 0, 10, 10))
    save_template(tmp_path, "a", img, (20, 20, 10, 10))
    lib = TemplateLibrary.load(tmp_path, {}, threshold=0.85, margin=40)
    assert lib.names() == ["a", "b"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_templates.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'coc_bot.vision.templates'`

- [ ] **Step 3: Write implementation**

`coc_bot/vision/templates.py`:
```python
"""Grayscale template matching restricted to each template's calibrated box (+ margin)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from coc_bot.config import Box


@dataclass(frozen=True)
class Match:
    name: str
    x: int
    y: int
    w: int
    h: int
    score: float

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)


class TemplateLibrary:
    def __init__(
        self,
        templates: dict[str, np.ndarray],
        boxes: dict[str, Box],
        threshold: float = 0.85,
        margin: int = 40,
    ) -> None:
        self._templates = templates
        self._boxes = boxes
        self._threshold = threshold
        self._margin = margin

    @classmethod
    def load(cls, directory: Path, boxes: dict[str, Box], threshold: float, margin: int) -> TemplateLibrary:
        templates: dict[str, np.ndarray] = {}
        if directory.is_dir():
            for path in sorted(directory.glob("*.png")):
                image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
                if image is None:
                    raise ValueError(f"Cannot read template {path}")
                templates[path.stem] = image
        return cls(templates, boxes, threshold, margin)

    def names(self) -> list[str]:
        return sorted(self._templates)

    def find(self, image: np.ndarray, name: str, threshold: float | None = None) -> Match | None:
        template = self._templates.get(name)
        if template is None:
            return None
        gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        region, ox, oy = gray, 0, 0
        box = self._boxes.get(name)
        if box is not None:
            x, y, w, h = box
            m = self._margin
            x0, y0 = max(0, x - m), max(0, y - m)
            x1, y1 = min(gray.shape[1], x + w + m), min(gray.shape[0], y + h + m)
            region, ox, oy = gray[y0:y1, x0:x1], x0, y0
        th, tw = template.shape[:2]
        if region.shape[0] < th or region.shape[1] < tw:
            return None
        result = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        limit = self._threshold if threshold is None else threshold
        if max_val < limit:
            return None
        return Match(name, ox + max_loc[0], oy + max_loc[1], tw, th, float(max_val))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_templates.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add coc_bot/vision/templates.py tests/test_templates.py
git commit -m "feat: template matching library"
```

---

### Task 4: Loot OCR

**Files:**
- Create: `coc_bot/vision/ocr.py`
- Test: `tests/test_ocr.py`

**Interfaces:**
- Consumes: `Box` from `coc_bot.config`.
- Produces:
  - `OcrEngine = Callable[[np.ndarray], list[tuple[str, float]]]` (text, confidence)
  - `parse_number(texts: list[str]) -> int | None`
  - `OcrReader(engine: OcrEngine, min_confidence: float = 0.5)` with `read_number(image: np.ndarray, roi: Box, max_value: int) -> int | None`
  - `rapidocr_engine() -> OcrEngine` (imports RapidOCR lazily; not unit-tested)

- [ ] **Step 1: Write the failing test**

`tests/test_ocr.py`:
```python
import numpy as np

from coc_bot.vision.ocr import OcrReader, parse_number

IMG = np.zeros((720, 1280, 3), np.uint8)
ROI = (10, 10, 100, 20)


class FakeEngine:
    def __init__(self, results):
        self.results = results
        self.seen = []

    def __call__(self, image):
        self.seen.append(image)
        return self.results


def test_parse_number_ignores_separators():
    assert parse_number(["512 340"]) == 512340
    assert parse_number(["1,234,567"]) == 1234567
    assert parse_number([]) is None
    assert parse_number(["abc"]) is None


def test_parse_number_maps_common_confusions():
    assert parse_number(["1O5 l2"]) == 10512


def test_reads_number():
    assert OcrReader(FakeEngine([("512 340", 0.9)])).read_number(IMG, ROI, 5_000_000) == 512340


def test_joins_multiple_boxes_in_order():
    reader = OcrReader(FakeEngine([("1", 0.9), ("234 567", 0.95)]))
    assert reader.read_number(IMG, ROI, 5_000_000) == 1234567


def test_low_confidence_ignored():
    assert OcrReader(FakeEngine([("999", 0.2)])).read_number(IMG, ROI, 5_000_000) is None


def test_above_max_rejected():
    assert OcrReader(FakeEngine([("6000000", 0.9)])).read_number(IMG, ROI, 5_000_000) is None


def test_engine_receives_upscaled_bgr_crop():
    engine = FakeEngine([("1", 0.9)])
    OcrReader(engine).read_number(IMG, ROI, 10)
    assert engine.seen[0].shape == (60, 300, 3)


def test_roi_outside_image_returns_none():
    engine = FakeEngine([("1", 0.9)])
    assert OcrReader(engine).read_number(IMG, (2000, 2000, 10, 10), 10) is None
    assert engine.seen == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_ocr.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'coc_bot.vision.ocr'`

- [ ] **Step 3: Write implementation**

`coc_bot/vision/ocr.py`:
```python
"""Read loot numbers from fixed screen regions."""
from __future__ import annotations

from typing import Callable

import cv2
import numpy as np

from coc_bot.config import Box

OcrEngine = Callable[[np.ndarray], list[tuple[str, float]]]

_CONFUSIONS = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1"})
_UPSCALE = 3


def parse_number(texts: list[str]) -> int | None:
    digits = "".join(ch for text in texts for ch in text.translate(_CONFUSIONS) if ch.isdigit())
    return int(digits) if digits else None


def _preprocess(crop: np.ndarray) -> np.ndarray:
    big = cv2.resize(crop, None, fx=_UPSCALE, fy=_UPSCALE, interpolation=cv2.INTER_CUBIC)
    gray = big if big.ndim == 2 else cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


class OcrReader:
    def __init__(self, engine: OcrEngine, min_confidence: float = 0.5) -> None:
        self._engine = engine
        self._min_confidence = min_confidence

    def read_number(self, image: np.ndarray, roi: Box, max_value: int) -> int | None:
        x, y, w, h = roi
        crop = image[y:y + h, x:x + w]
        if crop.size == 0:
            return None
        texts = [text for text, conf in self._engine(_preprocess(crop)) if conf >= self._min_confidence]
        value = parse_number(texts)
        if value is None or value > max_value:
            return None
        return value


def rapidocr_engine() -> OcrEngine:
    from rapidocr_onnxruntime import RapidOCR  # heavy import, only when actually used

    engine = RapidOCR()

    def run(image: np.ndarray) -> list[tuple[str, float]]:
        result, _ = engine(image)
        if not result:
            return []
        return [(str(item[1]), float(item[2])) for item in result]

    return run
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_ocr.py -v`
Expected: 8 passed

- [ ] **Step 5: Smoke-check the real engine loads**

Run: `.venv/Scripts/python -c "from coc_bot.vision.ocr import rapidocr_engine; import numpy as np; print(rapidocr_engine()(np.full((60,300,3),255,np.uint8)))"`
Expected: prints `[]` (blank image, no text) without import errors.

- [ ] **Step 6: Commit**

```bash
git add coc_bot/vision/ocr.py tests/test_ocr.py
git commit -m "feat: loot OCR reader"
```

---

### Task 5: Shared names + screen detection

**Files:**
- Create: `coc_bot/names.py`, `coc_bot/vision/screens.py`, `tests/fakes.py`
- Test: `tests/test_names.py`, `tests/test_screens.py`

**Interfaces:**
- Consumes: `Settings`, `Calibration` from `coc_bot.config`; `Match` from `coc_bot.vision.templates`.
- Produces:
  - Constants in `coc_bot.names`: `HOME_ATTACK="home_attack"`, `BTN_FIND_MATCH="btn_find_match"`, `BTN_NEXT="btn_next"`, `BTN_END_BATTLE="btn_end_battle"`, `BTN_RETURN_HOME="btn_return_home"`, `BTN_ARMY="btn_army"`, `ARMY_CLOSE="army_close"`, `ARMY_FULL="army_full"`, `TAB_QUICK_TRAIN="tab_quick_train"`, `BTN_TRAIN_SAVED="btn_train_saved"`, `SEARCHING="searching"`, `POPUP_RELOAD`, `POPUP_TRY_AGAIN`, `POPUP_OKAY`, `POPUP_CLOSE`, `POPUP_TEMPLATES` (that order), `REQUIRED_TEMPLATES`, `OPTIONAL_TEMPLATES`, `ROI_GOLD="gold"`, `ROI_ELIXIR="elixir"`, `ROI_DE="de"`, `REQUIRED_ROIS`, `OPTIONAL_ROIS`, `MAP_CORNERS=("map_top","map_right","map_bottom","map_left")`, `MAX_GOLD=5_000_000`, `MAX_ELIXIR=5_000_000`, `MAX_DE=100_000`
  - `troop_slot(n: int) -> str` → `"troop_slot_{n}"`; `required_points(troop_slots) -> tuple[str, ...]`
  - `missing_calibration(settings: Settings, template_names: set[str]) -> list[str]` (items like `"template:btn_next"`, `"roi:gold"`, `"point:map_top"`)
  - `valid_names(kind: str, troop_slots: tuple[int, ...]) -> tuple[str, ...]` for kind in `template|roi|point`
  - `Screen` enum: `HOME, ATTACK_MENU, ARMY, SEARCHING, BASE_PREVIEW, BATTLE, RESULT, POPUP, UNKNOWN`
  - `detect_screen(image: np.ndarray, templates) -> Screen` (templates = anything with `find(image, name)`)
  - `tests/fakes.py`: `FakeTemplates(visible=(), positions=None)` with `.visible: set[str]`, `find(image, name, threshold=None) -> Match | None` (10×10 match at `positions[name]` or `(100, 100)`), `names()`

- [ ] **Step 1: Write the fakes and failing tests**

`tests/fakes.py`:
```python
"""Shared test doubles. Later tasks append more fakes to this file."""
from coc_bot.vision.templates import Match


class FakeTemplates:
    def __init__(self, visible=(), positions=None):
        self.visible = set(visible)
        self.positions = positions or {}

    def find(self, image, name, threshold=None):
        if name not in self.visible:
            return None
        x, y = self.positions.get(name, (100, 100))
        return Match(name, x, y, 10, 10, 0.99)

    def names(self):
        return sorted(self.visible)
```

`tests/test_screens.py`:
```python
import numpy as np
import pytest

from coc_bot.vision.screens import Screen, detect_screen
from tests.fakes import FakeTemplates

IMG = np.zeros((720, 1280, 3), np.uint8)


@pytest.mark.parametrize(
    "visible, expected",
    [
        ({"home_attack"}, Screen.HOME),
        ({"btn_find_match"}, Screen.ATTACK_MENU),
        ({"army_close"}, Screen.ARMY),
        ({"searching"}, Screen.SEARCHING),
        ({"btn_next", "btn_end_battle"}, Screen.BASE_PREVIEW),
        ({"btn_end_battle"}, Screen.BATTLE),
        ({"btn_return_home"}, Screen.RESULT),
        ({"popup_reload", "home_attack"}, Screen.POPUP),
        ({"popup_okay", "btn_end_battle"}, Screen.POPUP),
        (set(), Screen.UNKNOWN),
    ],
)
def test_detect_screen(visible, expected):
    assert detect_screen(IMG, FakeTemplates(visible)) is expected
```

`tests/test_names.py`:
```python
from coc_bot import names as N
from coc_bot.config import Calibration, Settings


def full_calibration():
    cal = Calibration()
    for name in N.REQUIRED_TEMPLATES:
        cal = cal.with_entry("templates", name, (0, 0, 10, 10))
    for name in N.REQUIRED_ROIS:
        cal = cal.with_entry("rois", name, (0, 0, 10, 10))
    for name in N.required_points((1,)):
        cal = cal.with_entry("points", name, (5, 5))
    return cal


def test_missing_everything():
    missing = N.missing_calibration(Settings(), set())
    assert "template:home_attack" in missing
    assert "roi:gold" in missing
    assert "point:map_top" in missing
    assert "point:troop_slot_1" in missing
    assert "roi:de" not in missing  # optional


def test_template_needs_both_png_and_box():
    settings = Settings(calibration=full_calibration())
    missing = N.missing_calibration(settings, set(N.REQUIRED_TEMPLATES) - {"btn_next"})
    assert missing == ["template:btn_next"]


def test_complete():
    settings = Settings(calibration=full_calibration())
    assert N.missing_calibration(settings, set(N.REQUIRED_TEMPLATES)) == []


def test_valid_names():
    assert "popup_reload" in N.valid_names("template", (1,))
    assert N.valid_names("roi", (1,)) == ("gold", "elixir", "de")
    assert N.valid_names("point", (1, 2))[-2:] == ("troop_slot_1", "troop_slot_2")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_screens.py tests/test_names.py -v`
Expected: FAIL with `ModuleNotFoundError` for `coc_bot.vision.screens` / `coc_bot.names`

- [ ] **Step 3: Write implementation**

`coc_bot/names.py`:
```python
"""Names of templates, ROIs and points shared by calibration, vision and actions."""
from __future__ import annotations

from coc_bot.config import Settings

# Screen markers / buttons
HOME_ATTACK = "home_attack"          # Attack button on the home village
BTN_FIND_MATCH = "btn_find_match"    # "Find a Match" in the attack menu
BTN_NEXT = "btn_next"                # Next button while previewing an enemy base
BTN_END_BATTLE = "btn_end_battle"    # End Battle / Surrender button
BTN_RETURN_HOME = "btn_return_home"  # Return Home on the battle result screen
BTN_ARMY = "btn_army"                # Army / train button on the home village
ARMY_CLOSE = "army_close"            # X that closes the army window
ARMY_FULL = "army_full"              # indicator that the army is complete
TAB_QUICK_TRAIN = "tab_quick_train"  # Quick Train tab in the army window
BTN_TRAIN_SAVED = "btn_train_saved"  # Train button of saved army #1
SEARCHING = "searching"              # clouds while searching for opponent

# Popups, in priority order
POPUP_RELOAD = "popup_reload"
POPUP_TRY_AGAIN = "popup_try_again"
POPUP_OKAY = "popup_okay"
POPUP_CLOSE = "popup_close"
POPUP_TEMPLATES = (POPUP_RELOAD, POPUP_TRY_AGAIN, POPUP_OKAY, POPUP_CLOSE)

REQUIRED_TEMPLATES = (
    HOME_ATTACK, BTN_FIND_MATCH, BTN_NEXT, BTN_END_BATTLE, BTN_RETURN_HOME,
    BTN_ARMY, ARMY_CLOSE, ARMY_FULL, TAB_QUICK_TRAIN, BTN_TRAIN_SAVED, POPUP_OKAY,
)
OPTIONAL_TEMPLATES = (SEARCHING, POPUP_RELOAD, POPUP_TRY_AGAIN, POPUP_CLOSE)

# Loot ROIs on the enemy base preview
ROI_GOLD = "gold"
ROI_ELIXIR = "elixir"
ROI_DE = "de"
REQUIRED_ROIS = (ROI_GOLD, ROI_ELIXIR)
OPTIONAL_ROIS = (ROI_DE,)
MAX_GOLD = 5_000_000
MAX_ELIXIR = 5_000_000
MAX_DE = 100_000

# Points: map diamond corners (fully zoomed out) and troop card slots
MAP_CORNERS = ("map_top", "map_right", "map_bottom", "map_left")


def troop_slot(n: int) -> str:
    return f"troop_slot_{n}"


def required_points(troop_slots: tuple[int, ...]) -> tuple[str, ...]:
    return MAP_CORNERS + tuple(troop_slot(n) for n in troop_slots)


def valid_names(kind: str, troop_slots: tuple[int, ...]) -> tuple[str, ...]:
    if kind == "template":
        return REQUIRED_TEMPLATES + OPTIONAL_TEMPLATES
    if kind == "roi":
        return REQUIRED_ROIS + OPTIONAL_ROIS
    if kind == "point":
        return required_points(troop_slots)
    raise ValueError(f"Unknown kind: {kind}")


def missing_calibration(settings: Settings, template_names: set[str]) -> list[str]:
    cal = settings.calibration
    missing = [
        f"template:{n}" for n in REQUIRED_TEMPLATES
        if n not in template_names or n not in cal.templates
    ]
    missing += [f"roi:{n}" for n in REQUIRED_ROIS if n not in cal.rois]
    missing += [
        f"point:{n}" for n in required_points(settings.deploy.troop_slots) if n not in cal.points
    ]
    return missing
```

`coc_bot/vision/screens.py`:
```python
"""Identify which game screen is showing."""
from __future__ import annotations

from enum import Enum
from typing import Protocol

import numpy as np

from coc_bot import names as N
from coc_bot.vision.templates import Match


class Screen(Enum):
    HOME = "home"
    ATTACK_MENU = "attack_menu"
    ARMY = "army"
    SEARCHING = "searching"
    BASE_PREVIEW = "base_preview"
    BATTLE = "battle"
    RESULT = "result"
    POPUP = "popup"
    UNKNOWN = "unknown"


class TemplateFinder(Protocol):
    def find(self, image: np.ndarray, name: str, threshold: float | None = None) -> Match | None: ...


# Order matters: BASE_PREVIEW also shows End Battle, so it is checked before BATTLE.
SCREEN_MARKERS: tuple[tuple[Screen, str], ...] = (
    (Screen.RESULT, N.BTN_RETURN_HOME),
    (Screen.BASE_PREVIEW, N.BTN_NEXT),
    (Screen.BATTLE, N.BTN_END_BATTLE),
    (Screen.ATTACK_MENU, N.BTN_FIND_MATCH),
    (Screen.ARMY, N.ARMY_CLOSE),
    (Screen.HOME, N.HOME_ATTACK),
    (Screen.SEARCHING, N.SEARCHING),
)


def detect_screen(image: np.ndarray, templates: TemplateFinder) -> Screen:
    for name in N.POPUP_TEMPLATES:
        if templates.find(image, name) is not None:
            return Screen.POPUP
    for screen, name in SCREEN_MARKERS:
        if templates.find(image, name) is not None:
            return screen
    return Screen.UNKNOWN
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_screens.py tests/test_names.py -v`
Expected: 14 passed

- [ ] **Step 5: Commit**

```bash
git add coc_bot/names.py coc_bot/vision/screens.py tests/fakes.py tests/test_screens.py tests/test_names.py
git commit -m "feat: shared names, calibration check and screen detection"
```

---

### Task 6: Loot decision + deploy geometry

**Files:**
- Create: `coc_bot/game/loot.py`, `coc_bot/game/deploy.py`
- Test: `tests/test_loot.py`, `tests/test_deploy.py`

**Interfaces:**
- Consumes: `LootConfig`, `Point` from `coc_bot.config`.
- Produces:
  - `Loot(gold: int, elixir: int, de: int)` (frozen dataclass)
  - `is_worth_attacking(loot: Loot | None, cfg: LootConfig) -> bool`
  - `edge_points(corners: Sequence[Point], sides: int, per_side: int, outward_px: int, jitter_px: int, rng: random.Random, size: tuple[int, int], max_y: int) -> list[Point]` — `corners` ordered top, right, bottom, left; `size` = (width, height)

- [ ] **Step 1: Write the failing tests**

`tests/test_loot.py`:
```python
from coc_bot.config import LootConfig
from coc_bot.game.loot import Loot, is_worth_attacking

CFG = LootConfig(min_gold=100, min_elixir=200, min_de=0, max_next=50)


def test_worth_when_all_thresholds_met():
    assert is_worth_attacking(Loot(100, 200, 0), CFG)


def test_not_worth_when_one_below():
    assert not is_worth_attacking(Loot(99, 500, 0), CFG)
    assert not is_worth_attacking(Loot(500, 199, 0), CFG)


def test_de_threshold():
    cfg = LootConfig(min_gold=0, min_elixir=0, min_de=50, max_next=50)
    assert not is_worth_attacking(Loot(0, 0, 49), cfg)
    assert is_worth_attacking(Loot(0, 0, 50), cfg)


def test_none_is_not_worth():
    assert not is_worth_attacking(None, CFG)
```

`tests/test_deploy.py`:
```python
import math
import random

import pytest

from coc_bot.game.deploy import edge_points

CORNERS = [(640, 100), (1100, 360), (640, 620), (180, 360)]
CENTER = (640, 360)
SIZE = (1280, 720)


def pts(**kw):
    args = dict(corners=CORNERS, sides=4, per_side=5, outward_px=0, jitter_px=0,
                rng=random.Random(0), size=SIZE, max_y=720)
    args.update(kw)
    return edge_points(**args)


def test_count():
    assert len(pts()) == 20
    assert len(pts(sides=2)) == 10


def test_single_point_is_edge_midpoint():
    assert pts(sides=1, per_side=1) == [(870, 230)]


def test_outward_moves_away_from_center():
    (x, y), = pts(sides=1, per_side=1, outward_px=10)
    before = math.dist((870, 230), CENTER)
    after = math.dist((x, y), CENTER)
    assert abs((after - before) - 10) <= 1


def test_points_clamped_to_screen_and_max_y():
    corners = [(640, 100), (1270, 360), (640, 700), (5, 360)]
    result = pts(corners=corners, outward_px=50, jitter_px=5, max_y=600)
    assert all(0 <= x < 1280 and 0 <= y <= 600 for x, y in result)


def test_jitter_is_bounded():
    a = pts(sides=1, per_side=3)
    b = pts(sides=1, per_side=3, jitter_px=4, rng=random.Random(1))
    assert all(abs(ax - bx) <= 4 and abs(ay - by) <= 4 for (ax, ay), (bx, by) in zip(a, b))


@pytest.mark.parametrize("sides", [0, 5])
def test_invalid_sides(sides):
    with pytest.raises(ValueError):
        pts(sides=sides)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_loot.py tests/test_deploy.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write implementation**

`coc_bot/game/loot.py`:
```python
from __future__ import annotations

from dataclasses import dataclass

from coc_bot.config import LootConfig


@dataclass(frozen=True)
class Loot:
    gold: int
    elixir: int
    de: int


def is_worth_attacking(loot: Loot | None, cfg: LootConfig) -> bool:
    if loot is None:
        return False
    return loot.gold >= cfg.min_gold and loot.elixir >= cfg.min_elixir and loot.de >= cfg.min_de
```

`coc_bot/game/deploy.py`:
```python
"""Deploy points spread along the edges of the (zoomed-out) map diamond."""
from __future__ import annotations

import math
import random
from typing import Sequence

from coc_bot.config import Point


def edge_points(
    corners: Sequence[Point],
    sides: int,
    per_side: int,
    outward_px: int,
    jitter_px: int,
    rng: random.Random,
    size: tuple[int, int],
    max_y: int,
) -> list[Point]:
    if not 1 <= sides <= 4:
        raise ValueError(f"sides must be 1..4, got {sides}")
    if len(corners) != 4:
        raise ValueError("corners must be (top, right, bottom, left)")
    width, height = size
    cx = sum(p[0] for p in corners) / 4
    cy = sum(p[1] for p in corners) / 4
    edges = [(corners[i], corners[(i + 1) % 4]) for i in range(4)][:sides]
    result: list[Point] = []
    for (ax, ay), (bx, by) in edges:
        for k in range(per_side):
            t = 0.5 if per_side == 1 else 0.15 + 0.7 * k / (per_side - 1)
            x = ax + (bx - ax) * t
            y = ay + (by - ay) * t
            dx, dy = x - cx, y - cy
            norm = math.hypot(dx, dy) or 1.0
            x += dx / norm * outward_px + rng.uniform(-jitter_px, jitter_px)
            y += dy / norm * outward_px + rng.uniform(-jitter_px, jitter_px)
            px = min(max(int(round(x)), 0), width - 1)
            py = min(max(int(round(y)), 0), min(height - 1, max_y))
            result.append((px, py))
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_loot.py tests/test_deploy.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add coc_bot/game/loot.py coc_bot/game/deploy.py tests/test_loot.py tests/test_deploy.py
git commit -m "feat: loot decision and edge deploy geometry"
```

---

### Task 7: Session policy

**Files:**
- Create: `coc_bot/bot/session.py`
- Test: `tests/test_session.py`

**Interfaces:**
- Consumes: `SessionConfig` from `coc_bot.config`.
- Produces: `SessionPolicy(cfg: SessionConfig, rng: random.Random)` with
  - `in_active_hours(now: datetime) -> bool` (supports overnight windows like 22:00–06:00)
  - `start_play(now: datetime) -> None`, `end_play(now: datetime) -> None`
  - `played_seconds(now: datetime) -> float` (today's total incl. the running play block)
  - `should_rest(now: datetime) -> bool`
  - `rest_seconds(now: datetime) -> float` (random break, or seconds until the next active window when outside hours / daily cap reached)

- [ ] **Step 1: Write the failing test**

`tests/test_session.py`:
```python
import random
from datetime import datetime

from coc_bot.bot.session import SessionPolicy
from coc_bot.config import SessionConfig

CFG = SessionConfig(play_minutes=(40, 40), break_minutes=(10, 10),
                    active_hours=("08:00", "23:00"), max_hours_per_day=10.0)


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_session.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'coc_bot.bot.session'`

- [ ] **Step 3: Write implementation**

`coc_bot/bot/session.py`:
```python
"""Human-like play schedule: active hours, play/break blocks, daily cap."""
from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta

from coc_bot.config import SessionConfig


def _parse_hhmm(text: str) -> time:
    hours, minutes = text.split(":")
    return time(int(hours), int(minutes))


class SessionPolicy:
    def __init__(self, cfg: SessionConfig, rng: random.Random) -> None:
        self._cfg = cfg
        self._rng = rng
        self._start = _parse_hhmm(cfg.active_hours[0])
        self._end = _parse_hhmm(cfg.active_hours[1])
        self._play_started: datetime | None = None
        self._play_until: datetime | None = None
        self._played: dict[date, float] = {}

    def in_active_hours(self, now: datetime) -> bool:
        t = now.time()
        if self._start <= self._end:
            return self._start <= t < self._end
        return t >= self._start or t < self._end

    def start_play(self, now: datetime) -> None:
        self._play_started = now
        self._play_until = now + timedelta(minutes=self._rng.uniform(*self._cfg.play_minutes))

    def end_play(self, now: datetime) -> None:
        if self._play_started is None:
            return
        day = self._play_started.date()
        self._played[day] = self._played.get(day, 0.0) + (now - self._play_started).total_seconds()
        self._play_started = None
        self._play_until = None

    def played_seconds(self, now: datetime) -> float:
        total = self._played.get(now.date(), 0.0)
        if self._play_started is not None and self._play_started.date() == now.date():
            total += (now - self._play_started).total_seconds()
        return total

    def _daily_cap_reached(self, now: datetime) -> bool:
        return self.played_seconds(now) >= self._cfg.max_hours_per_day * 3600

    def should_rest(self, now: datetime) -> bool:
        if not self.in_active_hours(now) or self._daily_cap_reached(now):
            return True
        return self._play_until is not None and now >= self._play_until

    def rest_seconds(self, now: datetime) -> float:
        if not self.in_active_hours(now) or self._daily_cap_reached(now):
            candidate = datetime.combine(now.date(), self._start)
            if candidate <= now:
                candidate += timedelta(days=1)
            return (candidate - now).total_seconds()
        return self._rng.uniform(*self._cfg.break_minutes) * 60
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_session.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add coc_bot/bot/session.py tests/test_session.py
git commit -m "feat: session policy (active hours, breaks, daily cap)"
```

---

### Task 8: Game actions

**Files:**
- Create: `coc_bot/game/actions.py`
- Modify: `tests/fakes.py` (append `FakeAdb`, `FakeOcr`, `make_settings`)
- Test: `tests/test_actions.py`

**Interfaces:**
- Consumes: `EmulatorAdb` methods (`screencap`, `tap`, `key_back`, `start_app`, `stop_app`, `connect`); `TemplateLibrary.find`; `OcrReader.read_number`; `Settings`; `names` constants; `edge_points`; `Loot`; `Screen`, `detect_screen`.
- Produces: `Game(adb, templates, ocr, settings: Settings, rng: random.Random, sleep=time.sleep, debug_dir: Path = Path("logs/screens"))` with:
  - `last_image: np.ndarray | None`
  - `capture() -> np.ndarray`, `screen() -> Screen`
  - `tap(point: Point) -> None`, `tap_template(name: str, fresh: bool = True) -> bool`, `wait_for(name: str, timeout_s: float = 5.0, interval_s: float = 0.5) -> bool`
  - `army_ready() -> bool`, `quick_train() -> bool`, `close_army() -> bool`
  - `open_attack_menu() -> bool`, `find_match() -> bool`, `next_base() -> bool`
  - `read_loot() -> Loot | None`, `deploy_army() -> None`, `end_battle() -> None`, `return_home() -> bool`
  - `dismiss_popup() -> bool`, `go_back() -> None`, `restart_game() -> None`, `reconnect() -> None`
  - `save_debug_screenshot(tag: str) -> Path | None`

- [ ] **Step 1: Append fakes**

Append to `tests/fakes.py`:
```python
from dataclasses import replace

import numpy as np

from coc_bot.config import Calibration, Settings


class FakeAdb:
    def __init__(self, image=None):
        self.image = image if image is not None else np.zeros((720, 1280, 3), np.uint8)
        self.calls = []

    def screencap(self):
        self.calls.append(("screencap",))
        return self.image

    def tap(self, x, y):
        self.calls.append(("tap", x, y))

    def key_back(self):
        self.calls.append(("back",))

    def start_app(self, package):
        self.calls.append(("start", package))

    def stop_app(self, package):
        self.calls.append(("stop", package))

    def connect(self):
        self.calls.append(("connect",))

    def taps(self):
        return [(c[1], c[2]) for c in self.calls if c[0] == "tap"]


class FakeOcr:
    def __init__(self, values):
        self.values = values  # roi tuple -> int | None

    def read_number(self, image, roi, max_value):
        return self.values.get(tuple(roi))


def make_settings(**overrides):
    cal = Calibration(
        templates={},
        rois={"gold": (10, 10, 100, 20), "elixir": (10, 40, 100, 20), "de": (10, 70, 100, 20)},
        points={
            "map_top": (640, 100), "map_right": (1100, 360),
            "map_bottom": (640, 620), "map_left": (180, 360),
            "troop_slot_1": (200, 680), "troop_slot_2": (280, 680),
        },
    )
    return replace(Settings(calibration=cal), **overrides)
```

- [ ] **Step 2: Write the failing test**

`tests/test_actions.py`:
```python
import random
from dataclasses import replace

from coc_bot.game.actions import Game
from coc_bot.game.loot import Loot
from coc_bot.vision.screens import Screen
from tests.fakes import FakeAdb, FakeOcr, FakeTemplates, make_settings

GOLD, ELIXIR, DE = (10, 10, 100, 20), (10, 40, 100, 20), (10, 70, 100, 20)


def make_game(visible=(), positions=None, ocr=None, settings=None, debug_dir=None):
    adb = FakeAdb()
    kwargs = {"debug_dir": debug_dir} if debug_dir else {}
    game = Game(adb, FakeTemplates(visible, positions), FakeOcr(ocr or {}),
                settings or make_settings(), random.Random(0), sleep=lambda s: None, **kwargs)
    return game, adb


def near(point, target, tol=4):
    return abs(point[0] - target[0]) <= tol and abs(point[1] - target[1]) <= tol


def test_screen_uses_fresh_capture():
    game, adb = make_game({"home_attack"})
    assert game.screen() is Screen.HOME
    assert adb.calls[0] == ("screencap",)
    assert game.last_image is not None


def test_tap_template_taps_near_center():
    game, adb = make_game({"btn_next"}, {"btn_next": (500, 300)})
    assert game.tap_template("btn_next")
    assert near(adb.taps()[0], (505, 305))


def test_tap_template_missing():
    game, adb = make_game()
    assert not game.tap_template("btn_next")
    assert adb.taps() == []


def test_army_ready_true_and_closes():
    pos = {"btn_army": (100, 600), "army_close": (1200, 50)}
    game, adb = make_game({"btn_army", "army_close", "army_full"}, pos)
    assert game.army_ready()
    taps = adb.taps()
    assert near(taps[0], (105, 605)) and near(taps[-1], (1205, 55))


def test_army_ready_false_when_not_full():
    game, _ = make_game({"btn_army", "army_close"})
    assert not game.army_ready()


def test_quick_train_sequence():
    pos = {"btn_army": (100, 600), "tab_quick_train": (400, 100),
           "btn_train_saved": (900, 300), "army_close": (1200, 50)}
    game, adb = make_game(set(pos), pos)
    assert game.quick_train()
    taps = adb.taps()
    assert len(taps) == 4
    for tap, (x, y) in zip(taps, pos.values()):
        assert near(tap, (x + 5, y + 5))


def test_read_loot():
    game, _ = make_game(ocr={GOLD: 400_000, ELIXIR: 350_000, DE: 2_000})
    game.capture()
    assert game.read_loot() == Loot(400_000, 350_000, 2_000)


def test_read_loot_de_optional():
    game, _ = make_game(ocr={GOLD: 1, ELIXIR: 2})
    assert game.read_loot() == Loot(1, 2, 0)


def test_read_loot_requires_de_when_min_de_set():
    s = make_settings()
    s = replace(s, loot=replace(s.loot, min_de=100))
    game, _ = make_game(ocr={GOLD: 1, ELIXIR: 2}, settings=s)
    assert game.read_loot() is None


def test_read_loot_none_when_gold_unreadable():
    game, adb = make_game(ocr={ELIXIR: 2})
    assert game.read_loot() is None
    assert sum(1 for c in adb.calls if c[0] == "screencap") == 2  # initial + one retry


def test_deploy_army_tap_count():
    s = make_settings()
    s = replace(s, deploy=replace(s.deploy, troop_slots=(1, 2), sides=4, points_per_side=5, taps_per_point=2))
    game, adb = make_game(settings=s)
    game.capture()
    game.deploy_army()
    taps = adb.taps()
    assert len(taps) == 2 * (1 + 20 * 2)
    assert near(taps[0], (200, 680))
    assert all(y <= s.deploy.max_y for _, y in taps[1:41])


def test_dismiss_popup_prefers_reload():
    pos = {"popup_close": (1200, 50), "popup_reload": (600, 400)}
    game, adb = make_game(set(pos), pos)
    assert game.dismiss_popup()
    assert near(adb.taps()[0], (605, 405))


def test_dismiss_popup_nothing():
    game, _ = make_game()
    assert not game.dismiss_popup()


def test_end_battle_confirms():
    pos = {"btn_end_battle": (50, 550), "popup_okay": (700, 450)}
    game, adb = make_game(set(pos), pos)
    game.end_battle()
    taps = adb.taps()
    assert near(taps[0], (55, 555)) and near(taps[1], (705, 455))


def test_restart_game_stops_then_starts():
    game, adb = make_game()
    game.restart_game()
    kinds = [c for c in adb.calls if c[0] in ("stop", "start")]
    assert kinds == [("stop", "com.supercell.clashofclans"), ("start", "com.supercell.clashofclans")]


def test_go_back_and_reconnect():
    game, adb = make_game()
    game.go_back()
    game.reconnect()
    assert ("back",) in adb.calls and ("connect",) in adb.calls


def test_save_debug_screenshot(tmp_path):
    game, _ = make_game(debug_dir=tmp_path)
    assert game.save_debug_screenshot("x") is None
    game.capture()
    path = game.save_debug_screenshot("stuck")
    assert path is not None and path.exists() and path.name.endswith("_stuck.png")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_actions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'coc_bot.game.actions'`

- [ ] **Step 4: Write implementation**

`coc_bot/game/actions.py`:
```python
"""High-level game actions built on the ADB device and vision modules."""
from __future__ import annotations

import logging
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from coc_bot import names as N
from coc_bot.config import Point, Settings
from coc_bot.game.deploy import edge_points
from coc_bot.game.loot import Loot
from coc_bot.vision.screens import Screen, detect_screen

log = logging.getLogger(__name__)


class Game:
    def __init__(
        self,
        adb,
        templates,
        ocr,
        settings: Settings,
        rng: random.Random,
        sleep: Callable[[float], None] = time.sleep,
        debug_dir: Path = Path("logs/screens"),
    ) -> None:
        self.adb = adb
        self.templates = templates
        self.ocr = ocr
        self.settings = settings
        self.rng = rng
        self.sleep = sleep
        self.debug_dir = debug_dir
        self.last_image: np.ndarray | None = None

    # --- primitives -------------------------------------------------------
    def capture(self) -> np.ndarray:
        self.last_image = self.adb.screencap()
        return self.last_image

    def screen(self) -> Screen:
        return detect_screen(self.capture(), self.templates)

    def _pause(self) -> None:
        low, high = self.settings.timing.tap_delay_ms
        self.sleep(self.rng.uniform(low, high) / 1000)

    def tap(self, point: Point) -> None:
        j = self.settings.timing.tap_jitter_px
        self.adb.tap(point[0] + self.rng.randint(-j, j), point[1] + self.rng.randint(-j, j))
        self._pause()

    def _image(self, fresh: bool) -> np.ndarray:
        if fresh or self.last_image is None:
            return self.capture()
        return self.last_image

    def tap_template(self, name: str, fresh: bool = True) -> bool:
        match = self.templates.find(self._image(fresh), name)
        if match is None:
            log.debug("Template not found: %s", name)
            return False
        self.tap(match.center)
        return True

    def wait_for(self, name: str, timeout_s: float = 5.0, interval_s: float = 0.5) -> bool:
        waited = 0.0
        while True:
            if self.templates.find(self.capture(), name) is not None:
                return True
            if waited >= timeout_s:
                return False
            self.sleep(interval_s)
            waited += interval_s

    # --- army -------------------------------------------------------------
    def army_ready(self) -> bool:
        if not self.tap_template(N.BTN_ARMY) or not self.wait_for(N.ARMY_CLOSE):
            return False
        ready = self.templates.find(self.last_image, N.ARMY_FULL) is not None
        self.tap_template(N.ARMY_CLOSE, fresh=False)
        return ready

    def quick_train(self) -> bool:
        if not self.tap_template(N.BTN_ARMY) or not self.wait_for(N.ARMY_CLOSE):
            return False
        ok = (
            self.tap_template(N.TAB_QUICK_TRAIN)
            and self.wait_for(N.BTN_TRAIN_SAVED)
            and self.tap_template(N.BTN_TRAIN_SAVED, fresh=False)
        )
        self.tap_template(N.ARMY_CLOSE)
        return bool(ok)

    def close_army(self) -> bool:
        return self.tap_template(N.ARMY_CLOSE, fresh=False)

    # --- attack flow ------------------------------------------------------
    def open_attack_menu(self) -> bool:
        return self.tap_template(N.HOME_ATTACK)

    def find_match(self) -> bool:
        return self.tap_template(N.BTN_FIND_MATCH, fresh=False)

    def next_base(self) -> bool:
        return self.tap_template(N.BTN_NEXT, fresh=False)

    def read_loot(self) -> Loot | None:
        for attempt in range(2):
            image = self._image(fresh=attempt > 0)
            loot = self._read_loot_once(image)
            if loot is not None:
                return loot
        return None

    def _read_loot_once(self, image: np.ndarray) -> Loot | None:
        rois = self.settings.calibration.rois
        gold = self.ocr.read_number(image, rois[N.ROI_GOLD], N.MAX_GOLD)
        elixir = self.ocr.read_number(image, rois[N.ROI_ELIXIR], N.MAX_ELIXIR)
        if gold is None or elixir is None:
            return None
        de = self.ocr.read_number(image, rois[N.ROI_DE], N.MAX_DE) if N.ROI_DE in rois else None
        if de is None:
            if self.settings.loot.min_de > 0:
                return None
            de = 0
        return Loot(gold, elixir, de)

    def deploy_army(self) -> None:
        d = self.settings.deploy
        points = self.settings.calibration.points
        corners = [points[name] for name in N.MAP_CORNERS]
        height, width = self.last_image.shape[:2] if self.last_image is not None else (720, 1280)
        targets = edge_points(corners, d.sides, d.points_per_side, d.outward_px,
                              self.settings.timing.tap_jitter_px, self.rng, (width, height), d.max_y)
        for slot in d.troop_slots:
            self.tap(points[N.troop_slot(slot)])
            for x, y in targets:
                for _ in range(d.taps_per_point):
                    self.adb.tap(x, y)
                    self.sleep(self.rng.uniform(0.04, 0.11))

    def end_battle(self) -> None:
        if self.tap_template(N.BTN_END_BATTLE) and self.wait_for(N.POPUP_OKAY, timeout_s=3.0):
            self.tap_template(N.POPUP_OKAY, fresh=False)

    def return_home(self) -> bool:
        return self.tap_template(N.BTN_RETURN_HOME, fresh=False)

    # --- recovery ---------------------------------------------------------
    def dismiss_popup(self) -> bool:
        image = self._image(fresh=False)
        for name in N.POPUP_TEMPLATES:
            match = self.templates.find(image, name)
            if match is not None:
                log.info("Dismissing popup: %s", name)
                self.tap(match.center)
                return True
        return False

    def go_back(self) -> None:
        self.adb.key_back()
        self._pause()

    def restart_game(self) -> None:
        package = self.settings.adb.package
        log.warning("Restarting %s", package)
        self.adb.stop_app(package)
        self.sleep(3.0)
        self.adb.start_app(package)
        self.sleep(30.0)

    def reconnect(self) -> None:
        self.adb.connect()

    def save_debug_screenshot(self, tag: str) -> Path | None:
        if self.last_image is None:
            return None
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        path = self.debug_dir / f"{datetime.now():%Y%m%d_%H%M%S_%f}_{tag}.png"
        cv2.imwrite(str(path), self.last_image)
        log.info("Saved screenshot %s", path)
        return path
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_actions.py -v`
Expected: 17 passed

- [ ] **Step 6: Commit**

```bash
git add coc_bot/game/actions.py tests/fakes.py tests/test_actions.py
git commit -m "feat: high-level game actions"
```

---

### Task 9: Bot state machine

**Files:**
- Create: `coc_bot/bot/state_machine.py`
- Modify: `tests/fakes.py` (append `FakeClock`, `FakeGame`, `FakePolicy`)
- Test: `tests/test_state_machine.py`

**Interfaces:**
- Consumes: `Game` method names from Task 8 (`screen`, `army_ready`, `quick_train`, `close_army`, `open_attack_menu`, `find_match`, `read_loot`, `next_base`, `deploy_army`, `end_battle`, `return_home`, `dismiss_popup`, `go_back`, `restart_game`, `reconnect`, `save_debug_screenshot`); `SessionPolicy` methods from Task 7 (`start_play`, `end_play`, `should_rest`, `rest_seconds`); `AdbError`; `is_worth_attacking`; `Screen`.
- Produces: `FatalError(RuntimeError)`, `Stats(attacks, skipped, recoveries, restarts)`, `Bot(game, policy, settings, rng, clock: Callable[[], datetime], sleep: Callable[[float], None])` with `run(max_ticks: int | None = None)`, `tick()`, `stop()`, `stats`.

- [ ] **Step 1: Append fakes**

Append to `tests/fakes.py`:
```python
from datetime import datetime, timedelta

from coc_bot.device.adb import AdbError


class FakeClock:
    def __init__(self, start=datetime(2026, 11, 10, 9, 0)):
        self.current = start
        self.slept = []

    def now(self):
        return self.current

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.current += timedelta(seconds=seconds)


class FakeGame:
    def __init__(self, screens, loot=None, army_ready=True):
        self.screens = list(screens)
        self.loot = loot
        self._army_ready = army_ready
        self.fail_screen_times = 0
        self.calls = []

    def count(self, name):
        return sum(1 for c in self.calls if c == name)

    def screen(self):
        if self.fail_screen_times > 0:
            self.fail_screen_times -= 1
            raise AdbError("boom")
        return self.screens.pop(0) if len(self.screens) > 1 else self.screens[0]

    def army_ready(self):
        self.calls.append("army_ready")
        return self._army_ready

    def read_loot(self):
        self.calls.append("read_loot")
        return self.loot

    def save_debug_screenshot(self, tag):
        self.calls.append("save_debug_screenshot")
        return None

    def __getattr__(self, name):
        if name in {"quick_train", "close_army", "open_attack_menu", "find_match", "next_base",
                    "deploy_army", "end_battle", "return_home", "dismiss_popup", "go_back",
                    "restart_game", "reconnect"}:
            return lambda: self.calls.append(name)
        raise AttributeError(name)


class FakePolicy:
    def __init__(self, rest=False, rest_s=600.0):
        self.rest = rest
        self.rest_s = rest_s
        self.events = []

    def start_play(self, now):
        self.events.append("start")

    def end_play(self, now):
        self.events.append("end")

    def should_rest(self, now):
        return self.rest

    def rest_seconds(self, now):
        self.rest = False
        return self.rest_s
```

- [ ] **Step 2: Write the failing test**

`tests/test_state_machine.py`:
```python
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


def test_home_with_ready_army_opens_attack_menu():
    game = FakeGame([Screen.HOME])
    make_bot(game)[0].tick()
    assert game.count("open_attack_menu") == 1


def test_home_trains_once_while_waiting():
    game = FakeGame([Screen.HOME], army_ready=False)
    bot, clock = make_bot(game)
    bot.tick()
    bot.tick()
    assert game.count("quick_train") == 1
    assert game.count("open_attack_menu") == 0
    assert all(60 <= s <= 120 for s in clock.slept)


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
    assert game.count("save_debug_screenshot") >= 1


def test_progress_screen_resets_escalation():
    screens = [Screen.UNKNOWN] * 32 + [Screen.HOME] + [Screen.UNKNOWN] * 40
    game = FakeGame(screens)
    bot, _ = make_bot(game, settings=with_timing(stuck_timeout_s=60))
    for _ in range(len(screens)):
        bot.tick()
    assert game.count("go_back") == 2
    assert game.count("restart_game") == 0


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
    assert policy.events == ["start"]
    assert game.calls == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_state_machine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'coc_bot.bot.state_machine'`

- [ ] **Step 4: Write implementation**

`coc_bot/bot/state_machine.py`:
```python
"""Screen-driven farming loop with stuck detection and escalating recovery."""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from coc_bot.config import Settings
from coc_bot.device.adb import AdbError
from coc_bot.game.loot import is_worth_attacking
from coc_bot.vision.screens import Screen

log = logging.getLogger(__name__)

ACTION_SCREENS = frozenset({Screen.POPUP, Screen.ATTACK_MENU, Screen.RESULT, Screen.ARMY})
WAIT_SCREENS = frozenset({Screen.UNKNOWN, Screen.SEARCHING})
PROGRESS_SCREENS = frozenset({Screen.HOME, Screen.BATTLE})
MAX_SAME_ACTION_TICKS = 5
MAX_ADB_RECONNECTS = 3


class FatalError(RuntimeError):
    """The bot cannot continue safely."""


@dataclass
class Stats:
    attacks: int = 0
    skipped: int = 0
    recoveries: int = 0
    restarts: int = 0


class Bot:
    def __init__(
        self,
        game,
        policy,
        settings: Settings,
        rng: random.Random,
        clock: Callable[[], datetime],
        sleep: Callable[[float], None],
    ) -> None:
        self.game = game
        self.policy = policy
        self.settings = settings
        self.rng = rng
        self.clock = clock
        self.sleep = sleep
        self.stats = Stats()
        self._stop = False
        self._trained = False
        self._next_count = 0
        self._battle_started: datetime | None = None
        self._last_screen: Screen | None = None
        self._same_ticks = 0
        self._wait_since: datetime | None = None
        self._recover_level = 0
        self._consecutive_restarts = 0
        self._handlers = {
            Screen.HOME: self._on_home,
            Screen.ATTACK_MENU: self._on_attack_menu,
            Screen.ARMY: self._on_army,
            Screen.SEARCHING: self._on_searching,
            Screen.BASE_PREVIEW: self._on_base_preview,
            Screen.BATTLE: self._on_battle,
            Screen.RESULT: self._on_result,
            Screen.POPUP: self._on_popup,
            Screen.UNKNOWN: self._on_unknown,
        }

    def stop(self) -> None:
        self._stop = True

    def run(self, max_ticks: int | None = None) -> None:
        self.policy.start_play(self.clock())
        adb_failures = 0
        ticks = 0
        while not self._stop and (max_ticks is None or ticks < max_ticks):
            ticks += 1
            try:
                self.tick()
            except AdbError as exc:
                adb_failures += 1
                log.warning("ADB error (%d/%d): %s", adb_failures, MAX_ADB_RECONNECTS, exc)
                if adb_failures > MAX_ADB_RECONNECTS:
                    raise FatalError(f"ADB unavailable after {MAX_ADB_RECONNECTS} reconnects") from exc
                self.sleep(5.0)
                try:
                    self.game.reconnect()
                except AdbError as reconnect_exc:
                    log.warning("Reconnect failed: %s", reconnect_exc)
            else:
                adb_failures = 0
        log.info("Bot stopped. %s", self.stats)

    def tick(self) -> None:
        now = self.clock()
        screen = self.game.screen()
        if self._check_stuck(screen, now):
            return
        self._handlers[screen](now)

    # --- stuck detection / recovery --------------------------------------
    def _check_stuck(self, screen: Screen, now: datetime) -> bool:
        if screen != self._last_screen:
            log.debug("Screen: %s", screen.name)
            self._last_screen = screen
            self._same_ticks = 1
            self._wait_since = now if screen in WAIT_SCREENS else None
            if screen is Screen.UNKNOWN:
                self.game.save_debug_screenshot("unknown")
        else:
            self._same_ticks += 1
        if screen in PROGRESS_SCREENS:
            self._recover_level = 0
            self._consecutive_restarts = 0
        stuck = (
            (screen in ACTION_SCREENS and self._same_ticks > MAX_SAME_ACTION_TICKS)
            or (screen is Screen.BASE_PREVIEW and self._same_ticks > self.settings.loot.max_next + 10)
            or (
                self._wait_since is not None
                and (now - self._wait_since).total_seconds() > self.settings.timing.stuck_timeout_s
            )
        )
        if stuck:
            self._recover(screen)
        return stuck

    def _recover(self, screen: Screen) -> None:
        self.stats.recoveries += 1
        self.game.save_debug_screenshot(f"stuck_{screen.name.lower()}")
        self._same_ticks = 0
        self._wait_since = self.clock() if screen in WAIT_SCREENS else None
        if self._recover_level == 0:
            log.warning("Stuck on %s, pressing Back", screen.name)
            self._recover_level = 1
            self.game.go_back()
            return
        if self._consecutive_restarts >= self.settings.timing.max_restarts:
            raise FatalError(f"Still stuck on {screen.name} after {self._consecutive_restarts} restarts")
        self._consecutive_restarts += 1
        self.stats.restarts += 1
        log.warning("Stuck on %s, restarting game (%d/%d)", screen.name,
                    self._consecutive_restarts, self.settings.timing.max_restarts)
        self.game.restart_game()

    # --- screen handlers --------------------------------------------------
    def _on_home(self, now: datetime) -> None:
        self._battle_started = None
        if self.policy.should_rest(now):
            self.policy.end_play(now)
            seconds = self.policy.rest_seconds(now)
            log.info("Resting for %.0f min", seconds / 60)
            self.sleep(seconds)
            self.policy.start_play(self.clock())
            return
        if self.game.army_ready():
            log.info("Army ready, opening attack menu")
            self.game.open_attack_menu()
            return
        if not self._trained:
            log.info("Army not ready, quick training")
            self.game.quick_train()
            self._trained = True
        self.sleep(self.rng.uniform(*self.settings.timing.army_poll_s))

    def _on_attack_menu(self, now: datetime) -> None:
        self._next_count = 0
        self.game.find_match()

    def _on_army(self, now: datetime) -> None:
        self.game.close_army()

    def _on_searching(self, now: datetime) -> None:
        self.sleep(1.0)

    def _on_unknown(self, now: datetime) -> None:
        self.sleep(2.0)

    def _on_base_preview(self, now: datetime) -> None:
        loot = self.game.read_loot()
        cfg = self.settings.loot
        worth = is_worth_attacking(loot, cfg)
        if worth or self._next_count >= cfg.max_next:
            log.info("Attacking (%s) %s after %d skips",
                     "loot ok" if worth else "max_next reached", loot, self._next_count)
            self.game.deploy_army()
            self.stats.attacks += 1
            self._trained = False
            self._battle_started = now
            return
        self.stats.skipped += 1
        self._next_count += 1
        log.info("Skip %d: %s", self._next_count, loot)
        self.game.next_base()
        self.sleep(self.rng.uniform(1.5, 3.0))

    def _on_battle(self, now: datetime) -> None:
        if self._battle_started is None:
            self._battle_started = now
        if (now - self._battle_started).total_seconds() >= self.settings.timing.battle_timeout_s:
            log.info("Battle timeout, ending battle")
            self.game.end_battle()
            return
        self.sleep(3.0)

    def _on_result(self, now: datetime) -> None:
        self._battle_started = None
        log.info("Battle finished. %s", self.stats)
        self.game.return_home()
        self.sleep(self.rng.uniform(2.0, 4.0))

    def _on_popup(self, now: datetime) -> None:
        self.game.dismiss_popup()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_state_machine.py -v`
Expected: 18 passed

- [ ] **Step 6: Run full suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all tests pass (no failures)

- [ ] **Step 7: Commit**

```bash
git add coc_bot/bot/state_machine.py tests/fakes.py tests/test_state_machine.py
git commit -m "feat: screen-driven bot loop with recovery"
```

---

### Task 10: CLI + logging

**Files:**
- Create: `coc_bot/logs.py`, `coc_bot/main.py`, `coc_bot/__main__.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `setup_logging(log_dir: Path, level: int = logging.INFO) -> Path`
  - `build_parser() -> argparse.ArgumentParser`, `main(argv: list[str] | None = None) -> int`
  - Exit codes: `0` ok, `1` fatal bot error, `2` bad input / incomplete calibration / wrong resolution, `3` ADB error.
  - Commands: `python -m coc_bot [--settings P] [--calibration P] [--templates DIR] {run|check|screenshot [--out P]|test-vision IMAGE|calibrate {template,roi,point} NAME [--image P]}`

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:
```python
import cv2
import numpy as np

from coc_bot import names as N
from coc_bot.config import Calibration, save_calibration
from coc_bot.main import main


def base_args(tmp_path):
    return ["--settings", str(tmp_path / "settings.toml"),
            "--calibration", str(tmp_path / "calibration.toml"),
            "--templates", str(tmp_path / "templates")]


def test_check_reports_missing(tmp_path, capsys):
    assert main(base_args(tmp_path) + ["check"]) == 2
    out = capsys.readouterr().out
    assert "template:home_attack" in out
    assert "roi:gold" in out
    assert "point:map_top" in out


def test_check_complete(tmp_path, capsys):
    tpl = tmp_path / "templates"
    tpl.mkdir()
    cal = Calibration()
    for name in N.REQUIRED_TEMPLATES:
        cv2.imwrite(str(tpl / f"{name}.png"), np.full((10, 10, 3), 128, np.uint8))
        cal = cal.with_entry("templates", name, (0, 0, 10, 10))
    for name in N.REQUIRED_ROIS:
        cal = cal.with_entry("rois", name, (0, 0, 10, 10))
    for name in N.required_points((1,)):
        cal = cal.with_entry("points", name, (5, 5))
    save_calibration(tmp_path / "calibration.toml", cal)
    assert main(base_args(tmp_path) + ["check"]) == 0
    assert "complete" in capsys.readouterr().out.lower()


def test_calibrate_rejects_unknown_name(tmp_path, capsys):
    assert main(base_args(tmp_path) + ["calibrate", "template", "bogus"]) == 2
    assert "Valid" in capsys.readouterr().out


def test_test_vision_missing_image(tmp_path, capsys):
    assert main(base_args(tmp_path) + ["test-vision", str(tmp_path / "nope.png")]) == 2


def test_test_vision_prints_screen(tmp_path, capsys):
    img_path = tmp_path / "shot.png"
    cv2.imwrite(str(img_path), np.zeros((720, 1280, 3), np.uint8))
    assert main(base_args(tmp_path) + ["test-vision", str(img_path)]) == 0
    assert "Screen: UNKNOWN" in capsys.readouterr().out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'coc_bot.main'`

- [ ] **Step 3: Write implementation**

`coc_bot/logs.py`:
```python
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path


def setup_logging(log_dir: Path, level: int = logging.INFO) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"bot-{date.today():%Y-%m-%d}.log"
    formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    for handler in (logging.FileHandler(path, encoding="utf-8"), logging.StreamHandler()):
        handler.setFormatter(formatter)
        root.addHandler(handler)
    return path
```

`coc_bot/__main__.py`:
```python
import sys

from coc_bot.main import main

sys.exit(main())
```

`coc_bot/main.py`:
```python
"""Command-line entry point."""
from __future__ import annotations

import argparse
import logging
import random
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from coc_bot import names as N
from coc_bot.bot.session import SessionPolicy
from coc_bot.bot.state_machine import Bot, FatalError
from coc_bot.config import Box, Settings, load_calibration, load_settings, save_calibration
from coc_bot.device.adb import AdbError, EmulatorAdb, find_adb
from coc_bot.game.actions import Game
from coc_bot.logs import setup_logging
from coc_bot.vision.ocr import OcrReader, rapidocr_engine
from coc_bot.vision.screens import detect_screen
from coc_bot.vision.templates import TemplateLibrary

log = logging.getLogger("coc_bot")
EXPECTED_SHAPE = (720, 1280)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="coc_bot", description="Clash of Clans farming bot")
    parser.add_argument("--settings", type=Path, default=Path("settings.toml"))
    parser.add_argument("--calibration", type=Path, default=Path("calibration.toml"))
    parser.add_argument("--templates", type=Path, default=Path("assets/templates"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="run the bot (Ctrl+C to stop)")
    sub.add_parser("check", help="list missing calibration items")
    shot = sub.add_parser("screenshot", help="save an emulator screenshot")
    shot.add_argument("--out", type=Path)
    vision = sub.add_parser("test-vision", help="analyse a screenshot without tapping")
    vision.add_argument("image", type=Path)
    cal = sub.add_parser("calibrate", help="mark a template / ROI / point on a screenshot")
    cal.add_argument("kind", choices=["template", "roi", "point"])
    cal.add_argument("name")
    cal.add_argument("--image", type=Path, help="use a saved screenshot instead of the emulator")
    return parser


def _templates(args: argparse.Namespace, settings: Settings) -> TemplateLibrary:
    return TemplateLibrary.load(args.templates, settings.calibration.templates,
                                settings.vision.threshold, settings.vision.search_margin_px)


def _connect(settings: Settings) -> EmulatorAdb:
    adb = EmulatorAdb(find_adb(settings.adb.adb_path), settings.adb.serial)
    adb.connect()
    return adb


def _read_image(path: Path) -> np.ndarray | None:
    image = cv2.imread(str(path)) if path.exists() else None
    if image is None:
        print(f"Cannot read image: {path}")
    return image


def _select_box(image: np.ndarray, title: str) -> Box | None:
    x, y, w, h = cv2.selectROI(title, image, showCrosshair=True, fromCenter=False)
    cv2.destroyWindow(title)
    if w == 0 or h == 0:
        return None
    return (int(x), int(y), int(w), int(h))


def cmd_check(args: argparse.Namespace, settings: Settings) -> int:
    missing = N.missing_calibration(settings, set(_templates(args, settings).names()))
    if missing:
        print("Missing calibration:")
        for item in missing:
            print(f"  {item}")
        return 2
    print("Calibration complete.")
    return 0


def cmd_calibrate(args: argparse.Namespace, settings: Settings) -> int:
    valid = N.valid_names(args.kind, settings.deploy.troop_slots)
    if args.name not in valid:
        print(f"Unknown {args.kind} name '{args.name}'. Valid: {', '.join(valid)}")
        return 2
    image = _read_image(args.image) if args.image else _connect(settings).screencap()
    if image is None:
        return 2
    box = _select_box(image, f"{args.kind}: {args.name} - drag, ENTER to confirm, C to cancel")
    if box is None:
        print("Cancelled.")
        return 1
    cal = load_calibration(args.calibration)
    x, y, w, h = box
    if args.kind == "template":
        args.templates.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(args.templates / f"{args.name}.png"), image[y:y + h, x:x + w])
        cal = cal.with_entry("templates", args.name, box)
    elif args.kind == "roi":
        cal = cal.with_entry("rois", args.name, box)
    else:
        cal = cal.with_entry("points", args.name, (x + w // 2, y + h // 2))
    save_calibration(args.calibration, cal)
    print(f"Saved {args.kind} '{args.name}': {box}")
    return 0


def cmd_screenshot(args: argparse.Namespace, settings: Settings) -> int:
    image = _connect(settings).screencap()
    out = args.out or Path("tests/fixtures") / f"screen_{datetime.now():%Y%m%d_%H%M%S}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), image)
    print(f"Saved {out} ({image.shape[1]}x{image.shape[0]})")
    return 0


def cmd_test_vision(args: argparse.Namespace, settings: Settings) -> int:
    image = _read_image(args.image)
    if image is None:
        return 2
    templates = _templates(args, settings)
    print(f"Screen: {detect_screen(image, templates).name}")
    for name in templates.names():
        match = templates.find(image, name, threshold=-1.0)
        if match is None:
            print(f"  {name:<18} (does not fit)")
            continue
        status = "MATCH" if match.score >= settings.vision.threshold else "-"
        print(f"  {name:<18} score={match.score:.3f} at {match.center} {status}")
    rois = settings.calibration.rois
    if rois:
        reader = OcrReader(rapidocr_engine())
        for name, roi in rois.items():
            limit = N.MAX_DE if name == N.ROI_DE else N.MAX_GOLD
            print(f"  OCR {name:<8} = {reader.read_number(image, roi, limit)}")
    return 0


def cmd_run(args: argparse.Namespace, settings: Settings) -> int:
    templates = _templates(args, settings)
    missing = N.missing_calibration(settings, set(templates.names()))
    if missing:
        print("Calibration incomplete, run `python -m coc_bot check`. Missing:", ", ".join(missing))
        return 2
    log_path = setup_logging(Path("logs"))
    log.info("Logging to %s", log_path)
    adb = _connect(settings)
    shape = adb.screencap().shape[:2]
    if shape != EXPECTED_SHAPE:
        log.error("Emulator resolution must be 1280x720, got %dx%d", shape[1], shape[0])
        return 2
    rng = random.Random()
    game = Game(adb, templates, OcrReader(rapidocr_engine()), settings, rng)
    bot = Bot(game, SessionPolicy(settings.session, rng), settings, rng,
              clock=datetime.now, sleep=time.sleep)
    try:
        bot.run()
    except KeyboardInterrupt:
        log.info("Stopped by user (Ctrl+C). %s", bot.stats)
    except FatalError as exc:
        game.save_debug_screenshot("fatal")
        log.error("Fatal: %s. %s", exc, bot.stats)
        return 1
    return 0


COMMANDS = {
    "run": cmd_run,
    "check": cmd_check,
    "screenshot": cmd_screenshot,
    "test-vision": cmd_test_vision,
    "calibrate": cmd_calibrate,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings(args.settings, args.calibration)
    except ValueError as exc:
        print(f"Config error: {exc}")
        return 2
    try:
        return COMMANDS[args.command](args, settings)
    except AdbError as exc:
        print(f"ADB error: {exc}")
        return 3
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_cli.py -v`
Expected: 5 passed

- [ ] **Step 5: Run full suite and CLI help**

Run: `.venv/Scripts/python -m pytest -q && .venv/Scripts/python -m coc_bot --help`
Expected: all tests pass; help lists `run, check, screenshot, test-vision, calibrate`.

- [ ] **Step 6: Commit**

```bash
git add coc_bot/logs.py coc_bot/main.py coc_bot/__main__.py tests/test_cli.py
git commit -m "feat: CLI (run/check/screenshot/test-vision/calibrate) and logging"
```

---

### Task 11: Calibration and live verification (manual, with the user)

This task needs the user at the emulator. Use a **spare CoC account**, never the main one.

**Files:**
- Create (by the tool): `settings.toml`, `calibration.toml`, `assets/templates/*.png`, `tests/fixtures/*.png`

- [ ] **Step 1: Emulator setup (user)**

LDPlayer 9 → Settings → Advanced: Resolution **1280×720 (tablet)**, DPI **240**. Settings → Others: **ADB debugging = Open local connection**. Restart LDPlayer, open CoC, zoom fully out on the home village (pinch / Ctrl+scroll). CoC keeps the zoom level between screens.

- [ ] **Step 2: Connectivity check**

```bash
cp settings.example.toml settings.toml
.venv/Scripts/python -m coc_bot screenshot
```
Expected: `Saved tests/fixtures/screen_....png (1280x720)`. If ADB error: set `[adb] adb_path` to LDPlayer's `adb.exe` and check `serial`.

- [ ] **Step 3: Calibrate templates**

For each item, navigate the game to the screen named, then run the command and drag a tight box around the element (ENTER to save):

| Screen to show | Command |
|---|---|
| Home village | `python -m coc_bot calibrate template home_attack` and `... template btn_army` |
| Army window open | `... template army_close`; with a full army: `... template army_full` |
| Army window → Quick Train tab | `... template tab_quick_train`, then `... template btn_train_saved` |
| After pressing Attack | `... template btn_find_match` |
| Searching clouds (optional) | `... template searching` |
| Enemy base preview | `... template btn_next`; `... template btn_end_battle` |
| End Battle confirm dialog | `... template popup_okay` |
| Battle result | `... template btn_return_home` |
| Connection-lost / idle dialogs (optional, when they appear) | `... template popup_reload`, `... template popup_try_again`, `... template popup_close` |

(prefix every command with `.venv/Scripts/python -m coc_bot`)

Template tips: pick the part that is unique and static (the icon/text of the button, not the animated glow).

- [ ] **Step 4: Calibrate ROIs and points on an enemy base preview**

```bash
.venv/Scripts/python -m coc_bot calibrate roi gold
.venv/Scripts/python -m coc_bot calibrate roi elixir
.venv/Scripts/python -m coc_bot calibrate roi de
.venv/Scripts/python -m coc_bot calibrate point map_top
.venv/Scripts/python -m coc_bot calibrate point map_right
.venv/Scripts/python -m coc_bot calibrate point map_bottom
.venv/Scripts/python -m coc_bot calibrate point map_left
.venv/Scripts/python -m coc_bot calibrate point troop_slot_1
```
ROI boxes: only the digits of the "Available loot" numbers (no icon). Map corners: a small box on each tip of the grass diamond. Troop slot: a small box on the goblin/barbarian card. Add `troop_slot_2` etc. if `troop_slots` in `settings.toml` lists more.

- [ ] **Step 5: Verify calibration offline**

```bash
.venv/Scripts/python -m coc_bot check
```
Expected: `Calibration complete.`

Save one screenshot per screen (`python -m coc_bot screenshot`) and run `python -m coc_bot test-vision tests/fixtures/<file>.png` on each.
Expected: correct `Screen:` for every screenshot; on base preview, OCR values match what is shown. If a template scores < 0.85 on its own screen, recalibrate it tighter; if OCR is wrong, redraw the ROI to include only the digits.

- [ ] **Step 6: First supervised live run**

In `settings.toml` set `[session] play_minutes = [10, 10]` and `[loot] max_next = 5`, then:
```bash
.venv/Scripts/python -m coc_bot run
```
Watch one full cycle: train → attack menu → search → skip/attack → battle end → return home. Stop with Ctrl+C. Check `logs/bot-YYYY-MM-DD.log` and `logs/screens/`.

- [ ] **Step 7: Endurance run (spec acceptance)**

Restore normal session values and run ≥ 2 hours on the spare account. Pass criteria: no permanent stall, recoveries logged and successful, final `Stats` show attacks > 0.

- [ ] **Step 8: Commit calibration**

```bash
git add calibration.toml assets/templates tests/fixtures
git commit -m "chore: calibration for LDPlayer 1280x720"
```
