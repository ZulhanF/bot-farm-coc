"""Is a hero card's ability charged? While it charges the card is washed out (pale overlay sweeping
away like a clock hand); when charged it is in full colour.

Recorded on 2026-11-14 (Battle Copter card): pale share 0.79 right after use, 0.66, 0.36, then
0.18-0.20 once charged.
"""
from __future__ import annotations

import cv2
import numpy as np

from coc_bot.config import Point

CARD_BOX = (-38, -25, 80, 100)   # x, y offset from the card's bb_slot point, width, height
PALE_MAX_SATURATION = 60
PALE_MIN_VALUE = 170
READY_MAX_WASH = 0.22


def charge_wash(image: np.ndarray, card: Point) -> float:
    """Share of the card covered by the pale charging overlay (0 = full colour)."""
    dx, dy, w, h = CARD_BOX
    x, y = card[0] + dx, card[1] + dy
    crop = image[max(0, y):y + h, max(0, x):x + w]
    if crop.size == 0:
        return 0.0
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    pale = (hsv[..., 1] < PALE_MAX_SATURATION) & (hsv[..., 2] > PALE_MIN_VALUE)
    return float(pale.mean())


def ability_ready(image: np.ndarray, card: Point) -> bool:
    return charge_wash(image, card) < READY_MAX_WASH
