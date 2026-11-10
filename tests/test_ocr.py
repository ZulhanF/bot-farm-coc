import numpy as np

from coc_bot.vision.ocr import OcrReader, parse_number

IMG = np.zeros((720, 1280, 3), np.uint8)
ROI = (10, 10, 100, 20)


class FakeEngine:
    def __init__(self, results):
        self.results = results
        self.seen = []

    def __call__(self, image):
        self.seen.append(image)
        return self.results


def test_parse_number_ignores_separators():
    assert parse_number(["512 340"]) == 512340
    assert parse_number(["1,234,567"]) == 1234567
    assert parse_number([]) is None
    assert parse_number(["abc"]) is None


def test_parse_number_maps_common_confusions():
    assert parse_number(["1O5 l2"]) == 10512


def test_reads_number():
    assert OcrReader(FakeEngine([("512 340", 0.9)])).read_number(IMG, ROI, 5_000_000) == 512340


def test_joins_multiple_boxes_in_order():
    reader = OcrReader(FakeEngine([("1", 0.9), ("234 567", 0.95)]))
    assert reader.read_number(IMG, ROI, 5_000_000) == 1234567


def test_low_confidence_ignored():
    assert OcrReader(FakeEngine([("999", 0.2)])).read_number(IMG, ROI, 5_000_000) is None


def test_above_max_rejected():
    assert OcrReader(FakeEngine([("6000000", 0.9)])).read_number(IMG, ROI, 5_000_000) is None


def test_engine_receives_upscaled_bgr_crop():
    engine = FakeEngine([("1", 0.9)])
    OcrReader(engine).read_number(IMG, ROI, 10)
    assert engine.seen[0].shape == (60, 300, 3)


def test_roi_outside_image_returns_none():
    engine = FakeEngine([("1", 0.9)])
    assert OcrReader(engine).read_number(IMG, (2000, 2000, 10, 10), 10) is None
    assert engine.seen == []
