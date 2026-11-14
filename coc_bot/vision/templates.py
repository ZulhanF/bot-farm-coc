"""Grayscale template matching restricted to each template's calibrated box (+ margin)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from coc_bot.config import Box


@dataclass(frozen=True)
class Match:
    name: str
    x: int
    y: int
    w: int
    h: int
    score: float

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)


class TemplateLibrary:
    def __init__(
        self,
        templates: dict[str, np.ndarray],
        boxes: dict[str, Box],
        threshold: float = 0.85,
        margin: int = 40,
    ) -> None:
        self._templates = templates
        self._boxes = boxes
        self._threshold = threshold
        self._margin = margin

    @classmethod
    def load(cls, directory: Path, boxes: dict[str, Box], threshold: float, margin: int) -> TemplateLibrary:
        templates: dict[str, np.ndarray] = {}
        if directory.is_dir():
            for path in sorted(directory.glob("*.png")):
                image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
                if image is None:
                    raise ValueError(f"Cannot read template {path}")
                templates[path.stem] = image
        return cls(templates, boxes, threshold, margin)

    def names(self) -> list[str]:
        return sorted(self._templates)

    def find(self, image: np.ndarray, name: str, threshold: float | None = None,
             anywhere: bool = False, scales: tuple[float, ...] = (1.0,)) -> Match | None:
        """Best match of `name`, searched in its calibrated box (+ margin) unless `anywhere` is set
        (for things that move with the camera, like the boat). `scales` also tries the template
        resized, for map objects whose size follows the camera zoom."""
        template = self._templates.get(name)
        if template is None:
            return None
        if float(template.std()) == 0.0:
            # TM_CCOEFF_NORMED is degenerate for a zero-variance template: it scores 1.0 (or NaN)
            # everywhere, so minMaxLoc would report the region origin as a perfect match.
            return None
        gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        region, ox, oy = gray, 0, 0
        box = None if anywhere else self._boxes.get(name)
        if box is not None:
            x, y, w, h = box
            m = self._margin
            x0, y0 = max(0, x - m), max(0, y - m)
            x1, y1 = min(gray.shape[1], x + w + m), min(gray.shape[0], y + h + m)
            region, ox, oy = gray[y0:y1, x0:x1], x0, y0
        best: Match | None = None
        for scale in scales:
            scaled = template if scale == 1.0 else cv2.resize(
                template, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)
            th, tw = scaled.shape[:2]
            if region.shape[0] < th or region.shape[1] < tw:
                continue
            result = cv2.matchTemplate(region, scaled, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if math.isfinite(max_val) and (best is None or max_val > best.score):
                best = Match(name, ox + max_loc[0], oy + max_loc[1], tw, th, float(max_val))
        limit = self._threshold if threshold is None else threshold
        if best is None or best.score < limit:
            return None
        return best
