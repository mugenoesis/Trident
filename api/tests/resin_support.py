"""A small resin catalogue and the stand-in resin slicer, shared by the resin tests."""

import json
from pathlib import Path

FAKE_BIN = Path(__file__).parent / "fixtures" / "fake_resin_slicer.py"

PRESET = {
    "type": "machine",
    "name": "Elegoo Mars 3",
    "printer_technology": "SLA",
    "printer_model": "Mars 3",
    "display_width": "143.43",
    "display_height": "89.6",
    "display_pixels_x": "4098",
    "display_pixels_y": "2560",
    "printable_height": "175",
    "display_mirror_x": "1",
    "display_mirror_y": "0",
    "sla_archive_format": "CTBENCRYPTED",
}
MATERIAL = {
    "type": "material",
    "name": "Test resin",
    "vendor": "Test",
    "settings": [{"printers": ["*"], "layer_height": 0.05, "exposure_time": 2.5, "initial_exposure_time": 30}],
}


# A resin whose only row is for one printer (like most published ones), to show what a printer that is not in the catalogue can use.
SPECIFIC_MATERIAL = {
    "type": "material",
    "name": "Specific resin",
    "vendor": "Test",
    "settings": [
        {"printers": ["Elegoo Mars 3"], "layer_height": 0.05, "exposure_time": 7, "initial_exposure_time": 40}
    ],
}


def build_resin_dir(root: Path) -> Path:
    """Elegoo Mars 3 (can be sliced for), Elegoo Old (no writer yet) and the resin "Test resin"."""
    (root / "printers" / "Elegoo").mkdir(parents=True)
    (root / "printers" / "Elegoo" / "Mars 3.json").write_text(json.dumps(PRESET))
    (root / "printers" / "Elegoo" / "Old.json").write_text(
        json.dumps({**PRESET, "name": "Elegoo Old", "sla_archive_format": "lgs"})
    )
    printers = [
        {
            "vendor": "Elegoo",
            "model": "Mars 3",
            "file": "printers/Elegoo/Mars 3.json",
            "format": "CTBENCRYPTED",
            "supported": True,
        },
        {"vendor": "Elegoo", "model": "Old", "file": "printers/Elegoo/Old.json", "format": "lgs", "supported": False},
    ]
    (root / "index.json").write_text(json.dumps({"printers": printers}))
    (root / "materials" / "Test").mkdir(parents=True)
    (root / "materials" / "Test" / "Resin.json").write_text(json.dumps(MATERIAL))
    (root / "materials" / "Test" / "Specific.json").write_text(json.dumps(SPECIFIC_MATERIAL))
    entries = [
        {"name": "Test resin", "vendor": "Test", "file": "materials/Test/Resin.json"},
        {"name": "Specific resin", "vendor": "Test", "file": "materials/Test/Specific.json"},
    ]
    (root / "materials-index.json").write_text(json.dumps({"materials": entries}))
    return root
