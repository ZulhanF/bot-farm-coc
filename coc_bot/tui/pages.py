"""The dashboard's pages. Each page has `refresh_page()`, called whenever it is shown."""
from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from rich.table import Table
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, DataTable, Label, OptionList, RichLog, Sparkline, Static, Switch, TextArea
from textual.widgets.option_list import Option

from coc_bot import names as N
from coc_bot.bot.stats_report import attack_logs, log_for, read_attacks, summarize
from coc_bot.config import load_settings
from coc_bot.control import (
    BUILDER_SUB_MODES, MODE_INFO, Mode, State, connect, load_templates, mode_label, with_builder_mode,
)
from coc_bot.tui.info import SystemInfo, gather

if TYPE_CHECKING:
    from coc_bot.tui.app import DashboardApp

LOGO = """\
██████╗  ██████╗ ████████╗    ███████╗ █████╗ ██████╗ ███╗   ███╗
██╔══██╗██╔═══██╗╚══██╔══╝    ██╔════╝██╔══██╗██╔══██╗████╗ ████║
██████╔╝██║   ██║   ██║       █████╗  ███████║██████╔╝██╔████╔██║
██╔══██╗██║   ██║   ██║       ██╔══╝  ██╔══██║██╔══██╗██║╚██╔╝██║
██████╔╝╚██████╔╝   ██║       ██║     ██║  ██║██║  ██║██║ ╚═╝ ██║
╚═════╝  ╚═════╝    ╚═╝       ╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝"""
LOGO_COLORS = ("#ffd75f", "#ffc040", "#ffa94d", "#f08a8a", "#d97adf", "#b56cf0")
RESOURCE_COLORS = {"gold": "#ffc83d", "elixir": "#e05ce6", "de": "#9a7bd6"}
RESOURCE_NAMES = {"gold": "gold", "elixir": "elixir", "de": "DE"}
LEVEL_STYLES = {"WARNING": "yellow", "ERROR": "bold red", "CRITICAL": "bold white on red", "DEBUG": "dim"}


def logo() -> Text:
    text = Text()
    for i, line in enumerate(LOGO.splitlines()):
        text.append(line + "\n", style=f"bold {LOGO_COLORS[i % len(LOGO_COLORS)]}")
    return text


def meter(fraction: float | None, color: str, width: int = 12) -> Text:
    if fraction is None:
        return Text("?".ljust(width + 5), style="dim")
    filled = round(max(0.0, min(fraction, 1.0)) * width)
    return Text.assemble(("█" * filled, color), ("░" * (width - filled), "grey35"),
                         (f" {fraction:4.0%}", "bold"))


_LOG_RE = re.compile(r"^(?:\d{4}-\d\d-\d\d )?(\d\d:\d\d:\d\d)(?:,\d+)? +(\w+) +[\w.]+: (.*)$")


def log_line(line: str) -> Text:
    """`2026-11-12 08:20:31,596 INFO    coc_bot.x: msg` -> `08:20:31 INFO  msg`, coloured by level."""
    m = _LOG_RE.match(line)
    if not m:
        return Text(line)
    clock, level, message = m.groups()
    style = LEVEL_STYLES.get(level, "")
    return Text.assemble((clock + " ", "dim"), (f"{level:<7} ", style or "cyan"), (message, style))


def ok(flag: bool, yes: str, no: str) -> Text:
    return Text(f"✓ {yes}", style="green") if flag else Text(f"✗ {no}", style="red")


class Page(Vertical):
    @property
    def dash(self) -> DashboardApp:
        return self.app  # type: ignore[return-value]

    def refresh_page(self) -> None:
        pass


