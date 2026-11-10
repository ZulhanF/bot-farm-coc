"""Deploy points spread along the edges of the (zoomed-out) map diamond."""
from __future__ import annotations

import math
import random
from typing import Sequence

from coc_bot.config import Point


def edge_points(
    corners: Sequence[Point],
    sides: int,
    per_side: int,
    outward_px: int,
    jitter_px: int,
    rng: random.Random,
    size: tuple[int, int],
    max_y: int,
    pattern: str = "all",
) -> list[Point]:
    if not 1 <= sides <= 4:
        raise ValueError(f"sides must be 1..4, got {sides}")
    if len(corners) != 4:
        raise ValueError("corners must be (top, right, bottom, left)")
    width, height = size
    cx = sum(p[0] for p in corners) / 4
    cy = sum(p[1] for p in corners) / 4
    if pattern == "v_top":
        edges = [(corners[0], corners[3]), (corners[0], corners[1])]
    elif pattern == "v_bottom":
        edges = [(corners[2], corners[3]), (corners[2], corners[1])]
    else:
        edges = [(corners[i], corners[(i + 1) % 4]) for i in range(4)][:sides]
    result: list[Point] = []
    for (ax, ay), (bx, by) in edges:
        for k in range(per_side):
            t = 0.5 if per_side == 1 else 0.15 + 0.7 * k / (per_side - 1)
            x = ax + (bx - ax) * t
            y = ay + (by - ay) * t
            dx, dy = x - cx, y - cy
            norm = math.hypot(dx, dy) or 1.0
            x += dx / norm * outward_px + rng.uniform(-jitter_px, jitter_px)
            y += dy / norm * outward_px + rng.uniform(-jitter_px, jitter_px)
            px = min(max(int(round(x)), 0), width - 1)
            py = min(max(int(round(y)), 0), min(height - 1, max_y))
            result.append((px, py))
    return result


def line_points(
    start: Point,
    end: Point,
    count: int,
    jitter_px: int,
    rng: random.Random,
    size: tuple[int, int] = (1280, 720),
    max_y: int = 600,
) -> list[Point]:
    if count <= 0:
        return []
    width, height = size
    if count == 1:
        x = (start[0] + end[0]) // 2 + rng.randint(-jitter_px, jitter_px)
        y = (start[1] + end[1]) // 2 + rng.randint(-jitter_px, jitter_px)
        return [(min(max(x, 0), width - 1), min(max(y, 0), min(height - 1, max_y)))]
    res: list[Point] = []
    for k in range(count):
        t = k / (count - 1)
        x = int(round(start[0] + t * (end[0] - start[0]))) + rng.randint(-jitter_px, jitter_px)
        y = int(round(start[1] + t * (end[1] - start[1]))) + rng.randint(-jitter_px, jitter_px)
        px = min(max(x, 0), width - 1)
        py = min(max(y, 0), min(height - 1, max_y))
        res.append((px, py))
    return res
