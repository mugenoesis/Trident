"""Finding a cup in the layers of an SL1 archive: the same answer however many workers read it, and the right one."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from app import layer_preview

WIDTH, HEIGHT = 400, 300
SCREEN_MM = (80.0, 60.0)  # 0.2 mm per pixel: 5 pixels to the mm


def _png(hole: int) -> bytes:
    """A solid layer with a closed square hole of `hole` pixels in the middle (none when 0)."""
    image = Image.new("L", (WIDTH, HEIGHT), 255)
    if hole:
        x, y = (WIDTH - hole) // 2, (HEIGHT - hole) // 2
        image.paste(0, (x, y, x + hole, y + hole))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _archive(tmp_path: Path, holes: list[int]) -> Path:
    path = tmp_path / "plate_1.sl1"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("config.ini", "action = print\n")
        for i, hole in enumerate(holes):
            z.writestr(f"layer{i:05d}.png", _png(hole))
    return path


def test_a_closed_cavity_is_found_with_its_layer_and_area(tmp_path):
    archive = _archive(tmp_path, [0, 0, 100, 150, 100])  # 20 mm and 30 mm across: 400 mm2 and 900 mm2
    cup = layer_preview.find_cup(archive, SCREEN_MM)
    assert cup is not None
    assert cup.layer == 3
    assert cup.area_mm2 == pytest.approx(900, rel=0.05)


def test_a_part_with_no_cavity_has_no_cup(tmp_path):
    assert layer_preview.find_cup(_archive(tmp_path, [0, 0, 0]), SCREEN_MM) is None


def test_a_cavity_under_the_minimum_is_not_a_cup(tmp_path):
    assert layer_preview.find_cup(_archive(tmp_path, [0, 10, 10]), SCREEN_MM) is None  # 2 mm across: 4 mm2


@pytest.mark.parametrize("workers", [1, 3, 8])
def test_any_number_of_workers_gives_the_same_answer(tmp_path, workers):
    archive = _archive(tmp_path, [0, 0, 100, 150, 100, 0, 120])
    assert layer_preview.find_cup(archive, SCREEN_MM, workers=workers) == layer_preview.find_cup(
        archive, SCREEN_MM, workers=1
    )


def test_an_archive_with_no_layers_has_no_cup(tmp_path):
    path = tmp_path / "empty.sl1"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("config.ini", "action = print\n")
    assert layer_preview.find_cup(path, SCREEN_MM) is None
