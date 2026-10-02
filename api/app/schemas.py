from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, computed_field


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class MeshReport(BaseModel):
    """What the upload-time STL check found (see app/meshcheck.py)."""

    degenerate_faces: int = 0
    duplicate_faces: int = 0
    # Edges whose two faces disagree about orientation (flipped faces).
    inconsistent_edges: int = 0
    # The whole mesh is inside out.
    inverted: bool = False
    open_edges: int = 0
    nonmanifold_edges: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def fixed(self) -> list[str]:
        """Defects the slicer repairs by itself when it loads the file."""
        out: list[str] = []
        if self.duplicate_faces:
            out.append(f"{self.duplicate_faces} duplicate {'face' if self.duplicate_faces == 1 else 'faces'} removed")
        if self.degenerate_faces:
            out.append(f"{self.degenerate_faces} degenerate {'face' if self.degenerate_faces == 1 else 'faces'} removed")
        if self.inconsistent_edges:
            out.append("flipped faces corrected")
        if self.inverted:
            out.append("inside-out mesh turned the right way round")
        return out

    @computed_field  # type: ignore[prop-decorator]
    @property
    def warnings(self) -> list[str]:
        """Defects the slicer does not repair. Small gaps usually still slice
        (real models often have a few dozen); a large missing area does not."""
        if not (self.open_edges or self.nonmanifold_edges):
            return []
        parts = []
        if self.open_edges:
            parts.append(f"{self.open_edges} open edges")
        if self.nonmanifold_edges:
            parts.append(f"{self.nonmanifold_edges} edges shared by more than two faces")
        return [
            "The mesh is not watertight (" + ", ".join(parts) + "). "
            "Slicing usually still works; if it fails or the print has gaps, repair the model."
        ]


class ModelUploadResponse(BaseModel):
    model_id: str
    filename: str
    # Set only for an STL with something to report; None when it is clean,
    # not an STL, or could not be analysed.
    mesh_report: MeshReport | None = None


class SampleModelSummary(BaseModel):
    id: str
    name: str
    description: str


class ProfileSummary(BaseModel):
    vendor: str
    kind: str  # "machine" | "process" | "filament"
    name: str
    path: str


class ProfileDetail(ProfileSummary):
    data: dict[str, Any]


class ImportedProfile(BaseModel):
    kind: str  # "machine" | "process" | "filament"
    name: str
    inherits: str | None = None
    warning: str | None = None


class ImportIssue(BaseModel):
    file: str
    name: str | None = None
    reason: str


class ImportResult(BaseModel):
    """Outcome of POST /profiles/import (see app/userprofiles.py)."""

    imported: list[ImportedProfile]
    # Same name already imported earlier and overwrite was off; not saved.
    conflicts: list[ImportedProfile]
    skipped: list[ImportIssue]


class SettingDef(BaseModel):
    key: str
    type: str
    label: str | None = None
    description: str | None = None
    enum_values: list[str] | None = None
    default: Any | None = None


class SettingsSchema(BaseModel):
    source: str  # "help-json" | "help-text-fallback"
    settings: list[SettingDef]


class BeltLayout(BaseModel):
    """Belt printers only: lay the selected objects out in a row along the
    belt, in `order` (object indices, first printed first), `gap_mm` apart."""

    order: list[int]
    gap_mm: float = Field(default=10.0, ge=0, le=500)


class Placement(BaseModel):
    """Where to put the model: the centre of its footprint, in plate
    coordinates (mm, the same frame as the printer's printable_area)."""

    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)


