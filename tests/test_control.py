import threading
import time

from coc_bot.control import BotRunner, Mode, Paths, State


def tmp_paths(tmp_path):
    return Paths(tmp_path / "settings.toml", tmp_path / "calibration.toml",
                 tmp_path / "templates", tmp_path / "logs")


def test_unavailable_mode_fails_without_touching_adb(tmp_path):
    runner = BotRunner(tmp_paths(tmp_path), Mode.WALLS)
    assert runner.run() == 2
    status = runner.status()
    assert status.state is State.ERROR
    assert "walls" in status.error


def test_incomplete_calibration_fails(tmp_path):
    runner = BotRunner(tmp_paths(tmp_path))
    assert runner.run() == 2
    assert runner.status().state is State.ERROR
    assert "template:home_attack" in runner.status().error


def test_background_start_reports_error_and_can_restart(tmp_path):
    runner = BotRunner(tmp_paths(tmp_path))
    assert runner.start()
    runner.join(5)
    assert not runner.active
    assert runner.status().state is State.ERROR
    assert runner.start()   # a finished runner can be started again
    runner.join(5)


def test_sleep_returns_at_once_on_stop(tmp_path):
    runner = BotRunner(tmp_paths(tmp_path))
    runner._state = State.RUNNING
    threading.Timer(0.1, runner.stop).start()
    t0 = time.monotonic()
    runner._sleep(30)
    assert time.monotonic() - t0 < 2


def test_sleep_blocks_while_paused(tmp_path):
    runner = BotRunner(tmp_paths(tmp_path))
    runner._state = State.RUNNING
    runner.pause()
    assert runner.status().state is State.PAUSED
    threading.Timer(0.6, runner.resume).start()
    t0 = time.monotonic()
    runner._sleep(0.05)
    assert time.monotonic() - t0 >= 0.5
    assert runner.status().state is State.RUNNING


def test_storage_check_switch_reaches_the_running_bot(tmp_path):
    class FakeBot:
        check_storage = True
    runner = BotRunner(tmp_paths(tmp_path))
    runner._bot = FakeBot()
    runner.set_check_storage(False)
    assert runner.check_storage is False and runner._bot.check_storage is False


def test_builder_mode_checks_builder_calibration(tmp_path):
    runner = BotRunner(tmp_paths(tmp_path), Mode.BUILDER)
    assert runner.run() == 2
    error = runner.status().error
    assert "template:bb_boat" in error and "template:btn_next" not in error


def test_builder_sub_mode_label(tmp_path):
    from coc_bot.control import mode_label
    runner = BotRunner(tmp_paths(tmp_path), Mode.BUILDER, builder_mode="gold")
    assert runner.status().builder_mode == "gold"
    assert mode_label(Mode.BUILDER, "gold") == "builder (gold)"
    assert mode_label(Mode.HOME, "gold") == "home"


def test_builder_mode_override_drives_calibration_check(tmp_path):
    (tmp_path / "settings.toml").write_text('[builder]\nmode = "elixir"\n', encoding="utf-8")
    runner = BotRunner(tmp_paths(tmp_path), Mode.BUILDER, builder_mode="gold")
    assert runner.run() == 2
    assert "template:bb_btn_end_battle" in runner.status().error
