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
