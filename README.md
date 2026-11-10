<p align="center">
  <img src="assets/banner.svg" alt="Bot Farm COC — vision-driven auto-farming for Android emulators" width="100%">
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white">
  <img alt="Platform" src="https://img.shields.io/badge/platform-Windows-0078D6?logo=windows&logoColor=white">
  <img alt="Emulator" src="https://img.shields.io/badge/emulator-LDPlayer%209-1f6feb">
  <img alt="Vision" src="https://img.shields.io/badge/vision-OpenCV%20%2B%20RapidOCR-5C3EE8?logo=opencv&logoColor=white">
  <img alt="Tests" src="https://img.shields.io/badge/tests-pytest-0A9EDC?logo=pytest&logoColor=white">
</p>

<p align="center">
  A screen-reading farming bot for Clash of Clans running in an Android emulator.<br>
  It sees the game through ADB screenshots, reads loot with OCR, and plays the attack loop on its own —
  no memory reading, no packet tampering, no modified game files.
</p>

---

> [!WARNING]
> **Use at your own risk.** Automating gameplay violates Supercell's
> [Terms of Service](https://supercell.com/en/terms-of-service/), and Supercell runs regular ban waves
> that **permanently** ban bot accounts. Test on a spare account, never on your main one.
> This project is for learning and is not affiliated with, endorsed by, or sponsored by Supercell.

## Table of contents

- [Features](#features)
- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Installation](#installation)
- [Calibration](#calibration)
- [Configuration](#configuration)
- [Usage](#usage)
- [Logs and statistics](#logs-and-statistics)
- [Project structure](#project-structure)
- [Development](#development)
- [Troubleshooting](#troubleshooting)

## Features

- **Fast win farming** — attacks, waits until **50 % destruction** (one star = win and league bonus),
  then surrenders early to start the next battle. Built for the *Clash Anytime* era with no training time.
- **Loot filter** — reads the enemy's available Gold / Elixir / Dark Elixir with OCR and skips bases below
  your thresholds, with a cap on how many times it presses *Next*.
- **Configurable deployment** — troops along calibrated "clock" lines or the map diamond (`v_top`,
  `v_bottom`, `all`), plus siege machine and heroes with automatic ability activation.
- **Storage-full check** — reads your own Gold / Elixir before each attack and stops (or waits) when your
  storages are full, so no loot goes to waste.
- **Self-recovery** — detects popups, stuck screens and lost connections; escalates from *Back* to a full
  game restart, with a no-progress watchdog so a long unattended run never hangs silently.
- **Human-like timing** — random tap jitter and delays, optional play/break sessions with daily hour caps.
- **Background-friendly** — all input and capture go through ADB, the emulator window does not need focus.
- **Easy calibration** — mark buttons, text regions and points on a live screenshot; recalibrate after a
  game update instead of retraining a model.

## How it works

```text
             ┌──────────────── ADB (screencap / input tap) ────────────────┐
             │                                                             │
  LDPlayer ──┤   screenshot ──► detect screen ──► state handler ──► taps   ├── LDPlayer
             │                  (OpenCV templates)   │                     │
             └───────────────────────────────────────┼─────────────────────┘
                                                     ▼
                                         RapidOCR: loot, storage, damage %
```

Every tick the bot takes a screenshot, identifies the current screen and runs the handler for it:

```text
HOME ─► ATTACK_MENU ─► SEARCHING ─► BASE_PREVIEW ─┬─(loot too low)─► Next ─┐
  ▲                                               │                        │
  │                                               └─(loot ok)─► BATTLE ◄───┘
  │                                                                │ 50 % / stalled / timeout
  └───────────────────────── RESULT ◄──────── surrender ◄──────────┘
```

Popups are dismissed whenever they appear. If the screen stops moving forward, the bot presses *Back*,
then restarts the game, and finally stops safely with a screenshot in `logs/screens/` for diagnosis.

## Requirements

| | |
|---|---|
| **OS** | Windows 10/11 |
| **Python** | 3.12 (pinned in `pyproject.toml`) |
| **Emulator** | LDPlayer 9 (any emulator reachable over ADB should work) |
| **Resolution** | **1280 × 720, 240 DPI** — the bot refuses to run at any other size |
| **ADB** | Bundled with LDPlayer (`LDPlayer9\adb.exe`) or Android platform-tools on `PATH` |
| **GPU** | Not required — all vision runs on the CPU |

## Installation

```powershell
git clone https://github.com/ZulhanF/bot-farm-coc.git
cd bot-farm-coc
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy settings.example.toml settings.toml
```

Then prepare the emulator:

1. LDPlayer → **Settings → Advanced**: resolution **1280 × 720 (tablet)**, DPI **240**.
2. LDPlayer → **Settings → Others**: set **ADB debugging** to **Open local connection**.
3. Restart LDPlayer, open the game and **zoom fully out** on your village.
4. Check the connection:

```powershell
.venv\Scripts\python -m coc_bot screenshot
```

If ADB is not found, set `[adb] adb_path` in `settings.toml` (for example `D:\LDPlayer\LDPlayer9\adb.exe`).

## Calibration

The bot finds buttons by small template images and reads numbers from fixed regions. You mark both once
on a live screenshot: drag a box, press **Enter** to save, **C** to cancel.

```powershell
.venv\Scripts\python -m coc_bot calibrate <template|roi|point> <name>
```

| Kind | Names | Where |
|---|---|---|
| `template` (required) | `home_attack`, `btn_find_match`, `btn_attack`, `btn_next`, `btn_end_battle`, `btn_return_home`, `popup_okay` | the screen where each button is visible |
| `template` (optional) | `btn_surrender`, `searching`, `army_close`, `popup_reload`, `popup_try_again`, `popup_close` | as they appear |
| `roi` | `gold`, `elixir`, `de` | enemy base preview — only the loot digits, no icon |
| `roi` | `home_gold`, `home_elixir`, `home_de` | your village, top-right resource counters |
| `point` | `map_11`, `map_9`, `map_1`, `map_3` | edges of the battlefield for the deploy lines |
| `point` | `troop_slot_N` | each troop / siege / hero card in the bottom bar |

Verify that everything needed by your settings is present, and test detection offline on any screenshot:

```powershell
.venv\Scripts\python -m coc_bot check
.venv\Scripts\python -m coc_bot test-vision path\to\screenshot.png
```

> [!TIP]
> Pick the static, unique part of a button (its icon or text) rather than its animated glow.
> After a game update that moves buttons, just recalibrate the affected templates.

## Configuration

All settings live in `settings.toml` (copied from [`settings.example.toml`](settings.example.toml)).
Calibration data is written to `calibration.toml` by the `calibrate` command.

| Section | Key settings |
|---|---|
| `[loot]` | `min_gold`, `min_elixir`, `min_de`, `max_next` — `0` / `0` / `0` / `0` attacks the first base found |
| `[deploy]` | `pattern`, `points_per_side`, `taps_per_point`, `troop_slots`, `siege_slot`, `hero_slots` |
| `[timing]` | `battle_timeout_s`, `damage_stagnant_s`, `tap_delay_ms`, `tap_jitter_px`, `progress_timeout_s` |
| `[storage]` | `gold_cap`, `elixir_cap`, `de_cap`, `full_ratio`, `on_full` (`"stop"` / `"wait"`) |
| `[session]` | `enabled`, `play_minutes`, `break_minutes`, `active_hours`, `max_hours_per_day` |

Example for quick win farming with a storage check:

```toml
[loot]
min_gold = 0
min_elixir = 0
max_next = 0             # attack the first base: chase the win bonus, not big loot

[storage]
gold_cap = 24000000      # your storage capacity
elixir_cap = 24000000
on_full = "stop"

[session]
enabled = true           # breaks and daily caps make the bot look less like a bot
```

> [!IMPORTANT]
> Running 24/7 with `session.enabled = false` is the easiest pattern for anti-bot systems to spot.

## Usage

| Command | What it does |
|---|---|
| `python -m coc_bot run` | Start farming. **Ctrl+C** stops cleanly. |
| `python -m coc_bot check` | List calibration items still missing for your settings. |
| `python -m coc_bot screenshot [--out file.png]` | Save an emulator screenshot (default `tests/fixtures/`). |
| `python -m coc_bot test-vision <image>` | Show detected screen, template scores and OCR results — no taps. |
| `python -m coc_bot calibrate <kind> <name> [--image file]` | Mark a template, region or point. |

Run all commands from the repository root with `.venv\Scripts\python`.

Exit codes: `0` ok · `1` fatal bot error · `2` configuration or calibration problem · `3` ADB error.

## Logs and statistics

- `logs/bot-YYYY-MM-DD.log` — every state change, loot reading, decision and recovery, plus attacks per hour.
- `logs/attacks-YYYY-MM-DD.csv` — one row per attack: time, cycle time, battle time, damage %, preview loot.
- `logs/screens/` — screenshots saved only on recovery, fatal errors and crashes.

## Project structure

```text
coc_bot/
├── device/adb.py          ADB connection, screencap, tap, app start/stop
├── vision/
│   ├── templates.py       template matching inside calibrated boxes
│   ├── ocr.py             single-line RapidOCR number reader
│   └── screens.py         which screen is showing
├── game/
│   ├── actions.py         high-level actions (find match, deploy, surrender, …)
│   ├── deploy.py          deploy point geometry
│   └── loot.py            attack decision and storage-full check
├── bot/
│   ├── state_machine.py   main loop, stuck detection, recovery
│   ├── session.py         active hours, breaks, daily cap
│   └── records.py         per-attack CSV log
├── config.py              settings.toml / calibration.toml loading
├── names.py               shared template / ROI / point names
└── main.py                command-line interface
assets/templates/          calibrated button images
tests/                     unit tests (no emulator needed)
```

## Development

The game logic is pure Python over screenshots, so the whole suite runs without an emulator:

```powershell
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pytest -q
```

Design notes and the original implementation plan are in [`docs/superpowers/`](docs/superpowers/).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Emulator resolution must be 1280x720` | Set LDPlayer to 1280 × 720, 240 DPI, and restart it. |
| `ADB error … timed out` / `device offline` | Usually the emulator is short on RAM/CPU during the battle → village transition. Give LDPlayer more resources and close other tools that run their own `adb` (Android Studio, scrcpy, other emulators). |
| Loot always reads `0` or a wrong number | Recalibrate the `gold` / `elixir` ROI tightly around the digits only, then confirm with `test-vision`. |
| A button is never found | Recalibrate that template; check its score in `test-vision` (it should be ≥ 0.85 on its own screen). |
| Bot stops with `Storage full` | Expected when `[storage]` caps are set — spend resources, or use `on_full = "wait"`. |

---

<p align="center">
  <sub>Not affiliated with Supercell. "Clash of Clans" is a trademark of Supercell Oy.</sub>
</p>