# --- 1. Beranda ----------------------------------------------------------------------------------
class HomePage(Page):
    def compose(self) -> ComposeResult:
        yield Static(logo(), id="logo")
        yield Static(id="tagline")
        with Horizontal(id="home-row"):
            yield Static(id="sysinfo", classes="panel")
            yield Static(id="quickstart", classes="panel")

    def on_mount(self) -> None:
        self.query_one("#sysinfo").border_title = "sistem"
        self.query_one("#quickstart").border_title = "menu"
        self.query_one("#tagline", Static).update(Text.assemble(
            ("  Bot Farm COC ", "bold"), (f"v{SystemInfo().version}", "dim"),
            ("  ·  auto-farm Clash of Clans di LDPlayer", "dim")))
        self.query_one("#quickstart", Static).update(self._menu())
        self.query_one("#sysinfo", Static).update(Text("Memeriksa emulator…", style="dim italic"))

    def refresh_page(self) -> None:
        self.load_info()

    def _menu(self) -> Table:
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold #ffc83d", justify="right")
        table.add_column()
        for key, label, hint in (
            ("1", "Beranda", "info sistem (R = segarkan)"),
            ("2", "Bot", "mulai / jeda / stop + log live"),
            ("3", "Mode", "pilih apa yang dijalankan"),
            ("4", "Kalibrasi", "item ✓/✗, Enter = kalibrasi"),
            ("5", "Pengaturan", "edit settings.toml"),
            ("6", "Log", "log hari ini"),
            ("7", "Statistik", "serangan/jam, menang, siklus"),
            ("8", "Tes vision", "apa yang dilihat bot"),
            ("S", "Start/Stop", "dari halaman mana pun"),
            ("C", "Cek storage", "on / off"),
            ("Q", "Keluar", ""),
        ):
            table.add_row(key, Text.assemble((label, "bold"), ("  " + hint, "dim")))
        return table

    @work(thread=True, exclusive=True, group="info")
    def load_info(self) -> None:
        info = gather(self.dash.paths, self.dash.probe_emulator, self.dash.mode.value,
                      self.dash.runner.builder_mode)
        self.app.call_from_thread(self._show_info, info)

    def _show_info(self, info: SystemInfo) -> None:
        self.query_one("#sysinfo", Static).update(
            self.render_info(info, mode_label(self.dash.mode, self.dash.runner.builder_mode),
                             self.dash.runner.check_storage))

    @staticmethod
    def render_info(info: SystemInfo, mode_text: str, check_storage: bool = True) -> Table:
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold #ffc83d", no_wrap=True)
        table.add_column()
        table.add_row(Text("bot@farm", style="bold #e05ce6"), Text(f"v{info.version}", style="dim"))
        table.add_row("─" * 9, Text("─" * 30, style="dim"))
        if info.settings_error:
            table.add_row("Config", Text(f"✗ {info.settings_error}", style="red"))
            return table
        emu = Text(f"{info.serial} ")
        emu.append_text(ok(info.online, "online", "offline (jalankan LDPlayer, R)"))
        table.add_row("Emulator", emu)
        if info.resolution:
            res = f"{info.resolution[0]}x{info.resolution[1]}"
            table.add_row("Resolusi", ok(info.resolution_ok, res, f"{res} (harus 1280x720)"))
        if info.screen:
            table.add_row("Layar", info.screen)
        table.add_row("Kalibrasi", ok(not info.missing, "lengkap", f"{len(info.missing)} item kurang (menu 4)"))
        if info.storage:
            for res, level in info.storage.items():
                table.add_row(f"Storage {RESOURCE_NAMES[res]}", meter(level, RESOURCE_COLORS[res]))
        elif info.storage_checks and info.online:
            table.add_row("Storage", Text("buka desa untuk membaca bar", style="dim"))
        checks = ", ".join(RESOURCE_NAMES[r] for r in info.storage_checks)
        if not check_storage:
            table.add_row("Cek penuh", Text("OFF (dimatikan, tombol C)", style="yellow"))
        elif checks:
            table.add_row("Cek penuh", Text(f"ON: {checks} ≥{info.full_ratio:.0%} → {info.on_full}"))
        else:
            table.add_row("Cek penuh", Text("OFF (kalibrasi bar storage)", style="yellow"))
        table.add_row("Mode", Text(mode_text, style="bold"))
        table.add_row("Deploy", f"{info.pattern}, slot {', '.join(map(str, info.troop_slots)) or '-'}")
        table.add_row("Spell", f"slot {', '.join(map(str, info.spell_slots))}" if info.spell_slots else "off")
        g, e, d = info.min_loot
        table.add_row("Loot min", f"gold {g:,} · elixir {e:,} · DE {d:,}".replace(",", "."))
        table.add_row("Sesi", info.session)
        table.add_row("Python", f"{info.python} · {info.os}")
        palette = Text()
        for color in ("#1e1e2e", "#f38ba8", "#a6e3a1", "#ffc83d", "#89b4fa", "#e05ce6", "#94e2d5", "#cdd6f4"):
            palette.append("███", style=color)
        table.add_row("", "")
        table.add_row("", palette)
        return table


