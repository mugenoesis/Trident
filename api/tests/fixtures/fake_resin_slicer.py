#!/usr/bin/env python3
"""Stand-in for the slicer's resin path, used by test_resin_runner.py and test_jobs_resin.py.

Like the real one it takes --load-settings "printer;process", an optional --load-filaments (the resin) and a model, prints
"sla N% text" progress lines, writes plate_1.<ext> and result.json into --outputdir. The arguments it was given are written to
args.json so the tests can look at them; a process profile with hollowing_min_thickness 99 makes it fail the way the real one does.
"""

import argparse
import base64
import json
import pathlib
import sys
import zipfile

parser = argparse.ArgumentParser()
parser.add_argument("--slice")
parser.add_argument("--datadir")
parser.add_argument("--outputdir", required=True)
parser.add_argument("--load-settings")
parser.add_argument("--load-filaments")
parser.add_argument("--allow-newer-file")
parser.add_argument("model", nargs="?")
args, _unknown = parser.parse_known_args()

out = pathlib.Path(args.outputdir)
out.mkdir(parents=True, exist_ok=True)
printer_file, process_file = args.load_settings.split(";")
printer = json.loads(pathlib.Path(printer_file).read_text())
process = json.loads(pathlib.Path(process_file).read_text())
material = json.loads(pathlib.Path(args.load_filaments).read_text()) if args.load_filaments else None
(out / "args.json").write_text(
    json.dumps(
        {
            "printer": printer,
            "process": process,
            "material": material,
            "model": args.model,
            "allow_newer": args.allow_newer_file,
        }
    )
)

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
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptVAAAACklEQVR4nGNgAAAAAgABSK+kcQAAAABJRU5ErkJggg=="
    )
    sl1 = out / "plate_1.sl1"
    with zipfile.ZipFile(sl1, "w") as z:
        z.writestr("config.ini", "action = print\n")
        for i in range(3):
            z.writestr(f"fake{i:05d}.png", png)
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
        }
    )
)
print("sla exported", archive, flush=True)
sys.exit(0)
