import cv2
import numpy as np

from coc_bot.vision.templates import TemplateLibrary


def noise(seed):
    return np.random.default_rng(seed).integers(0, 256, (720, 1280, 3), dtype=np.uint8)


def save_template(directory, name, image, box):
    x, y, w, h = box
    cv2.imwrite(str(directory / f"{name}.png"), image[y:y + h, x:x + w])


def test_finds_template_inside_its_box(tmp_path):
    img = noise(0)
    box = (100, 200, 50, 40)
    save_template(tmp_path, "btn", img, box)
    lib = TemplateLibrary.load(tmp_path, {"btn": box}, threshold=0.85, margin=40)
    m = lib.find(img, "btn")
    assert m is not None
    assert (m.x, m.y, m.w, m.h) == (100, 200, 50, 40)
    assert m.center == (125, 220)
    assert m.score > 0.95


def test_finds_template_without_box_full_search(tmp_path):
    img = noise(1)
    save_template(tmp_path, "btn", img, (700, 500, 60, 30))
    lib = TemplateLibrary.load(tmp_path, {}, threshold=0.85, margin=40)
    m = lib.find(img, "btn")
    assert m is not None and (m.x, m.y) == (700, 500)


def test_box_limits_search_region(tmp_path):
    img = noise(2)
    save_template(tmp_path, "btn", img, (100, 200, 50, 40))
    lib = TemplateLibrary.load(tmp_path, {"btn": (900, 500, 50, 40)}, threshold=0.85, margin=40)
    assert lib.find(img, "btn") is None


def test_absent_template_returns_none(tmp_path):
    save_template(tmp_path, "btn", noise(3), (100, 200, 50, 40))
    lib = TemplateLibrary.load(tmp_path, {}, threshold=0.85, margin=40)
    assert lib.find(noise(4), "btn") is None


def test_threshold_override_returns_low_score_match(tmp_path):
    save_template(tmp_path, "btn", noise(3), (100, 200, 50, 40))
    lib = TemplateLibrary.load(tmp_path, {}, threshold=0.85, margin=40)
    m = lib.find(noise(4), "btn", threshold=-1.0)
    assert m is not None and m.score < 0.85


def test_unknown_name_returns_none(tmp_path):
    lib = TemplateLibrary.load(tmp_path, {}, threshold=0.85, margin=40)
    assert lib.find(noise(0), "nope") is None


def test_missing_directory_gives_empty_library(tmp_path):
    lib = TemplateLibrary.load(tmp_path / "nope", {}, threshold=0.85, margin=40)
    assert lib.names() == []


def test_uniform_template_never_matches(tmp_path):
    cv2.imwrite(str(tmp_path / "flat.png"), np.full((20, 20), 128, dtype=np.uint8))
    lib = TemplateLibrary.load(tmp_path, {}, threshold=0.85, margin=40)
    assert lib.names() == ["flat"]
    img = noise(0)
    assert lib.find(img, "flat") is None
    assert lib.find(img, "flat", threshold=-1.0) is None


def test_names_sorted(tmp_path):
    img = noise(0)
    save_template(tmp_path, "b", img, (0, 0, 10, 10))
    save_template(tmp_path, "a", img, (20, 20, 10, 10))
    lib = TemplateLibrary.load(tmp_path, {}, threshold=0.85, margin=40)
    assert lib.names() == ["a", "b"]
