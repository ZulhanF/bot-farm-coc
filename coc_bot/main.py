"""Command-line entry point."""
from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from coc_bot import names as N
from coc_bot.config import Box, Settings, load_calibration, load_settings, save_calibration
from coc_bot.control import BotRunner, Mode, Paths, connect, load_templates
from coc_bot.device.adb import AdbError
from coc_bot.logs import setup_logging
from coc_bot.vision.report import analyse
from coc_bot.vision.templates import TemplateLibrary

log = logging.getLogger("coc_bot")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="coc_bot", description="Clash of Clans farming bot")
    parser.add_argument("--settings", type=Path, default=Path("settings.toml"))
    parser.add_argument("--calibration", type=Path, default=Path("calibration.toml"))
    parser.add_argument("--templates", type=Path, default=Path("assets/templates"))
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("dashboard", help="open the terminal dashboard (default without a command)")
    run = sub.add_parser("run", help="run the bot (Ctrl+C to stop)")
    run.add_argument("--mode", choices=[m.value for m in Mode], default=Mode.HOME.value)
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


def _paths(args: argparse.Namespace) -> Paths:
    return Paths(args.settings, args.calibration, args.templates)


def _templates(args: argparse.Namespace, settings: Settings) -> TemplateLibrary:
    return load_templates(_paths(args), settings)


def _connect(settings: Settings):
    return connect(settings)


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
    valid = N.valid_names(args.kind, N.used_slots(settings))
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
    report = analyse(image, settings, _templates(args, settings))
    print(f"Screen: {report.screen}")
    for t in report.templates:
        if t.score is None:
            print(f"  {t.name:<18} (does not fit)")
        else:
            print(f"  {t.name:<18} score={t.score:.3f} at {t.center} {'MATCH' if t.match else '-'}")
    for r in report.rois:
        if r.kind == "bar":
            print(f"  BAR {r.name:<8} = {'?' if r.value is None else f'{r.value:.0%} full'}")
        else:
            print(f"  OCR {r.name:<8} = {r.value}")
    return 0


def cmd_run(args: argparse.Namespace, settings: Settings) -> int:
    missing = N.missing_calibration(settings, set(_templates(args, settings).names()))
    if missing:
        print("Calibration incomplete, run `python -m coc_bot check`. Missing:", ", ".join(missing))
        return 2
    log_path = setup_logging(Path("logs"))
    log.info("Logging to %s", log_path)
    runner = BotRunner(_paths(args), Mode(getattr(args, "mode", Mode.HOME.value)))
    code = runner.run()
    if code == 3:
        raise AdbError(runner.status().error or "ADB error")
    return code


def cmd_dashboard(args: argparse.Namespace, settings: Settings) -> int:
    from coc_bot.tui.app import run_dashboard   # Textual is only needed for the dashboard
    return run_dashboard(_paths(args))


COMMANDS = {
    "dashboard": cmd_dashboard,
    "run": cmd_run,
    "check": cmd_check,
    "screenshot": cmd_screenshot,
    "test-vision": cmd_test_vision,
    "calibrate": cmd_calibrate,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command is None:
        args.command = "dashboard"
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
    except ValueError as exc:
        print(f"Error: {exc}")
        return 2
