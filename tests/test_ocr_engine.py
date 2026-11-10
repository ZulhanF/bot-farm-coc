"""Real RapidOCR on a cropped base-preview loot panel (regression for split/merged digits)."""
from pathlib import Path

import cv2
import pytest

from coc_bot.vision.ocr import OcrReader, rapidocr_engine

FIXTURE = Path(__file__).parent / "fixtures" / "loot_preview_1354460_1029032.png"
# ROIs from calibration.toml, shifted by the fixture crop origin (x=50, y=80)
GOLD = (60 - 50, 87 - 80, 159, 31)
ELIXIR = (63 - 50, 126 - 80, 132, 28)


@pytest.fixture(scope="module")
def reader():
    return OcrReader(rapidocr_engine())


def test_reads_gold_with_spaces(reader):
    assert reader.read_number(cv2.imread(str(FIXTURE)), GOLD, 5_000_000) == 1_354_460


def test_reads_elixir_leading_digits(reader):
    assert reader.read_number(cv2.imread(str(FIXTURE)), ELIXIR, 5_000_000) == 1_029_032


def test_engine_error_returns_no_text(monkeypatch):
    import rapidocr_onnxruntime

    class Broken:
        def __call__(self, *args, **kwargs):
            raise RuntimeError("[ONNXRuntimeError] : 1 : FAIL : bad allocation")

    monkeypatch.setattr(rapidocr_onnxruntime, "RapidOCR", Broken)
    engine = rapidocr_engine()
    assert engine(cv2.imread(str(FIXTURE))) == []