# --- 2. Bot ----------------------------------------------------------------------------------------
class BotPage(Page):
    def compose(self) -> ComposeResult:
        with Horizontal(id="bot-top"):
            yield Static(id="bot-status", classes="panel")
            with Vertical(id="bot-buttons", classes="panel"):
                yield Button("▶ Mulai", id="btn-start", variant="success")
                yield Button("⏸ Jeda", id="btn-pause", variant="warning")
                yield Button("■ Stop", id="btn-stop", variant="error")
                with Horizontal(id="storage-toggle"):
                    yield Switch(value=True, id="sw-storage")
                    yield Label("Cek storage\npenuh (C)", id="sw-storage-label")
        yield RichLog(id="bot-log", max_lines=3000, wrap=True, classes="panel")

    def on_mount(self) -> None:
        self.query_one("#bot-status").border_title = "status"
        self.query_one("#bot-buttons").border_title = "kontrol"
        self.query_one("#bot-log").border_title = "log live"
        self.update_status()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        actions = {"btn-start": self.dash.action_start, "btn-pause": self.dash.action_pause,
                   "btn-stop": self.dash.action_stop}
        if event.button.id in actions:
            actions[event.button.id]()

    def on_switch_changed(self, event: Switch.Changed) -> None:
        if event.switch.id == "sw-storage" and event.value != self.dash.runner.check_storage:
            self.dash.set_check_storage(event.value)

    def write_log(self, line: str) -> None:
        self.query_one("#bot-log", RichLog).write(log_line(line))

    def update_status(self) -> None:
        status = self.dash.runner.status()
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold #ffc83d", no_wrap=True)
        table.add_column()
        table.add_row("Status", state_text(status.state))
        table.add_row("Mode", mode_label(status.mode, status.builder_mode))
        table.add_row("Layar", status.screen or "-")
        running = status.state in (State.RUNNING, State.PAUSED, State.STOPPING)
        if status.started_at and running:
            elapsed = datetime.now() - status.started_at
            hours = elapsed.total_seconds() / 3600
            table.add_row("Durasi", str(elapsed).split(".")[0])
            table.add_row("Serangan", f"{status.stats.attacks}  ({status.stats.per_hour(hours)})")
        else:
            table.add_row("Serangan", str(status.stats.attacks))
        if status.mode is Mode.BUILDER:
            table.add_row("Cart diklaim", str(status.stats.carts))
            table.add_row("Tahap 2", str(status.stats.stage2))
        else:
            table.add_row("Dilewati", str(status.stats.skipped))
        table.add_row("Recovery", f"{status.stats.recoveries} (restart {status.stats.restarts})")
        table.add_row("Cek storage", Text("ON", style="green") if self.dash.runner.check_storage
                      else Text("OFF (tetap menyerang walau penuh)", style="yellow"))
        if status.error:
            table.add_row("Error", Text(status.error, style="red"))
        self.query_one("#bot-status", Static).update(table)
        switch = self.query_one("#sw-storage", Switch)
        if switch.value != self.dash.runner.check_storage:
            switch.value = self.dash.runner.check_storage
        self.query_one("#btn-start", Button).disabled = self.dash.runner.active
        pause = self.query_one("#btn-pause", Button)
        pause.label = "⏵ Lanjut" if status.state is State.PAUSED else "⏸ Jeda"
        pause.disabled = status.state not in (State.RUNNING, State.PAUSED)
        self.query_one("#btn-stop", Button).disabled = not self.dash.runner.active or status.state is State.STOPPING


