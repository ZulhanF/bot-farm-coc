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


def test_screencap_empty_output_raises():
    adb, _ = make()
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