class JobCreateRequest(BaseModel):
    model_id: str
    printer_profile: str
    process_profile: str
    filament_profiles: list[str] = Field(default_factory=list)
    setting_overrides: dict[str, Any] = Field(default_factory=dict)
    # 1-based, mirrors OrcaSlicer's own --slice N syntax. None means "not a
    # multi-plate .3mf" -- slice as today (--slice 0, all plates). Distinct
    # from JobProgress.plate_index/plate_count below, which are populated
    # from the --pipe progress stream (an output of slicing), not an input.
    plate_index: int | None = None
    # Put the whole model at an exact spot instead of letting the slicer place
    # it (not combined with belt_layout, which places the objects itself).
    placement: Placement | None = None
    # Print this many copies of the whole (selected) model. On a belt printer
    # they are lined up along the belt (belt_layout.gap_mm, default 10); on
    # any other printer the slicer arranges them. Placement is ignored.
    copies: int = Field(default=1, ge=1, le=50)
    # .3mf only: indices (see ObjectInfo.index) of objects NOT to print.
    excluded_objects: list[int] = Field(default_factory=list)
    # .3mf on a belt printer only: place the kept objects in a row (see above).
    belt_layout: BeltLayout | None = None
    # Raw base64 PNG (no "data:" prefix) of the browser's own 3D preview at
    # the moment slicing starts -- the OrcaSlicer CLI never renders a gcode
    # thumbnail itself (its thumbnail_cb is hardcoded null on the plain
    # --slice path), so routers/jobs.py embeds this one instead, once
    # slicing succeeds. See app/gcode_thumbnail.py. None if the frontend had
    # nothing loaded to capture -- the job still slices normally, just
    # without a preview.
    preview_image_base64: str | None = None


class JobProgress(BaseModel):
    plate_index: int | None = None
    plate_count: int | None = None
    plate_percent: float | None = None
    total_percent: float | None = None
    message: str | None = None
    warning: str | None = None


class JobRecord(BaseModel):
    id: str
    user_id: str
    status: JobStatus
    model_id: str
    printer_profile: str
    process_profile: str
    filament_profiles: list[str]
    setting_overrides: dict[str, Any]
    plate_index: int | None = None
    created_at: str
    updated_at: str
    progress: JobProgress | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class PlateInfo(BaseModel):
    index: int
    name: str | None = None
    object_count: int | None = None
    thumbnail: str | None = None  # in-zip path; None if not present/not a .3mf


class ColorNode(BaseModel):
    """Mirrors the exact tree shape three.js's 3MFLoader builds in the
    browser: one node per <build><item>/<component>, in the same order,
    recursively -- a leaf (no children) carries this object/part's own
    resolved color (from its assigned extruder + the file's
    filament_colour array), a composite (a <components> object) carries
    no color of its own, only children. The frontend walks its rendered
    Object3D tree in lockstep with this same structure to color each mesh
    -- see api/app/threemf.py's module docstring for the per-triangle
    paint approximation triangle_extruders/triangle_colors add on top of
    this per-object/per-part base color."""

    color: str | None = None
    # This leaf's 1-based extruder/filament-role index (None for a
    # composite, or a leaf with no resolvable extruder) -- `color` above is
    # just that role's color as the file's own author set it; the frontend
    # uses this index (extruder - 1 == the role's position in
    # embedded_filament_colors, i.e. roleNozzleAssignments) to instead show
    # whichever color the user actually assigned that role to, once they've
    # picked a nozzle for it, without needing a second round-trip.
    extruder: int | None = None
    children: list["ColorNode"] = Field(default_factory=list)
    # One entry per triangle in this leaf's own mesh, same order as its
    # <triangle> elements (and so the loaded 3D geometry's face order) --
    # only present (non-None) on a leaf with real per-triangle paint
    # overrides; always None for a composite, and for a leaf with no paint
    # data at all (the common case, already fully described by
    # color/extruder alone). A deliberate per-triangle approximation, not
    # a sub-triangle-accurate split -- see api/app/threemf.py's
    # _representative_extruder. Same extruder->color resolution and
    # live-reassignment substitution as the singular extruder/color pair
    # above, just per-triangle.
    triangle_extruders: list[int | None] | None = None
    triangle_colors: list[str | None] | None = None