STATE_STYLES = {
    State.IDLE: ("○ siap", "dim"), State.STARTING: ("◌ memulai…", "cyan"),
    State.RUNNING: ("● berjalan", "bold green"), State.PAUSED: ("❚❚ dijeda", "bold yellow"),
    State.STOPPING: ("◌ berhenti…", "yellow"), State.STOPPED: ("■ berhenti", "dim"),
    State.ERROR: ("✗ error", "bold red"),
}


def state_text(state: State) -> Text:
    label, style = STATE_STYLES[state]
    return Text(label, style=style)


# --- 3. Mode ---------------------------------------------------------------------------------------
class ModePage(Page):
    def compose(self) -> ComposeResult:
        yield Static("Pilih mode yang dijalankan saat bot dimulai (Enter). Mode lain menyusul — "
                     "lihat docs/ROADMAP.md.", classes="hint")
        options = []
        for mode, (desc, available) in MODE_INFO.items():
            if mode is Mode.BUILDER:
                for sub, sub_desc in BUILDER_SUB_MODES.items():
                    prompt = Text.assemble((f"{'builder ' + sub:<15}", "bold"), ("  " + sub_desc, ""))
                    options.append(Option(prompt, id=f"builder:{sub}"))
                continue
            prompt = Text.assemble((f"{mode.value:<15}", "bold"), ("  " + desc, "" if available else "dim"),
                                   ("" if available else "  (segera)", "italic dim"))
            options.append(Option(prompt, id=mode.value, disabled=not available))
        yield OptionList(*options, id="mode-list", classes="panel")

    def on_mount(self) -> None:
        self.query_one("#mode-list").border_title = "mode"

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        value, _, sub = event.option.id.partition(":")
        mode = Mode(value)
        if self.dash.runner.active:
            self.app.notify("Hentikan bot dulu untuk ganti mode.", severity="warning")
            return
        self.dash.set_mode(mode, sub or None)
        self.app.notify(f"Mode: {mode_label(mode, sub or None)}")


# --- 4. Kalibrasi ----------------------------------------------------------------------------------
class CalibrationPage(Page):
    BINDINGS = [("a", "toggle_all", "Semua item")]

    def compose(self) -> ComposeResult:
        yield Static("Enter = kalibrasi item terpilih: jendela OpenCV terbuka dengan screenshot emulator. "
                     "Seret kotak, ENTER simpan, C batal.  A = tampilkan semua / hanya yang dipakai.",
                     classes="hint")
        yield Static(id="cal-summary")
        yield DataTable(id="cal-table", cursor_type="row", zebra_stripes=True, classes="panel")

    def on_mount(self) -> None:
        self._show_all = False
        table = self.query_one("#cal-table", DataTable)
        table.add_columns("", "jenis", "nama", "nilai", "keterangan")

    def action_toggle_all(self) -> None:
        self._show_all = not self._show_all
        self.refresh_page()

    def refresh_page(self) -> None:
        table = self.query_one("#cal-table", DataTable)
        summary = self.query_one("#cal-summary", Static)
        table.clear()
        try:
            settings = with_builder_mode(load_settings(self.dash.paths.settings, self.dash.paths.calibration),
                                         self.dash.mode, self.dash.runner.builder_mode)
            templates = load_templates(self.dash.paths, settings)
        except (ValueError, OSError) as exc:
            summary.update(Text(f"✗ {exc}", style="red"))
            return
        mode = self.dash.mode.value
        missing = set(N.missing_for_mode(settings, set(templates.names()), mode))
        cal = settings.calibration
        have = {"template": cal.templates, "roi": cal.rois, "point": cal.points}
        relevant = N.relevant_for_mode(settings, mode)
        if self._show_all:
            items = [(k, n) for k in ("template", "roi", "point")
                     for n in N.valid_names(k, N.used_slots(settings))]
        else:
            items = relevant
        rows = []
        for kind, name in items:
            key = f"{kind}:{name}"
            value = have[kind].get(name)
            if kind == "template" and name not in templates.names():
                value = None
            if key in missing:
                mark, note = Text("✗", style="bold red"), Text("wajib, belum ada", style="red")
            elif value is not None:
                mark, note = Text("✓", style="green"), Text("")
            elif (kind, name) in relevant:
                mark, note = Text("·", style="dim"), Text("opsional", style="dim")
            else:
                mark, note = Text("·", style="dim"), Text("tidak dipakai setting sekarang", style="dim")
            rows.append((key not in missing, value is None, kind, name, mark, value, note))
        rows.sort(key=lambda r: (r[0], r[1]))   # missing first, then calibrated, then unset
        for _ok, _unset, kind, name, mark, value, note in rows:
            table.add_row(mark, kind, name, "-" if value is None else str(list(value)), note,
                          key=f"{kind}:{name}")
        table.border_title = "semua item" if self._show_all else "item yang dipakai setting sekarang"
        summary.update(Text(f"  ✓ Kalibrasi lengkap ({len(rows)} item)", style="green") if not missing
                       else Text(f"  ✗ {len(missing)} item wajib belum dikalibrasi", style="bold red"))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        kind, name = str(event.row_key.value).split(":", 1)
        self.app.notify(f"Membuka jendela kalibrasi {kind} '{name}'…")
        self.calibrate(kind, name)

    @work(thread=True, exclusive=True, group="calibrate")
    def calibrate(self, kind: str, name: str) -> None:
        p = self.dash.paths
        cmd = [sys.executable, "-m", "coc_bot", "--settings", str(p.settings),
               "--calibration", str(p.calibration), "--templates", str(p.templates), "calibrate", kind, name]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            output = (proc.stdout + proc.stderr).strip().splitlines()
            message, failed = (output[-1] if output else "selesai"), proc.returncode not in (0, 1)
        except (OSError, subprocess.TimeoutExpired) as exc:
            message, failed = str(exc), True
        self.app.call_from_thread(self._calibrated, message, failed)

    def _calibrated(self, message: str, failed: bool) -> None:
        self.app.notify(message, severity="error" if failed else "information", timeout=6)
        self.refresh_page()


