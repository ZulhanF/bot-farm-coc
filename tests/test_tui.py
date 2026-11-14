import asyncio

from textual.widgets import ContentSwitcher

from coc_bot.control import Mode, Paths, State
from coc_bot.tui.app import PAGES, DashboardApp
from coc_bot.tui.pages import validate_settings_text


def make_app(tmp_path):
    paths = Paths(tmp_path / "settings.toml", tmp_path / "calibration.toml",
                  tmp_path / "templates", tmp_path / "logs")
    return DashboardApp(paths, probe_emulator=False)


def test_every_page_opens(tmp_path):
    async def go():
        app = make_app(tmp_path)
        async with app.run_test(size=(130, 40)) as pilot:
            for pid, key, _label, _cls in PAGES:
                await pilot.press(key)
                await pilot.pause()
                assert app.query_one("#pages", ContentSwitcher).current == pid
    asyncio.run(go())


def test_start_with_incomplete_calibration_shows_error(tmp_path):
    async def go():
        app = make_app(tmp_path)
        async with app.run_test(size=(130, 40)) as pilot:
            await pilot.press("s")
            app.runner.join(5)
            await pilot.pause(0.6)
            assert app.query_one("#pages", ContentSwitcher).current == "bot"
            assert app.runner.status().state is State.ERROR
    asyncio.run(go())


def test_storage_check_toggle(tmp_path):
    async def go():
        app = make_app(tmp_path)
        async with app.run_test(size=(130, 40)) as pilot:
            await pilot.press("2")
            await pilot.press("c")
            await pilot.pause(0.6)
            assert app.runner.check_storage is False
            assert app.query_one("#sw-storage").value is False
            await pilot.press("c")
            await pilot.pause(0.6)
            assert app.runner.check_storage is True
    asyncio.run(go())


def test_calibration_page_shows_only_relevant_items(tmp_path):
    async def go():
        app = make_app(tmp_path)
        async with app.run_test(size=(130, 40)) as pilot:
            await pilot.press("4")
            await pilot.pause(0.3)
            table = app.query_one("#cal-table")
            relevant = table.row_count
            app.query_one("#calibration").action_toggle_all()
            await pilot.pause(0.3)
            assert table.row_count > relevant
    asyncio.run(go())


def test_validate_settings_text(tmp_path):
    cal = tmp_path / "calibration.toml"
    assert validate_settings_text("[loot]\nmin_gold = 1\n", cal) is None
    assert "Unknown key" in validate_settings_text("[loot]\nbogus = 1\n", cal)
    assert "TOML" in validate_settings_text("[loot\n", cal)


def test_mode_page_offers_builder_sub_modes(tmp_path):
    async def go():
        app = make_app(tmp_path)
        async with app.run_test(size=(130, 40)) as pilot:
            await pilot.press("3")
            await pilot.pause(0.3)
            mode_list = app.query_one("#mode-list")
            ids = [mode_list.get_option_at_index(i).id for i in range(mode_list.option_count)]
            assert "builder:elixir" in ids and "builder:gold" in ids
            app.set_mode(Mode.BUILDER, "gold")
            assert app.runner.mode is Mode.BUILDER and app.runner.builder_mode == "gold"
    asyncio.run(go())
