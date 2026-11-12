"""Terminal dashboard (Textual): `python -m coc_bot`."""
from __future__ import annotations

import logging
from collections import deque
from datetime import datetime

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.theme import Theme
from textual.widgets import ContentSwitcher, Footer, OptionList, Static
from textual.widgets.option_list import Option

from coc_bot.control import BotRunner, Mode, Paths, State
from coc_bot.logs import FORMAT, setup_logging
from coc_bot.tui.pages import (
    BotPage, CalibrationPage, HomePage, LogPage, ModePage, Page, SettingsPage, StatsPage, VisionPage,
    state_text,
)

PAGES: tuple[tuple[str, str, str, type[Page]], ...] = (   # id, key, label, class
    ("home", "1", "Beranda", HomePage),
    ("bot", "2", "Bot", BotPage),
    ("mode", "3", "Mode", ModePage),
    ("calibration", "4", "Kalibrasi", CalibrationPage),
    ("settings", "5", "Pengaturan", SettingsPage),
    ("logs", "6", "Log", LogPage),
    ("stats", "7", "Statistik", StatsPage),
    ("vision", "8", "Tes vision", VisionPage),
)

THEME = Theme(
    name="bot-farm",
    primary="#ffc83d",      # gold
    secondary="#e05ce6",    # elixir
    accent="#9a7bd6",       # dark elixir
    foreground="#e6e1f0",
    background="#14111c",
    surface="#1c1827",
    panel="#262033",
    success="#7ed491",
    warning="#ffb454",
    error="#ff6b81",
    dark=True,
)


