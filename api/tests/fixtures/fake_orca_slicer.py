#!/usr/bin/env python3
"""Stand-in for the real OrcaSlicer CLI, used by test_cli_runner.py.

Mimics just enough of the --pipe / result.json protocol
(docs/ARCHITECTURE.md) to exercise cli_runner.run_slice's FIFO handling
without needing a real, built binary.
"""
import argparse
import json
import pathlib
import sys

if "--help-json" in sys.argv:
    # cli_runner.fetch_help_json()'s target -- a tiny slice of real
    # ConfigDef metadata (see PrintConfig.cpp) covering exactly the keys
    # test_cli_runner.py's out-of-range-override tests need, min/max
    # included so _option_bounds() has something to work with. Handled
    # before the --outputdir/--pipe-requiring parser below since a real
    # `--help-json` invocation never passes those.
    print(json.dumps([
        {"key": "raft_first_layer_expansion", "type": "float", "min": 0, "default": "2"},
        {"key": "tree_support_wall_count", "type": "int", "min": 0, "max": 2, "default": "0"},
    ]))
    sys.exit(0)

parser = argparse.ArgumentParser()
parser.add_argument("--slice")
parser.add_argument("--datadir")
parser.add_argument("--outputdir", required=True)
parser.add_argument("--pipe", required=True)
parser.add_argument("--load-settings")
parser.add_argument("--load-filaments")
parser.add_argument("--arrange")
parser.add_argument("--raft-first-layer-expansion")
parser.add_argument("--tree-support-wall-count")
parser.add_argument("model", nargs="?")
args, _unknown = parser.parse_known_args()

with open(args.pipe, "w") as f:
    f.write(json.dumps(
        {"plate_index": 1, "plate_count": 1, "plate_percent": 50.0,
         "total_percent": 50.0, "message": "slicing"}
    ) + "\n")
    f.write(json.dumps(
        {"plate_index": 1, "plate_count": 1, "plate_percent": 100.0,
         "total_percent": 100.0, "message": "done"}
    ) + "\n")

outputdir = pathlib.Path(args.outputdir)
outputdir.mkdir(parents=True, exist_ok=True)
(outputdir / "result.json").write_text(json.dumps({"return_code": 0, "error_string": ""}))
(outputdir / "out.gcode").write_text("; fake gcode\n")
# Records the received --slice value so test_cli_runner.py can assert on it
# without needing to mock subprocess.run (which would leave the FIFO
# reader thread blocked forever waiting for a writer that never connects).
(outputdir / "slice_arg.txt").write_text(args.slice or "")
(outputdir / "arrange_arg.txt").write_text(args.arrange or "")
(outputdir / "raft_first_layer_expansion_arg.txt").write_text(args.raft_first_layer_expansion or "")

sys.exit(0)
