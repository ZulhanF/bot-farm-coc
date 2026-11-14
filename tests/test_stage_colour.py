import cv2
import numpy as np

from coc_bot.vision.stage import is_stage2_map, map_colours


def hsv_image(hue, sat=150, val=110):
    hsv = np.zeros((720, 1280, 3), np.uint8)
    hsv[...] = (hue, sat, val)
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)


def test_green_battlefield_is_stage1():
    img = hsv_image(65)
    green, blue = map_colours(img)
    assert green > 0.9 and blue < 0.1
    assert not is_stage2_map(img)


def test_dark_blue_battlefield_is_stage2():
    assert is_stage2_map(hsv_image(110))


def test_black_screen_is_not_stage2():
    assert not is_stage2_map(np.zeros((720, 1280, 3), np.uint8))


def test_mostly_green_with_some_blue_is_stage1():
    img = hsv_image(65)
    img[100:250, :] = hsv_image(110)[100:250, :]   # a blue strip (water, UI) over part of the map
    assert not is_stage2_map(img)
