"""What the bot sees on one screenshot (screen, template scores, bars, OCR) - for `test-vision` and the TUI."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from coc_bot import names as N
from coc_bot.config import Settings
from coc_bot.vision.bars import BAR_HUES, bar_fill
from coc_bot.vision.screens import detect_screen
from coc_bot.vision.templates import TemplateLibrary


@dataclass(frozen=True)
class TemplateScore:
    name: str
    score: float | None   # None = the calibrated box does not fit the image
    center: tuple[int, int] | None
    match: bool


@dataclass(frozen=True)
class RoiReading:
    name: str
    kind: str             # "bar" (fraction 0..1) or "ocr" (number)
    value: float | int | None


@dataclass(frozen=True)
class VisionReport:
    screen: str
    templates: list[TemplateScore]
    rois: list[RoiReading]


def bar_levels(image: np.ndarray, settings: Settings) -> dict[str, float | None]:
    """Fill of every calibrated home resource bar, by resource."""
    rois = settings.calibration.rois
    return {res: bar_fill(image, rois[bar], BAR_HUES[res]) for res, bar in N.STORAGE_BARS if bar in rois}


def analyse(image: np.ndarray, settings: Settings, templates: TemplateLibrary, reader=None) -> VisionReport:
    """`reader` (an OcrReader) is created on demand: loading the OCR model takes a few seconds."""
    scores = []
    for name in templates.names():
        found = templates.find(image, name, threshold=-1.0)
        if found is None:
            scores.append(TemplateScore(name, None, None, False))
        else:
            scores.append(TemplateScore(name, found.score, found.center,
                                        found.score >= settings.vision.threshold))
    readings = []
    bars = {bar: res for res, bar in N.STORAGE_BARS}
    for name, roi in settings.calibration.rois.items():
        if name in bars:
            readings.append(RoiReading(name, "bar", bar_fill(image, roi, BAR_HUES[bars[name]])))
            continue
        if name not in N.ROI_LIMITS:
            continue   # not a ROI the bot reads (e.g. left over from an older version)
        if reader is None:
            from coc_bot.vision.ocr import OcrReader, rapidocr_engine
            reader = OcrReader(rapidocr_engine())
        readings.append(RoiReading(name, "ocr", reader.read_number(image, roi, N.ROI_LIMITS.get(name, N.MAX_GOLD))))
    return VisionReport(detect_screen(image, templates).name, scores, readings)
