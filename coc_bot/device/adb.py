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
        if not data:
            raise AdbError("screencap returned no data")
        try:
            image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        except cv2.error as exc:
            raise AdbError(f"screencap could not be decoded: {exc}") from exc
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
