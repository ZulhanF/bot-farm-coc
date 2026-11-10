from __future__ import annotations

import logging
from datetime import date
from pathlib import Path


def setup_logging(log_dir: Path, level: int = logging.INFO) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"bot-{date.today():%Y-%m-%d}.log"
    formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    for handler in (logging.FileHandler(path, encoding="utf-8"), logging.StreamHandler()):
        handler.setFormatter(formatter)
        root.addHandler(handler)
    return path