class ObjectInfo(BaseModel):
    """One <build><item> of a .3mf, in file order. `index` is that position
    (0-based) -- the same order three.js's 3MFLoader builds its children in,
    so the browser's per-object meshes line up with this list."""

    index: int
    name: str
    plate: int
    width_mm: float
    depth_mm: float
    height_mm: float
    # Centre of the object in plate coordinates (mm), where the file puts it.
    center_x_mm: float = 0.0
    center_y_mm: float = 0.0


class ThreeMfInspection(BaseModel):
    plates: list[PlateInfo]
    # Empty for a non-3mf or a file whose objects could not be read.
    objects: list[ObjectInfo] = Field(default_factory=list)
    extruder_indices: list[int] = Field(default_factory=list)
    # The file's own author's filament_colour array (Metadata/
    # project_settings.config), one entry per filament role the file was
    # originally configured with -- more reliable than extruder_indices
    # for detecting real multi-material intent (catches paint-on/
    # per-triangle color assignments that per-object extruder metadata
    # misses entirely). An empty string means "role exists, no known
    # color" rather than "no role" -- length is what matters.
    embedded_filament_colors: list[str] = Field(default_factory=list)
    # The file's own author's saved material name per role (Metadata/
    # project_settings.config's filament_settings_id, e.g. "Bambu PLA
    # Basic @BBL A1M"), same index space as embedded_filament_colors --
    # shown next to each role's color swatch purely to help a user match
    # the file's intended material to one of their own; never used to
    # resolve an actual profile (that name won't exist in this printer's
    # own catalog). Empty string/list when unknown.
    embedded_filament_names: list[str] = Field(default_factory=list)
    # One entry per top-level <build><item> (in file order); see ColorNode.
    # Empty when the file has no per-object/part color info to offer (a
    # non-3mf, a plain single-object file, or one whose color is only
    # expressed as per-triangle paint, which isn't parsed here).
    color_tree: list[ColorNode] = Field(default_factory=list)


class AuthStatus(BaseModel):
    mode: str  # "unset" | "single" | "multi"
    logged_in: bool
    username: str | None = None
    # The printer/material/settings profile last selected -- restored as the
    # default next time this account opens the site (App.tsx applies these
    # once the matching printers/materials/settings-profiles list has loaded).
    last_printer_id: str | None = None
    last_material_id: str | None = None
    last_settings_profile_id: str | None = None


class LastSelectionRequest(BaseModel):
    printer_id: str | None = None
    material_id: str | None = None
    settings_profile_id: str | None = None


class AuthSetupRequest(BaseModel):
    mode: str  # "single" | "multi"
    username: str | None = None
    password: str | None = None


class SwitchToMultiRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class UserCreateRequest(BaseModel):
    username: str
    password: str


class MaterialProfileCreateRequest(BaseModel):
    """A material profile is filament choice only -- print-quality settings
    live separately in a SettingsProfile (see below), so the two can be
    saved/loaded/combined independently."""

    name: str
    # One entry per physical extruder/AMS slot, index-aligned with
    # filament_colors. None (vs. an empty list) means "this material profile
    # doesn't touch filament choice", matching the old scalar's None.
    filament_profiles: list[str] | None = None
    filament_colors: list[str] | None = None  # "#rrggbb", UI label only


class MaterialProfileUpdateRequest(BaseModel):
    """A field left out entirely is left unchanged (see routers/printers.py's
    `model_dump(exclude_unset=True)`) -- used both for a plain rename
    ({"name": ...}) and "update mode" (overwriting the saved filament
    choice with the current one)."""

    name: str | None = None
    filament_profiles: list[str] | None = None
    filament_colors: list[str] | None = None


class MaterialProfileRecord(BaseModel):
    id: str
    printer_id: str
    name: str
    filament_profiles: list[str] | None = None
    filament_colors: list[str] | None = None
    created_at: str


class SettingsProfileCreateRequest(BaseModel):
    """A settings profile is print-quality settings only (no filament
    choice) -- the counterpart to MaterialProfileCreateRequest, saved/loaded
    independently so the same materials can be reused across different
    quality presets and vice versa."""

    name: str
    quick_settings: dict[str, str] = Field(default_factory=dict)
    advanced_overrides: dict[str, str] = Field(default_factory=dict)
    process_profile: str | None = None


