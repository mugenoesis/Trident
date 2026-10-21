"""Embeds a client-captured 3D-preview PNG into sliced gcode as a standard
thumbnail comment block -- purely for printers/print-host UIs (Mainsail,
Fluidd, OctoPrint, a printer's own screen) that read it from the gcode file
itself; this app's own UI doesn't display a copy of it anywhere.

The comment-block format (`; THUMBNAIL_BLOCK_START` / `; thumbnail begin
WxH SIZE` / base64 body / `; thumbnail end`) matches exactly what OrcaSlicer's
own engine writes (vendor/orcaslicer/src/libslic3r/GCode/Thumbnails.hpp's
export_thumbnails_to_file, "thumbnail" tag from Thumbnails.cpp's
CompressedPNG::tag()) -- the same convention Klipper/Moonraker (Mainsail,
Fluidd), OctoPrint, and many printers' own screens already know how to read.

Generating this thumbnail server-side would normally mean standing up a
headless OpenGL context (confirmed: OrcaSlicer.cpp's export_gcode call passes
a hardcoded null thumbnail_cb on the plain --slice path -- the engine's own
GLFW-based renderer only ever runs for --export-3mf's separate plate-picker
preview, a code path already flagged in this repo as failure-prone in
constrained environments). The web UI already renders an accurate 3D view of
the model with the exact colors/nozzle assignment the user configured, so
this reuses a snapshot of that instead -- see web/src/components/Viewer.tsx's
capturePreview and App.tsx's handleSlice.
"""

from __future__ import annotations

import base64
import binascii
import io
import logging
import re
import zipfile
from pathlib import Path

from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)

# Matches OrcaSlicer's own default `thumbnails` print-config value
# ("48x48/PNG,300x300/PNG", PrintConfig.cpp) -- anything reading these
# blocks (Mainsail, Fluidd, OctoPrint, a printer's own screen) already
# expects to find sizes like these.
_THUMBNAIL_SIZES = [(48, 48), (300, 300)]
_MAX_LINE_LENGTH = 78  # matches GCodeThumbnails.hpp's own max_row_length


def _decode_preview_png(preview_image_base64: str) -> bytes | None:
    # Tolerate a data: URL slipping through unstripped.
    if preview_image_base64.startswith("data:"):
        _, _, preview_image_base64 = preview_image_base64.partition(",")
    try:
        return base64.b64decode(preview_image_base64, validate=True)
    except (binascii.Error, ValueError):
        return None


def _square_thumbnail(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    # Center-crop to square first -- the viewer's canvas is whatever aspect
    # ratio its panel happens to be, and a plain resize would squash it.
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    cropped = image.crop((left, top, left + side, top + side))
    return cropped.resize(size, Image.Resampling.LANCZOS)


def _thumbnail_block(image: Image.Image) -> str:
    lines = ["; THUMBNAIL_BLOCK_START"]
    for width, height in _THUMBNAIL_SIZES:
        buf = io.BytesIO()
        _square_thumbnail(image, (width, height)).save(buf, format="PNG")
        encoded = base64.b64encode(buf.getvalue()).decode("ascii")
        lines.append(";")
        lines.append(f"; thumbnail begin {width}x{height} {len(encoded)}")
        for i in range(0, len(encoded), _MAX_LINE_LENGTH):
            lines.append(f"; {encoded[i:i + _MAX_LINE_LENGTH]}")
        lines.append("; thumbnail end")
    lines.append("; THUMBNAIL_BLOCK_END")
    lines.append("")
    return "\n".join(lines) + "\n"


def embed_preview(output_dir: Path, preview_image_base64: str) -> None:
    """Best-effort -- never raises. A bad/missing preview image just means
    the job's gcode ends up with no thumbnail, not a failed slice (this
    runs after slicing has already succeeded)."""
    png_bytes = _decode_preview_png(preview_image_base64)
    if png_bytes is None:
        logger.warning("preview_image_base64 did not decode as base64, skipping thumbnail")
        return
    try:
        image = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    except UnidentifiedImageError:
        logger.warning("preview_image_base64 did not decode as a PNG, skipping thumbnail")
        return

    block = _thumbnail_block(image)

    for gcode_path in output_dir.glob("*.gcode"):
        try:
            original = gcode_path.read_text(errors="replace")
            gcode_path.write_text(block + original)
        except OSError:
            logger.warning("Failed to embed thumbnail into %s", gcode_path, exc_info=True)
    for three_mf in output_dir.glob("*.gcode.3mf"):
        try:
            _add_cover_pictures(three_mf, image)
        except (OSError, zipfile.BadZipFile):
            logger.warning("Failed to add the cover picture to %s", three_mf, exc_info=True)


# ---- the sliced 3MF a Bambu printer is sent ----
# A printer and Bambu's app show a job's picture from the 3MF itself, laid out as Bambu Studio's own export writes a plate (bbs_3mf.cpp,
# _add_relationships_file_to_archive): Metadata/plate_N.png and plate_N_small.png (128 px), found through three entries in _rels/.rels.

_PLATE_GCODE = re.compile(r"^Metadata/plate_(\d+)\.gcode$")
_COVER_SIZE = 512
_SMALL_COVER_SIZE = 128
_PICTURE_RELATIONS = (
    ("rel-2", "plate_{n}.png", "http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail"),
    ("rel-4", "plate_{n}.png", "http://schemas.bambulab.com/package/2021/cover-thumbnail-middle"),
    ("rel-5", "plate_{n}_small.png", "http://schemas.bambulab.com/package/2021/cover-thumbnail-small"),
)


def _png(image: Image.Image, size: int) -> bytes:
    buf = io.BytesIO()
    _square_thumbnail(image, (size, size)).save(buf, format="PNG")
    return buf.getvalue()


def _relations_for(plate: int) -> str:
    return "".join(
        f' <Relationship Target="/Metadata/{target.format(n=plate)}" Id="{rel_id}" Type="{kind}"/>\n'
        for rel_id, target, kind in _PICTURE_RELATIONS
    )


def _add_cover_pictures(three_mf: Path, image: Image.Image) -> None:
    with zipfile.ZipFile(three_mf) as source:
        names = set(source.namelist())
        plates = sorted(int(m.group(1)) for name in names if (m := _PLATE_GCODE.match(name)))
        plates = [n for n in plates if f"Metadata/plate_{n}.png" not in names]
        if not plates:
            return
        # Bambu's own export points its three entries at one plate: the first one (a job holds one plate here).
        relations = _relations_for(plates[0])
        tmp = three_mf.with_name(three_mf.name + ".new")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
            for item in source.infolist():
                data = source.read(item.filename)
                if item.filename == "_rels/.rels":
                    data = data.decode().replace("</Relationships>", relations + "</Relationships>").encode()
                elif item.filename == "[Content_Types].xml" and b'Extension="png"' not in data:
                    data = (
                        data.decode()
                        .replace("<Default ", '<Default Extension="png" ContentType="image/png"/><Default ', 1)
                        .encode()
                    )
                out.writestr(item, data)
            for n in plates:
                out.writestr(f"Metadata/plate_{n}.png", _png(image, _COVER_SIZE))
                out.writestr(f"Metadata/plate_{n}_small.png", _png(image, _SMALL_COVER_SIZE))
    tmp.replace(three_mf)
