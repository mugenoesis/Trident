"""Curated, bundled OrcaSlicer sample models (vendor/orcaslicer/resources/
handy_models) -- exposed via GET /sample-models and instantiated into a
normal model_id via POST /sample-models/{id}/load, so the UI can offer a
"load a sample" option without the user needing their own file.

Deliberately a small hand-picked subset, not the full handy_models/calib
tree: most of the calib/ 3MFs bake a specific printer profile into their
own project_settings.config (e.g. "Bambu Lab H2D"), which would silently
conflict with whatever printer the user actually has selected, and several
handy_models entries (OrcaSliced.3mf, calicat.drc, ksr_fdmtest_v4.drc, ...)
are large or otherwise not great generic "try it out" defaults.

Most of these ship as OrcaSlicer's own Draco-compressed .drc format, not
plain STL/3MF -- confirmed against the vendored C++ source
(libslic3r/Model.cpp's read_from_file() dispatches ".drc" to
Format/DRC.cpp's load_drc() in the same unconditional if/else chain as
.stl/.3mf/.obj, and OrcaSlicer.cpp's CLI path calls that same
read_from_file()) that the CLI slices .drc files exactly like any other
supported format, no conversion needed.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import settings


@dataclass(frozen=True)
class SampleModel:
    id: str
    name: str
    description: str
    filename: str  # relative to settings.sample_models_dir


_SAMPLES: list[SampleModel] = [
    SampleModel(
        id="benchy",
        name="3DBenchy",
        description="The classic torture-test tugboat.",
        filename="3DBenchy.drc",
    ),
    SampleModel(
        id="calibration-cube",
        name="Calibration Cube",
        description="OrcaSlicer's own dimensional-accuracy test cube.",
        filename="OrcaCube_v2.drc",
    ),
    SampleModel(
        id="orca-badge",
        name="Orca Badge",
        description="Multi-part logo badge.",
        filename="OrcaBadge.3mf",
    ),
    SampleModel(
        id="stanford-bunny",
        name="Stanford Bunny",
        description="A classic 3D-graphics test mesh.",
        filename="Stanford_Bunny.drc",
    ),
]

_BY_ID = {s.id: s for s in _SAMPLES}


def list_samples() -> list[SampleModel]:
    return list(_SAMPLES)


def get_sample(sample_id: str) -> SampleModel | None:
    return _BY_ID.get(sample_id)


def resolve_sample_path(sample: SampleModel) -> Path:
    return settings.sample_models_dir / sample.filename
