import numpy as np
import pytest

from coc_bot.vision.screens import Screen, detect_screen
from tests.fakes import FakeTemplates

IMG = np.zeros((720, 1280, 3), np.uint8)


@pytest.mark.parametrize(
    "visible, expected",
    [
        ({"home_attack"}, Screen.HOME),
        ({"btn_find_match"}, Screen.ATTACK_MENU),
        ({"searching"}, Screen.SEARCHING),
        ({"btn_next", "btn_end_battle"}, Screen.BASE_PREVIEW),
        ({"btn_end_battle"}, Screen.BATTLE),
        ({"btn_surrender"}, Screen.BATTLE),
        ({"btn_return_home"}, Screen.RESULT),
        ({"popup_reload", "home_attack"}, Screen.POPUP),
        ({"popup_okay", "btn_end_battle"}, Screen.POPUP),
        (set(), Screen.UNKNOWN),
    ],
)
def test_detect_screen(visible, expected):
    assert detect_screen(IMG, FakeTemplates(visible)) is expected
