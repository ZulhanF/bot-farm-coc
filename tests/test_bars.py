import cv2
import numpy as np
import pytest

from coc_bot.vision.bars import BAR_HUES, bar_fill

ROI = (100, 20, 200, 24)  # x, y, w, h of the bar's fill area


def bar_image(fill: float, hue, text=True, seed=0):
    """Dark noisy background, bar filled from the right, white digits drawn over the right half."""
    rng = np.random.default_rng(seed)
    hsv = np.zeros((80, 400, 3), np.uint8)
    hsv[..., 0] = rng.integers(95, 125, hsv.shape[:2])   # bluish scenery behind the empty part
    hsv[..., 1] = rng.integers(20, 120, hsv.shape[:2])
    hsv[..., 2] = rng.integers(30, 160, hsv.shape[:2])
    x, y, w, h = ROI
    filled = int(round(w * fill))
    hsv[y:y + h // 2, x + w - filled:x + w] = (hue, 140, 240)       # light top band
    hsv[y + h // 2:y + h, x + w - filled:x + w] = (hue, 220, 200)   # deep bottom band
    img = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    if text:
        cv2.putText(img, "18 817 846", (x + 70, y + 19), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    return img


@pytest.mark.parametrize("resource", ["gold", "elixir", "de"])
@pytest.mark.parametrize("fill", [0.0, 0.3, 0.6, 0.9, 1.0])
def test_measures_fill_from_the_right(resource, fill):
    img = bar_image(fill, BAR_HUES[resource])
    assert bar_fill(img, ROI, BAR_HUES[resource]) == pytest.approx(fill, abs=0.04)


def test_full_bar_with_text_reads_full():
    img = bar_image(1.0, BAR_HUES["gold"])
    assert bar_fill(img, ROI, BAR_HUES["gold"]) >= 0.97


def test_other_resource_colour_does_not_count():
    img = bar_image(1.0, BAR_HUES["elixir"])
    assert bar_fill(img, ROI, BAR_HUES["gold"]) < 0.05


def test_stray_matching_pixels_left_of_the_fill_are_ignored():
    img = bar_image(0.5, BAR_HUES["gold"])
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    x, y, w, h = ROI
    hsv[y:y + h, x + 10:x + 13] = (BAR_HUES["gold"], 200, 200)   # 3px sliver far left
    img = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    assert bar_fill(img, ROI, BAR_HUES["gold"]) == pytest.approx(0.5, abs=0.04)


def test_roi_outside_image_reads_none():
    img = bar_image(1.0, BAR_HUES["gold"])
    assert bar_fill(img, (2000, 2000, 50, 10), BAR_HUES["gold"]) is None


def test_real_storage_bars():
    """Crop of a real home screen: gold 18 817 846 (~90 %), elixir 10 554 998 (~49 %), DE full."""
    from pathlib import Path
    img = cv2.imread(str(Path(__file__).parent / "fixtures" / "storage_bars_gold90_elixir49_defull.png"))
    ox, oy = 990, 20   # crop origin in the 1280x720 screenshot
    gold = bar_fill(img, (1002 - ox, 30 - oy, 228, 20), BAR_HUES["gold"])
    elixir = bar_fill(img, (1002 - ox, 78 - oy, 228, 20), BAR_HUES["elixir"])
    de = bar_fill(img, (1068 - ox, 126 - oy, 162, 18), BAR_HUES["de"])
    assert gold == pytest.approx(0.90, abs=0.05)
    assert elixir == pytest.approx(0.49, abs=0.05)
    assert de >= 0.95
