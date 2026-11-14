import cv2
import numpy as np

from coc_bot.vision.cards import ability_ready, charge_wash

CARD = (128, 625)   # bb_slot point of the hero card


def screen_with_card(hsv_colour, washed_rows=0):
    hsv = np.zeros((720, 1280, 3), np.uint8)
    hsv[...] = (0, 0, 40)
    x, y = CARD
    hsv[y - 25:y + 75, x - 38:x + 42] = hsv_colour
    if washed_rows:
        hsv[y - 25:y - 25 + washed_rows, x - 38:x + 42] = (0, 20, 230)   # pale, bright overlay
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)


def test_full_colour_card_is_ready():
    img = screen_with_card((135, 200, 200))
    assert charge_wash(img, CARD) < 0.05
    assert ability_ready(img, CARD)


def test_pale_card_is_still_charging():
    img = screen_with_card((135, 200, 200), washed_rows=80)
    assert charge_wash(img, CARD) > 0.7
    assert not ability_ready(img, CARD)


def test_almost_charged_card_is_ready():
    assert ability_ready(screen_with_card((135, 200, 200), washed_rows=18), CARD)
