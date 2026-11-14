"""Which Builder Base stage a battle is on, from the battlefield colour.

Stage 1 is a green field (31-68 % green pixels, under 10 % dark blue in the 2026-11-14 recordings),
stage 2 is a dark blue cave (0 % green, ~88 % dark blue). Only meaningful on prep / battle screens:
the Builder Base village itself is dark blue too.
"""
from __future__ import annotations

import cv2
import numpy as np

MAP_REGION = (200, 100, 880, 460)   # x, y, w, h: the battlefield between the side buttons and the cards
GREEN_HUES = (35, 85)                # OpenCV hue scale 0-179
BLUE_HUES = (95, 130)
MIN_SATURATION = 40
STAGE2_MIN_BLUE = 0.5
STAGE2_MAX_GREEN = 0.1


def map_colours(image: np.ndarray) -> tuple[float, float]:
    """(green share, dark-blue share) of the battlefield pixels."""
    x, y, w, h = MAP_REGION
    hsv = cv2.cvtColor(image[y:y + h, x:x + w], cv2.COLOR_BGR2HSV)
    hue, sat = hsv[..., 0], hsv[..., 1]
    green = (hue >= GREEN_HUES[0]) & (hue <= GREEN_HUES[1]) & (sat > 60)
    blue = (hue >= BLUE_HUES[0]) & (hue <= BLUE_HUES[1]) & (sat > MIN_SATURATION)
    return float(green.mean()), float(blue.mean())


def is_stage2_map(image: np.ndarray) -> bool:
    green, blue = map_colours(image)
    return blue >= STAGE2_MIN_BLUE and green < STAGE2_MAX_GREEN
