import base64
import io
from pathlib import Path

from PIL import Image

from app import gcode_thumbnail


def _fake_preview_base64(size: tuple[int, int] = (64, 40), color: str = "#ff8800") -> str:
    """A tiny, non-square (matches a real viewer canvas's aspect ratio)
    in-memory PNG, base64-encoded exactly the way App.tsx's handleSlice
    sends it (no "data:" prefix)."""
    image = Image.new("RGBA", size, color)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def test_embed_preview_prepends_thumbnail_block(tmp_path: Path):
    gcode_path = tmp_path / "plate_1.gcode"
    gcode_path.write_text("; original gcode content\nG28\n")

    gcode_thumbnail.embed_preview(tmp_path, _fake_preview_base64())

    content = gcode_path.read_text()
    assert content.startswith("; THUMBNAIL_BLOCK_START\n")
    assert "; thumbnail begin 48x48 " in content
    assert "; thumbnail begin 300x300 " in content
    assert content.count("; thumbnail end") == 2
    assert "; THUMBNAIL_BLOCK_END" in content
    # Original content preserved, just pushed after the new block.
    assert content.endswith("; original gcode content\nG28\n")


def test_embed_preview_covers_every_gcode_file_in_the_output_dir(tmp_path: Path):
    (tmp_path / "plate_1.gcode").write_text("plate one\n")
    (tmp_path / "plate_2.gcode").write_text("plate two\n")

    gcode_thumbnail.embed_preview(tmp_path, _fake_preview_base64())

    assert (tmp_path / "plate_1.gcode").read_text().endswith("plate one\n")
    assert (tmp_path / "plate_2.gcode").read_text().endswith("plate two\n")


def test_embed_preview_decodes_a_data_url_prefixed_payload(tmp_path: Path):
    gcode_path = tmp_path / "plate_1.gcode"
    gcode_path.write_text("G28\n")

    gcode_thumbnail.embed_preview(tmp_path, f"data:image/png;base64,{_fake_preview_base64()}")

    assert "; THUMBNAIL_BLOCK_START" in gcode_path.read_text()


def test_embed_preview_is_a_noop_on_invalid_base64(tmp_path: Path):
    gcode_path = tmp_path / "plate_1.gcode"
    gcode_path.write_text("G28\n")

    gcode_thumbnail.embed_preview(tmp_path, "not valid base64!!!")

    assert gcode_path.read_text() == "G28\n"


def test_embed_preview_is_a_noop_on_valid_base64_that_is_not_a_png(tmp_path: Path):
    gcode_path = tmp_path / "plate_1.gcode"
    gcode_path.write_text("G28\n")

    gcode_thumbnail.embed_preview(tmp_path, base64.b64encode(b"not a png").decode("ascii"))

    assert gcode_path.read_text() == "G28\n"


def test_embed_preview_ignores_missing_output_dir(tmp_path: Path):
    # Never raises, even if the job's output dir vanished/was never created
    # -- best-effort, shouldn't affect the already-succeeded slice result.
    gcode_thumbnail.embed_preview(tmp_path / "does-not-exist", _fake_preview_base64())
