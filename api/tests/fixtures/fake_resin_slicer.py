#!/usr/bin/env python3
"""Stand-in for the slicer's resin path, used by test_resin_runner.py and test_jobs_resin.py.

Like the real one it takes --load-settings "printer;process", an optional --load-filaments (the resin) and a model, prints
"sla N% text" progress lines, writes plate_1.<ext> and result.json into --outputdir. The arguments it was given are written to
args.json (with the support points file it was given, if any) so the tests can look at them; a process profile with hollowing_min_thickness 99 makes it fail the way the real one does.
"""

import argparse
import json
import pathlib
import struct
import sys
import zipfile
import zlib


def square_png(i: int, width: int = 100, height: int = 60) -> bytes:
    """A width x height grayscale PNG with a white square of (i + 1) * 5 pixels on black: layer i has ((i + 1) * 5) ** 2 white pixels."""
    side = (i + 1) * 5
    rows = b"".join(b"\x00" + bytes(255 if x < side and y < side else 0 for x in range(width)) for y in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


parser = argparse.ArgumentParser()
parser.add_argument("--slice")
parser.add_argument("--datadir")
parser.add_argument("--outputdir", required=True)
parser.add_argument("--load-settings")
parser.add_argument("--load-filaments")
parser.add_argument("--allow-newer-file")
parser.add_argument("--sla-hollow-output")
parser.add_argument("--sla-support-points-input")
parser.add_argument("--sla-support-points-output")
parser.add_argument("model", nargs="?")
args, _unknown = parser.parse_known_args()

out = pathlib.Path(args.outputdir)
out.mkdir(parents=True, exist_ok=True)
printer_file, process_file = args.load_settings.split(";")
printer = json.loads(pathlib.Path(printer_file).read_text())
process = json.loads(pathlib.Path(process_file).read_text())
material = json.loads(pathlib.Path(args.load_filaments).read_text()) if args.load_filaments else None
points_input = (
    json.loads(pathlib.Path(args.sla_support_points_input).read_text()) if args.sla_support_points_input else None
)
(out / "args.json").write_text(
    json.dumps(
        {
            "support_points_input": points_input,
            "printer": printer,
            "process": process,
            "material": material,
            "model": args.model,
            "allow_newer": args.allow_newer_file,
        }
    )
)

if args.sla_hollow_output:
    # hollowing instead of slicing: a wall of 13 is "too thin" (to test a refusal); otherwise the file names what it was asked for
    wall = process.get("hollowing_min_thickness")
    quality = process.get("hollowing_quality", "")
    print("sla 10% Hollowing model", flush=True)
    if wall == "13":
        (out / "result.json").write_text(
            json.dumps({"return_code": -51, "error_string": "The model is too thin for a wall of 13 mm"})
        )
        print("hollowing failed: The model is too thin for a wall of 13 mm", file=sys.stderr)
        sys.exit(-51 & 0xFF)
    target = pathlib.Path(args.sla_hollow_output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(
        f"solid fake hollow wall={wall} quality={quality} model={pathlib.Path(args.model).suffix}\n".encode()
    )
    (out / "result.json").write_text(
        json.dumps(
            {
                "return_code": 0,
                "error_string": "",
                "printer_technology": "SLA",
                "hollow_file": str(target),
                "triangle_count": "1234",
                "volume_before_mm3": "8000.000000",
                "volume_after_mm3": "3900.000000",
            }
        )
    )
    sys.exit(0)

if args.sla_support_points_output:
    # support points instead of slicing: those given back, or three made up (the first carries the display width and the density it was
    # given, to show they arrived); a wall of 99 is "does not fit" (to test a refusal)
    print("sla 10% Placing support points", flush=True)
    if process.get("hollowing_min_thickness") == "99":
        (out / "result.json").write_text(json.dumps({"return_code": -21, "error_string": "does not fit"}))
        print("support points failed: does not fit", file=sys.stderr)
        sys.exit(-21 & 0xFF)
    made = points_input or {
        "objects": [
            {
                "points": [
                    {
                        "x": float(printer["display_width"]),
                        "y": float(process.get("support_points_density_relative", 0)),
                        "z": 0,
                        "radius": 0.4,
                        "type": "island",
                    },
                    {"x": 1, "y": 1, "z": 0, "radius": 0.4, "type": "slope"},
                    {"x": 2, "y": 2, "z": 0, "radius": 0.4, "type": "slope"},
                ]
            }
        ]
    }
    target = pathlib.Path(args.sla_support_points_output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(made))
    count = sum(len(o["points"]) for o in made["objects"])
    (out / "result.json").write_text(
        json.dumps(
            {
                "return_code": 0,
                "error_string": "",
                "printer_technology": "SLA",
                "support_points_file": str(target),
                "support_point_count": str(count),
            }
        )
    )
    sys.exit(0)

print("sla 10% Slicing", flush=True)
print("sla 80% Writing the archive", flush=True)
# A layer-preview run (the printer's format swapped for SL1) fails when asked to, to test a preview that fails.
if printer.get("sla_archive_format") == "SL1" and process.get("elefant_foot_compensation") == "98":
    (out / "result.json").write_text(json.dumps({"return_code": -22, "error_string": "preview failed"}))
    print("resin slicing failed: preview failed", file=sys.stderr)
    sys.exit(-22 & 0xFF)
if process.get("hollowing_min_thickness") == "99":
    (out / "result.json").write_text(json.dumps({"return_code": -21, "error_string": "does not fit"}))
    print("resin slicing failed: does not fit", file=sys.stderr)
    sys.exit(-21 & 0xFF)

if printer.get("sla_archive_format") == "SL1":
    # an SL1 archive: settings text and one PNG per layer (three here)
    sl1 = out / "plate_1.sl1"
    with zipfile.ZipFile(sl1, "w") as z:
        z.writestr("config.ini", "action = print\n")
        for i in range(3):
            z.writestr(f"fake{i:05d}.png", square_png(i))
ext = {"CTB": "ctb", "CTBENCRYPTED": "ctb", "GOO": "goo"}.get(printer.get("sla_archive_format", ""), "sl1")
archive = out / f"plate_1.{ext}"
if printer.get("sla_archive_format") != "SL1":
    archive.write_bytes(b"fake printer file")
(out / "result.json").write_text(
    json.dumps(
        {
            "return_code": 0,
            "error_string": "",
            "printer_technology": "SLA",
            "archive_file": str(archive),
            "archive_format": printer.get("sla_archive_format", "SL1"),
            "layer_count": "400",
            "layer_height_mm": f"{float(process.get('layer_height', 0.05)):.6f}",
            "estimated_print_time_s": "5000.000000",
            "resin_used_ml": "8.000000",
            "support_point_count": str(sum(len(o["points"]) for o in points_input["objects"]) if points_input else 12),
        }
    )
)
print("sla exported", archive, flush=True)
sys.exit(0)
