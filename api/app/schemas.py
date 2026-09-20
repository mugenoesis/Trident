from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ModelUploadResponse(BaseModel):
    model_id: str
    filename: str


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
    -- see api/app/threemf.py's module docstring for why this only covers
    per-object/per-part color (not per-triangle paint)."""

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


class ThreeMfInspection(BaseModel):
    plates: list[PlateInfo]
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
    # The printer/material profile last selected -- restored as the default
    # next time this account opens the site (App.tsx applies these once the
    # matching printers/materials list has loaded).
    last_printer_id: str | None = None
    last_material_id: str | None = None


class LastSelectionRequest(BaseModel):
    printer_id: str | None = None
    material_id: str | None = None


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
    name: str
    quick_settings: dict[str, str] = Field(default_factory=dict)
    advanced_overrides: dict[str, str] = Field(default_factory=dict)
    process_profile: str | None = None
    # One entry per physical extruder/AMS slot, index-aligned with
    # filament_colors. None (vs. an empty list) means "this material profile
    # doesn't touch filament choice", matching the old scalar's None.
    filament_profiles: list[str] | None = None
    filament_colors: list[str] | None = None  # "#rrggbb", UI label only


class MaterialProfileUpdateRequest(BaseModel):
    """A field left out entirely is left unchanged (see routers/printers.py's
    `model_dump(exclude_unset=True)`) -- used both for a plain rename
    ({"name": ...}) and "update mode" (overwriting the saved settings with
    the current ones: {"quick_settings": ..., "advanced_overrides": ...})."""

    name: str | None = None
    quick_settings: dict[str, str] | None = None
    advanced_overrides: dict[str, str] | None = None
    process_profile: str | None = None
    filament_profiles: list[str] | None = None
    filament_colors: list[str] | None = None


class MaterialProfileRecord(BaseModel):
    id: str
    printer_id: str
    name: str
    quick_settings: dict[str, str]
    advanced_overrides: dict[str, str]
    process_profile: str | None = None
    filament_profiles: list[str] | None = None
    filament_colors: list[str] | None = None
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
