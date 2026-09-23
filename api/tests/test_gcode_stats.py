from pathlib import Path

from app import gcode_stats


def test_parse_total_filament_grams_sums_every_extruder(tmp_path: Path):
    gcode_path = tmp_path / "plate_1.gcode"
    gcode_path.write_text(
        "G28\nG1 X10\n"
        "; filament used [mm] = 1234.56, 78.90\n"
        "; filament used [cm3] = 12.34, 0.56\n"
        "; filament used [g] = 15.23, 0.67\n"
        "; total filament used [g] = 15.90\n"
    )

    assert gcode_stats.parse_total_filament_grams(gcode_path) == 15.9


def test_parse_total_filament_grams_single_extruder(tmp_path: Path):
    gcode_path = tmp_path / "plate_1.gcode"
    gcode_path.write_text("; filament used [g] = 42.00\n")

    assert gcode_stats.parse_total_filament_grams(gcode_path) == 42.0


def test_parse_total_filament_grams_missing_line_returns_none(tmp_path: Path):
    gcode_path = tmp_path / "plate_1.gcode"
    gcode_path.write_text("G28\nG1 X10\n; just some other comment\n")

    assert gcode_stats.parse_total_filament_grams(gcode_path) is None


def test_parse_total_filament_grams_missing_file_returns_none(tmp_path: Path):
    assert gcode_stats.parse_total_filament_grams(tmp_path / "does-not-exist.gcode") is None


def test_parse_total_filament_grams_only_scans_the_tail(tmp_path: Path):
    # A footer line followed by enough trailing content to push it more
    # than _TAIL_BYTES from EOF should not be found -- confirms this only
    # ever reads the tail, not the whole file (the real footer is always
    # near the very end, per GCode.cpp, so this never happens in practice).
    gcode_path = tmp_path / "plate_1.gcode"
    trailing_junk = "; padding\n" * 20000
    gcode_path.write_text("; filament used [g] = 10.00\n" + trailing_junk)

    assert gcode_stats.parse_total_filament_grams(gcode_path) is None


def test_total_filament_grams_for_job_sums_across_plates(tmp_path: Path):
    (tmp_path / "plate_1.gcode").write_text("; filament used [g] = 10.00\n")
    (tmp_path / "plate_2.gcode").write_text("; filament used [g] = 5.00, 2.50\n")

    assert gcode_stats.total_filament_grams_for_job(tmp_path) == 17.5


def test_total_filament_grams_for_job_no_gcode_files_returns_none(tmp_path: Path):
    assert gcode_stats.total_filament_grams_for_job(tmp_path) is None
