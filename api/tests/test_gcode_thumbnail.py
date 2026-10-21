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


# ---- the sliced 3MF a Bambu printer is sent: its cover picture, as Bambu Studio's own export lays it out ----

import zipfile  # noqa: E402


def _sliced_3mf(path: Path, plates=(1,)) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<Types xmlns="x"><Default Extension="rels" ContentType="r"/></Types>')
        z.writestr(
            "_rels/.rels",
            '<?xml version="1.0"?>\n<Relationships xmlns="r">\n <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="m"/>\n</Relationships>',
        )
        for n in plates:
            z.writestr(f"Metadata/plate_{n}.gcode", "G28\n")
    return path


def test_the_preview_becomes_the_sliced_3mfs_cover_picture(tmp_path: Path):
    three_mf = _sliced_3mf(tmp_path / "sliced.gcode.3mf")
    gcode_thumbnail.embed_preview(tmp_path, _fake_preview_base64())
    with zipfile.ZipFile(three_mf) as z:
        big = Image.open(io.BytesIO(z.read("Metadata/plate_1.png")))
        small = Image.open(io.BytesIO(z.read("Metadata/plate_1_small.png")))
        rels = z.read("_rels/.rels").decode()
        types = z.read("[Content_Types].xml").decode()
        assert z.read("Metadata/plate_1.gcode") == b"G28\n"
    assert big.size == (512, 512) and small.size == (128, 128)
    assert 'Target="/Metadata/plate_1.png" Id="rel-2"' in rels and "metadata/thumbnail" in rels
    assert "cover-thumbnail-middle" in rels and 'Target="/Metadata/plate_1_small.png" Id="rel-5"' in rels
    assert "/3D/3dmodel.model" in rels
    assert 'Extension="png"' in types


def test_every_plate_of_the_3mf_gets_its_own_picture(tmp_path: Path):
    three_mf = _sliced_3mf(tmp_path / "sliced.gcode.3mf", plates=(1, 2))
    gcode_thumbnail.embed_preview(tmp_path, _fake_preview_base64())
    with zipfile.ZipFile(three_mf) as z:
        names = set(z.namelist())
    assert {"Metadata/plate_1.png", "Metadata/plate_2.png", "Metadata/plate_2_small.png"} <= names


def test_a_3mf_that_already_has_a_cover_picture_is_left_alone(tmp_path: Path):
    three_mf = _sliced_3mf(tmp_path / "sliced.gcode.3mf")
    gcode_thumbnail.embed_preview(tmp_path, _fake_preview_base64())
    first = three_mf.read_bytes()
    gcode_thumbnail.embed_preview(tmp_path, _fake_preview_base64(color="#0000ff"))
    assert three_mf.read_bytes() == first


def test_a_broken_3mf_does_not_fail_the_slice(tmp_path: Path):
    (tmp_path / "sliced.gcode.3mf").write_bytes(b"not a zip")
    gcode_thumbnail.embed_preview(tmp_path, _fake_preview_base64())
    assert (tmp_path / "sliced.gcode.3mf").read_bytes() == b"not a zip"
