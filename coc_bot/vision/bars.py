"""How full a resource bar is, measured from its flat fill colour (no OCR, no capacity needed).

The home-village gold / elixir / dark elixir bars fill from the right (icon side) to the left with a
flat colour; the empty part shows the dimmed scenery behind it. The amount text is drawn over the
bar, so a column counts as "filled" when enough of its pixels have the bar colour, and the fill is the
contiguous run of filled columns ending at the right edge.
"""
from __future__ import annotations

import cv2
import numpy as np

from coc_bot.config import Box

# OpenCV hue (0-179) of each bar's fill, measured on 1280x720 LDPlayer screenshots. The fill has a light
# top band and a deeper bottom band, so saturation / brightness vary a lot while the hue stays put.
BAR_HUES: dict[str, int] = {"gold": 25, "elixir": 150, "de": 140}
_HUE_TOL = 3
_MIN_S, _MIN_V = 30, 35           # excludes the white digits (low S) and their black outline (low V)
_COLUMN_MIN = 0.6                 # share of nearby non-text pixels with the fill hue to count as filled
_RIGHT_SLACK = 0.15               # the run may start this far left of the ROI's right edge (icon overlap)


def bar_fill(image: np.ndarray, roi: Box, hue: int) -> float | None:
    """Fraction 0..1 of the bar that is filled, or None if the ROI is outside the image."""
    x, y, w, h = roi
    crop = image[max(y, 0):y + h, max(x, 0):x + w]
    if crop.size == 0 or crop.shape[1] < 4:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV).astype(np.int16)
    dh = np.abs(hsv[..., 0] - hue)
    dh = np.minimum(dh, 180 - dh)  # hue wraps around
    coloured = (hsv[..., 1] >= _MIN_S) & (hsv[..., 2] >= _MIN_V)   # not white digit / black outline
    match = coloured & (dh <= _HUE_TOL)

    # The digits can cover almost the whole height of a column, so ignore them: among the coloured
    # (non-text) pixels near each column, how many have the fill hue? The empty part of a bar shows
    # scenery in other hues, so it stays near 0.
    width = match.shape[1]
    k = max(3, int(round(width * 0.04)))
    window = np.ones(k)
    pad = (k // 2, k - 1 - k // 2)
    hits = np.convolve(np.pad(match.sum(axis=0).astype(float), pad, mode="edge"), window, mode="valid")
    seen = np.convolve(np.pad(coloured.sum(axis=0).astype(float), pad, mode="edge"), window, mode="valid")
    smooth = hits >= _COLUMN_MIN * np.maximum(seen, 1)

    right = width - 1
    lowest = int(width * (1 - _RIGHT_SLACK))
    while right >= lowest and not smooth[right]:
        right -= 1
    if right < lowest:
        return 0.0
    left = right
    while left > 0 and smooth[left - 1]:
        left -= 1
    return (right + 1 - left) / (right + 1)
