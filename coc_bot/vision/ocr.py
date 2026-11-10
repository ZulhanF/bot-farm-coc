"""Read loot numbers from fixed screen regions."""
from __future__ import annotations

from typing import Callable

import cv2
import numpy as np

from coc_bot.config import Box

OcrEngine = Callable[[np.ndarray], list[tuple[str, float]]]

_CONFUSIONS = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1"})
_UPSCALE = 3


def parse_number(texts: list[str]) -> int | None:
    digits = "".join(ch for text in texts for ch in text.translate(_CONFUSIONS) if ch.isdigit())
    return int(digits) if digits else None


def _preprocess(crop: np.ndarray) -> np.ndarray:
    big = cv2.resize(crop, None, fx=_UPSCALE, fy=_UPSCALE, interpolation=cv2.INTER_CUBIC)
    gray = big if big.ndim == 2 else cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)


class OcrReader:
    def __init__(self, engine: OcrEngine, min_confidence: float = 0.5) -> None:
        self._engine = engine
        self._min_confidence = min_confidence

    def read_number(self, image: np.ndarray, roi: Box, max_value: int) -> int | None:
        x, y, w, h = roi
        crop = image[y:y + h, x:x + w]
        if crop.size == 0:
            return None
        texts = [text for text, conf in self._engine(_preprocess(crop)) if conf >= self._min_confidence]
        value = parse_number(texts)
        if value is None or value > max_value:
            return None
        return value


def rapidocr_engine() -> OcrEngine:
    from rapidocr_onnxruntime import RapidOCR  # heavy import, only when actually used

    engine = RapidOCR()

    def run(image: np.ndarray) -> list[tuple[str, float]]:
        result, _ = engine(image)
        if not result:
            return []
        return [(str(item[1]), float(item[2])) for item in result]

    return run