# --- 5. Pengaturan ---------------------------------------------------------------------------------
class SettingsPage(Page):
    def compose(self) -> ComposeResult:
        yield Static("Edit settings.toml langsung. Ctrl+S = simpan (divalidasi dulu), Ctrl+R = muat ulang. "
                     "Berlaku saat bot dimulai berikutnya.", classes="hint")
        yield TextArea(id="settings-editor", show_line_numbers=True, tab_behavior="indent", classes="panel")
        with Horizontal(id="settings-buttons"):
            yield Button("Simpan", id="btn-save", variant="primary")
            yield Button("Muat ulang", id="btn-reload")

    BINDINGS = [("ctrl+s", "save", "Simpan"), ("ctrl+r", "reload", "Muat ulang")]

    def on_mount(self) -> None:
        editor = self.query_one("#settings-editor", TextArea)
        editor.border_title = str(self.dash.paths.settings)
        try:
            editor.language = "toml"
        except Exception:  # noqa: BLE001 - syntax highlighting is optional (textual[syntax])
            pass
        self.action_reload()

    def action_reload(self) -> None:
        path = self.dash.paths.settings
        example = Path("settings.example.toml")
        if path.exists():
            text = path.read_text(encoding="utf-8")
        elif example.exists():
            text = example.read_text(encoding="utf-8")
            self.app.notify(f"{path} belum ada, diisi dari {example}", severity="warning")
        else:
            text = ""
        self.query_one("#settings-editor", TextArea).load_text(text)

    def action_save(self) -> None:
        text = self.query_one("#settings-editor", TextArea).text
        error = validate_settings_text(text, self.dash.paths.calibration)
        if error:
            self.app.notify(error, title="Tidak disimpan", severity="error", timeout=8)
            return
        self.dash.paths.settings.write_text(text, encoding="utf-8")
        self.app.notify("settings.toml tersimpan" + (" — berlaku saat bot dimulai ulang"
                                                     if self.dash.runner.active else ""))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-save":
            self.action_save()
        elif event.button.id == "btn-reload":
            self.action_reload()


