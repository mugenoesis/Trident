"""Measuring the layers of an SL1 archive: the same answer however many workers do it, and the right one."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from app import layer_preview

WIDTH, HEIGHT = 80, 50
SCREEN_MM = (160.0, 100.0)  # 2 mm per pixel each way: one pixel is 4 mm2
# white pixels per layer; the largest (60) comes twice, and the first of them must win
WHITE = [0, 10, 60, 25, 60, 5, 40, 33, 12, 7, 50, 1]


def _png(white: int) -> bytes:
    image = Image.new("L", (WIDTH, HEIGHT), 0)
    image.putdata([255 if i < white else 0 for i in range(WIDTH * HEIGHT)])
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture()
def archive(tmp_path: Path) -> Path:
    path = tmp_path / "plate_1.sl1"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("config.ini", "action = print\n")
        for i, white in enumerate(WHITE):
            z.writestr(f"layer{i:05d}.png", _png(white))
    return path


def test_the_count_the_largest_layer_and_its_area(archive):
    count, peak_layer, peak_cm2 = layer_preview.measure(archive, SCREEN_MM)
    assert count == len(WHITE)
    assert peak_layer == 2  # the first of the two largest
    assert peak_cm2 == pytest.approx(60 * 4 / 100)


@pytest.mark.parametrize("workers", [1, 2, 3, 8, 64])
def test_any_number_of_workers_gives_the_same_answer(archive, workers):
    assert layer_preview.measure(archive, SCREEN_MM, workers=workers) == layer_preview.measure(
        archive, SCREEN_MM, workers=1
    )


def test_an_archive_with_no_layers_has_none(tmp_path):
    path = tmp_path / "empty.sl1"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("config.ini", "action = print\n")
    assert layer_preview.measure(path, SCREEN_MM) == (0, 0, 0.0)
