import math
import random

import pytest

from coc_bot.game.deploy import edge_points

CORNERS = [(640, 100), (1100, 360), (640, 620), (180, 360)]
CENTER = (640, 360)
SIZE = (1280, 720)


def pts(**kw):
    args = dict(corners=CORNERS, sides=4, per_side=5, outward_px=0, jitter_px=0,
                rng=random.Random(0), size=SIZE, max_y=720)
    args.update(kw)
    return edge_points(**args)


def test_count():
    assert len(pts()) == 20
    assert len(pts(sides=2)) == 10
    assert len(pts(pattern="v_top", per_side=5)) == 10


def test_single_point_is_edge_midpoint():
    assert pts(sides=1, per_side=1) == [(870, 230)]


def test_outward_moves_away_from_center():
    (x, y), = pts(sides=1, per_side=1, outward_px=10)
    before = math.dist((870, 230), CENTER)
    after = math.dist((x, y), CENTER)
    assert abs((after - before) - 10) <= 1


def test_points_clamped_to_screen_and_max_y():
    corners = [(640, 100), (1270, 360), (640, 700), (5, 360)]
    result = pts(corners=corners, outward_px=50, jitter_px=5, max_y=600)
    assert all(0 <= x < 1280 and 0 <= y <= 600 for x, y in result)


def test_jitter_is_bounded():
    a = pts(sides=1, per_side=3)
    b = pts(sides=1, per_side=3, jitter_px=4, rng=random.Random(1))
    assert all(abs(ax - bx) <= 4 and abs(ay - by) <= 4 for (ax, ay), (bx, by) in zip(a, b))


@pytest.mark.parametrize("sides", [0, 5])
def test_invalid_sides(sides):
    with pytest.raises(ValueError):
        pts(sides=sides)


def test_line_points():
    from coc_bot.game.deploy import line_points
    res = line_points((100, 100), (500, 500), 5, 0, random.Random(0))
    assert len(res) == 5
    assert res[0] == (100, 100)
    assert res[-1] == (500, 500)
    assert res[2] == (300, 300)
