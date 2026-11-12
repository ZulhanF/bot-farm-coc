from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(log_dir: Path, level: int = logging.INFO, console: bool = True) -> Path:
    """Log to logs/bot-YYYY-MM-DD.log (and the console). Calling it again replaces our handlers."""
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"bot-{date.today():%Y-%m-%d}.log"
    formatter = logging.Formatter(FORMAT)
    root = logging.getLogger()
    root.setLevel(level)
    for old in [h for h in root.handlers if getattr(h, "_coc_bot", False)]:
        root.removeHandler(old)
        old.close()
    handlers: list[logging.Handler] = [logging.FileHandler(path, encoding="utf-8")]
    if console:
        handlers.append(logging.StreamHandler())
    for handler in handlers:
        handler.setFormatter(formatter)
        handler._coc_bot = True  # type: ignore[attr-defined]
        root.addHandler(handler)
    return path
