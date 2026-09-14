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
    created_at: str
    updated_at: str
    progress: JobProgress | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class AuthStatus(BaseModel):
    mode: str  # "unset" | "single" | "multi"
    logged_in: bool
    username: str | None = None


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
    filament_profile: str | None = None


class MaterialProfileUpdateRequest(BaseModel):
    """A field left out entirely is left unchanged (see routers/printers.py's
    `model_dump(exclude_unset=True)`) -- used both for a plain rename
    ({"name": ...}) and "update mode" (overwriting the saved settings with
    the current ones: {"quick_settings": ..., "advanced_overrides": ...})."""

    name: str | None = None
    quick_settings: dict[str, str] | None = None
    advanced_overrides: dict[str, str] | None = None
    process_profile: str | None = None
    filament_profile: str | None = None


class MaterialProfileRecord(BaseModel):
    id: str
    printer_id: str
    name: str
    quick_settings: dict[str, str]
    advanced_overrides: dict[str, str]
    process_profile: str | None = None
    filament_profile: str | None = None
    created_at: str


class PrinterCreateRequest(BaseModel):
    name: str
    vendor: str
    machine_profile: str
    process_profile: str
    filament_profile: str
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
    filament_profile: str
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
