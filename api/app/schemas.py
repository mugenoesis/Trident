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