class SettingsProfileUpdateRequest(BaseModel):
    """Same left-out-means-unchanged convention as MaterialProfileUpdateRequest."""

    name: str | None = None
    quick_settings: dict[str, str] | None = None
    advanced_overrides: dict[str, str] | None = None
    process_profile: str | None = None


class SettingsProfileRecord(BaseModel):
    id: str
    printer_id: str
    name: str
    quick_settings: dict[str, str]
    advanced_overrides: dict[str, str]
    process_profile: str | None = None
    created_at: str


class PrinterCreateRequest(BaseModel):
    name: str
    vendor: str
    machine_profile: str
    process_profile: str
    # One entry per physical extruder/AMS slot, index-aligned with
    # filament_colors (e.g. Snapmaker U1 = several independent heads, Bambu
    # X1C = several AMS slots feeding one nozzle -- same shape either way).
    filament_profiles: list[str] = Field(default_factory=list)
    filament_colors: list[str] = Field(default_factory=list)  # "#rrggbb", UI label only -- never sent to OrcaSlicer
    bed_width: float | None = None
    bed_depth: float | None = None
    bed_height: float | None = None
    # host_type is limited to "octoprint"/"moonraker" by the frontend (the
    # only two send-to-printer actually knows how to talk to), but nothing
    # here stops a wider OrcaSlicer host_type value from being stored.
    host_type: str | None = None
    print_host: str | None = None
    printhost_apikey: str | None = None
    printhost_user: str | None = None
    printhost_password: str | None = None


class PrinterUpdateRequest(BaseModel):
    """A field left out of the request body entirely (vs. present as null or
    an empty string) is left unchanged -- see routers/printers.py's
    `model_dump(exclude_unset=True)`. Only name/connection fields are
    editable; a printer's slicing identity is delete-and-recreate."""

    name: str | None = None
    host_type: str | None = None
    print_host: str | None = None
    printhost_apikey: str | None = None
    printhost_user: str | None = None
    printhost_password: str | None = None


class PrinterRecord(BaseModel):
    id: str
    name: str
    vendor: str
    machine_profile: str
    process_profile: str
    filament_profiles: list[str]
    filament_colors: list[str]
    bed_width: float | None = None
    bed_depth: float | None = None
    bed_height: float | None = None
    host_type: str | None = None
    print_host: str | None = None
    # Write-only: the raw apikey/user/password are never sent back to the
    # browser once saved -- just whether *something* is configured.
    has_credentials: bool
    created_at: str


class TestConnectionRequest(BaseModel):
    """Ad-hoc connection test: validates fields the caller just typed in,
    for a printer that may not even be saved yet (routers/printers.py's
    POST /printers/test-connection) -- distinct from testing an
    already-saved printer's stored credentials (POST /printers/{id}/
    test-connection, which needs no body)."""

    host_type: str | None = None
    print_host: str | None = None
    printhost_apikey: str | None = None
    printhost_user: str | None = None
    printhost_password: str | None = None


class SendToPrinterRequest(BaseModel):
    # Physically starting a print is a real-world action software can't
    # verify is safe (bed clear? filament loaded?), so it's opt-in and
    # defaults off everywhere -- the frontend always surfaces this as an
    # explicit checkbox rather than defaulting it on.
    start_print: bool = False


class SourceInfo(BaseModel):
    license: str = "AGPL-3.0"
    notice: str = (
        "This service runs a patched fork of OrcaSlicer (AGPL-3.0). "
        "You are entitled to the corresponding source for the exact "
        "commit this instance was built from."
    )
    orcaslicer_fork_url: str
    orcaslicer_commit_sha: str
    wrapper_repo_url: str


class ModelOpRequest(BaseModel):
    """Body of POST /models/{id}/orient and /arrange: the printer to do it
    for (arrange needs its bed; orient does not)."""

    printer_profile: str | None = None
    process_profile: str | None = None