def validate_settings_text(text: str, calibration: Path) -> str | None:
    """Error message, or None if `text` is a valid settings.toml."""
    import tempfile

    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return f"TOML salah: {exc}"
    with tempfile.TemporaryDirectory() as tmp:
        candidate = Path(tmp) / "settings.toml"
        candidate.write_text(text, encoding="utf-8")
        try:
            load_settings(candidate, calibration)
        except (ValueError, TypeError) as exc:
            return str(exc)
    return None


# --- 6. Log ------------------------------------------------------------------------------------------
class LogPage(Page):
    TAIL_LINES = 400

    def compose(self) -> ComposeResult:
        yield RichLog(id="file-log", max_lines=5000, wrap=False, classes="panel")

    def on_mount(self) -> None:
        self._path: Path | None = None
        self._offset = 0
        self.set_interval(1.0, self.poll)

    def refresh_page(self) -> None:
        self.poll()

    def poll(self) -> None:
        path = self.dash.paths.logs / f"bot-{date.today():%Y-%m-%d}.log"
        log = self.query_one("#file-log", RichLog)
        if path != self._path:
            self._path, self._offset = path, 0
            log.clear()
            log.border_title = str(path)
            if path.exists():
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                for line in lines[-self.TAIL_LINES:]:
                    log.write(log_line(line))
                self._offset = path.stat().st_size
            return
        if not path.exists() or path.stat().st_size <= self._offset:
            return
        with path.open("rb") as fh:
            fh.seek(self._offset)
            chunk = fh.read()
        self._offset += len(chunk)
        for line in chunk.decode("utf-8", errors="replace").splitlines():
            log.write(log_line(line))


# --- 7. Statistik ----------------------------------------------------------------------------------
class StatsPage(Page):
    def compose(self) -> ComposeResult:
        with Horizontal(id="stats-row"):
            yield Static(id="stats-today", classes="panel")
            yield Static(id="stats-all", classes="panel")
        with Vertical(id="stats-spark-box", classes="panel"):
            yield Sparkline([0] * 24, id="stats-spark")
            yield Static(Text("".join(f"{h:02d}".ljust(12) for h in (0, 6, 12, 18)).rstrip()
                              .ljust(46) + "23", style="dim"), id="stats-hours")
        yield DataTable(id="stats-table", zebra_stripes=True, classes="panel")

    def on_mount(self) -> None:
        self.query_one("#stats-today").border_title = "hari ini"
        self.query_one("#stats-all").border_title = "semua log"
        self.query_one("#stats-spark-box").border_title = "serangan per jam (hari ini)"
        table = self.query_one("#stats-table", DataTable)
        table.border_title = "serangan terakhir"
        table.add_columns("waktu", "siklus", "battle", "damage", "hasil")
        self.set_interval(15.0, self.refresh_page)

    def refresh_page(self) -> None:
        logs = self.dash.paths.logs
        today = read_attacks(log_for(logs, date.today()))
        everything = [a for path in attack_logs(logs) for a in read_attacks(path)]
        today_sum, all_sum = summarize(today), summarize(everything)
        self.query_one("#stats-today", Static).update(summary_table(today_sum))
        self.query_one("#stats-all", Static).update(summary_table(all_sum))
        self.query_one("#stats-spark", Sparkline).data = today_sum.per_hour
        table = self.query_one("#stats-table", DataTable)
        table.clear()
        for a in reversed(everything[-30:]):
            won = a.damage_pct is not None and a.damage_pct >= 50
            table.add_row(f"{a.time:%d/%m %H:%M:%S}", secs(a.cycle_s), secs(a.battle_s),
                          "-" if a.damage_pct is None else f"{a.damage_pct}%",
                          Text("menang", style="green") if won else Text("kalah", style="red"))


def secs(value: float | None) -> str:
    return "-" if value is None else f"{value:.0f}s"