class QueueHandler(logging.Handler):
    """Collects formatted log lines from any thread; the UI drains them on a timer."""

    def __init__(self, lines: deque[str]) -> None:
        super().__init__()
        self.lines = lines
        self.setFormatter(logging.Formatter(FORMAT, "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.lines.append(self.format(record))
        except Exception:  # noqa: BLE001
            self.handleError(record)


class DashboardApp(App):
    TITLE = "Bot Farm COC"
    CSS_PATH = "dashboard.tcss"
    BINDINGS = [
        *[Binding(key, f"page('{pid}')", label, show=False) for pid, key, label, _cls in PAGES],
        Binding("s", "toggle_run", "Start/Stop"),
        Binding("p", "pause", "Jeda/Lanjut"),
        Binding("c", "toggle_storage", "Cek storage"),
        Binding("r", "refresh", "Segarkan"),
        Binding("q", "quit", "Keluar"),
    ]

    def __init__(self, paths: Paths | None = None, runner: BotRunner | None = None,
                 probe_emulator: bool = True) -> None:
        super().__init__()
        self.probe_emulator = probe_emulator   # False in tests: don't touch ADB
        self.paths = paths or Paths()
        self.runner = runner or BotRunner(self.paths)
        self.mode = self.runner.mode
        self._log_lines: deque[str] = deque(maxlen=5000)
        self._log_handler = QueueHandler(self._log_lines)
        self._quitting = False

    # --- layout -------------------------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Static(id="statusbar")
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Static(Text.assemble(("⚔ ", "#e05ce6"), ("BOT FARM", "bold #ffc83d")), id="brand")
                yield OptionList(
                    *[Option(Text.assemble((f" {key} ", "bold #ffc83d"), label), id=pid)
                      for pid, key, label, _cls in PAGES],
                    id="nav",
                )
                yield Static(id="sidebar-mode")
            with ContentSwitcher(initial="home", id="pages"):
                for pid, _key, _label, cls in PAGES:
                    yield cls(id=pid)
        yield Footer()

    def on_mount(self) -> None:
        self.register_theme(THEME)
        self.theme = "bot-farm"
        logging.getLogger().addHandler(self._log_handler)
        self.set_interval(0.25, self._drain_logs)
        self.set_interval(0.5, self._tick)
        self._tick()
        self.query_one(HomePage).refresh_page()
        self.query_one("#nav", OptionList).highlighted = 0

    def on_unmount(self) -> None:
        logging.getLogger().removeHandler(self._log_handler)

    # --- navigation ---------------------------------------------------------------------------------
    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_list.id == "nav" and event.option.id:
            self._show_page(event.option.id)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id == "nav":
            self.query_one(f"#{event.option.id}", Page).focus()
            self.screen.focus_next()

    def action_page(self, page_id: str) -> None:
        index = [pid for pid, *_ in PAGES].index(page_id)
        self.query_one("#nav", OptionList).highlighted = index
        self._show_page(page_id)

    def _show_page(self, page_id: str) -> None:
        switcher = self.query_one("#pages", ContentSwitcher)
        if switcher.current != page_id:
            switcher.current = page_id
            self.query_one(f"#{page_id}", Page).refresh_page()

    def action_refresh(self) -> None:
        current = self.query_one("#pages", ContentSwitcher).current
        if current:
            self.query_one(f"#{current}", Page).refresh_page()
            self.notify("Disegarkan", timeout=1.5)

    # --- bot control --------------------------------------------------------------------------------
    def set_mode(self, mode: Mode) -> None:
        self.mode = mode
        self.runner.mode = mode
        self._tick()

    def set_check_storage(self, on: bool) -> None:
        self.runner.set_check_storage(on)
        self.notify("Cek storage penuh ON" if on else
                    "Cek storage penuh OFF: bot tetap menyerang walau storage penuh",
                    severity="information" if on else "warning")
        self._tick()

    def action_toggle_storage(self) -> None:
        self.set_check_storage(not self.runner.check_storage)

    def action_start(self) -> None:
        if self.runner.start(self.mode):
            self.notify(f"Bot dimulai (mode {self.mode.value})")
            self.action_page("bot")
        else:
            self.notify("Bot sudah berjalan", severity="warning")

    def action_stop(self) -> None:
        if self.runner.active:
            self.runner.stop()
            self.notify("Menghentikan bot setelah aksi saat ini…")

    def action_toggle_run(self) -> None:
        if self.runner.active:
            self.action_stop()
        else:
            self.action_start()

    def action_pause(self) -> None:
        state = self.runner.status().state
        if state is State.RUNNING:
            self.runner.pause()
        elif state is State.PAUSED:
            self.runner.resume()
        self._tick()

    async def action_quit(self) -> None:
        if not self.runner.active:
            self.exit()
            return
        if not self._quitting:
            self._quitting = True
            self.notify("Menghentikan bot lalu keluar…")
            self.runner.stop()
            self._wait_and_exit()

    @work(thread=True)
    def _wait_and_exit(self) -> None:
        self.runner.join(timeout=20)
        self.call_from_thread(self.exit)

    # --- timers ---------------------------------------------------------------------------------------
    def _drain_logs(self) -> None:
        if not self._log_lines:
            return
        page = self.query_one(BotPage)
        while self._log_lines:
            page.write_log(self._log_lines.popleft())

    def _tick(self) -> None:
        status = self.runner.status()
        bar = Text.assemble(" ", state_text(status.state), ("  │  ", "dim"), ("mode ", "dim"),
                            (status.mode.value, "bold"))
        if status.screen:
            bar.append_text(Text.assemble(("  │  ", "dim"), ("layar ", "dim"), (status.screen, "bold")))
        if self.runner.active:
            bar.append_text(Text.assemble(("  │  ", "dim"), ("serangan ", "dim"),
                                          (str(status.stats.attacks), "bold #ffc83d")))
            if status.started_at:
                bar.append_text(Text.assemble(("  │  ", "dim"), ("durasi ", "dim"),
                                              str(datetime.now() - status.started_at).split(".")[0]))
        if not self.runner.check_storage:
            bar.append_text(Text.assemble(("  │  ", "dim"), ("cek storage OFF", "bold yellow")))
        if status.error and status.state is State.ERROR:
            bar.append_text(Text.assemble(("  │  ", "dim"), (status.error[:80], "red")))
        self.query_one("#statusbar", Static).update(bar)
        self.query_one("#sidebar-mode", Static).update(Text.assemble(
            ("mode  ", "dim"), (self.mode.value, "bold #e05ce6"), "\n", state_text(status.state)))
        self.query_one(BotPage).update_status()


def run_dashboard(paths: Paths | None = None) -> int:
    paths = paths or Paths()
    setup_logging(paths.logs, console=False)   # the dashboard owns the terminal
    DashboardApp(paths).run()
    return 0