def summary_table(s) -> Table:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold #ffc83d", no_wrap=True)
    table.add_column()
    if not s.attacks:
        table.add_row("Serangan", Text("belum ada data", style="dim"))
        return table
    rate = f"  (~{3600 / s.avg_cycle_s:.0f}/jam saat jalan)" if s.avg_cycle_s else ""
    table.add_row("Serangan", f"{s.attacks}{rate}")
    table.add_row("Menang ≥50%", f"{s.wins}  ({s.win_rate:.0%})")
    table.add_row("Rata siklus", secs(s.avg_cycle_s))
    table.add_row("Rata battle", secs(s.avg_battle_s))
    table.add_row("Rata damage", "-" if s.avg_damage is None else f"{s.avg_damage:.0f}%")
    return table


# --- 8. Tes vision ---------------------------------------------------------------------------------
class VisionPage(Page):
    def compose(self) -> ComposeResult:
        yield Static("Ambil screenshot emulator dan lihat apa yang dibaca bot (tanpa tap). "
                     "OCR dimuat saat pertama kali dipakai (beberapa detik).", classes="hint")
        with Horizontal(id="vision-buttons"):
            yield Button("📷 Analisa layar", id="btn-analyse", variant="primary")
            yield Button("💾 Simpan screenshot", id="btn-shot")
        yield Static(id="vision-screen")
        with Horizontal(id="vision-row"):
            yield DataTable(id="vision-templates", zebra_stripes=True, classes="panel")
            yield DataTable(id="vision-rois", zebra_stripes=True, classes="panel")

    def on_mount(self) -> None:
        t = self.query_one("#vision-templates", DataTable)
        t.border_title = "template"
        t.add_columns("nama", "skor", "posisi", "")
        r = self.query_one("#vision-rois", DataTable)
        r.border_title = "ROI (bar / OCR)"
        r.add_columns("nama", "jenis", "nilai")
        self._reader = None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-analyse":
            self.query_one("#vision-row").loading = True
            self.analyse()
        elif event.button.id == "btn-shot":
            self.save_shot()

    @work(thread=True, exclusive=True, group="vision")
    def analyse(self) -> None:
        from coc_bot.vision.ocr import OcrReader, rapidocr_engine
        from coc_bot.vision.report import analyse

        try:
            settings = load_settings(self.dash.paths.settings, self.dash.paths.calibration)
            templates = load_templates(self.dash.paths, settings)
            image = connect(settings).screencap()
            if self._reader is None:
                self._reader = OcrReader(rapidocr_engine())
            report = analyse(image, settings, templates, self._reader)
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(self._failed, str(exc))
            return
        self.app.call_from_thread(self._show, report, image.shape)

    def _failed(self, message: str) -> None:
        self.query_one("#vision-row").loading = False
        self.app.notify(message, title="Tes vision gagal", severity="error", timeout=8)

    def _show(self, report, shape) -> None:
        self.query_one("#vision-row").loading = False
        self.query_one("#vision-screen", Static).update(Text.assemble(
            ("  Layar terdeteksi: ", "bold"), (report.screen, "bold #ffc83d"),
            (f"   ({shape[1]}x{shape[0]}, {datetime.now():%H:%M:%S})", "dim")))
        t = self.query_one("#vision-templates", DataTable)
        t.clear()
        for s in sorted(report.templates, key=lambda s: -(s.score or -1)):
            t.add_row(s.name, "-" if s.score is None else f"{s.score:.3f}",
                      "-" if s.center is None else str(s.center),
                      Text("MATCH", style="bold green") if s.match else Text("·", style="dim"))
        r = self.query_one("#vision-rois", DataTable)
        r.clear()
        for reading in report.rois:
            if reading.kind == "bar":
                value = "?" if reading.value is None else f"{reading.value:.0%} penuh"
            else:
                value = "?" if reading.value is None else f"{reading.value:,}".replace(",", ".")
            r.add_row(reading.name, reading.kind, value)

    @work(thread=True, exclusive=True, group="vision")
    def save_shot(self) -> None:
        import cv2

        try:
            settings = load_settings(self.dash.paths.settings, self.dash.paths.calibration)
            image = connect(settings).screencap()
            out = Path("tests/fixtures") / f"screen_{datetime.now():%Y%m%d_%H%M%S}.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(out), image)
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(self.app.notify, str(exc), severity="error")
            return
        self.app.call_from_thread(self.app.notify, f"Tersimpan: {out}")
