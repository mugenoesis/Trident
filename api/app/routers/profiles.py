from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import profiles as profiles_module
from ..schemas import ProfileDetail, ProfileSummary, SettingsSchema
from ..settings_schema import build_settings_schema

router = APIRouter(tags=["profiles"])


@router.get("/profiles", response_model=list[ProfileSummary])
def list_profiles() -> list[ProfileSummary]:
    return profiles_module.catalog.list()


@router.get("/profiles/{vendor}/{kind}/{name}", response_model=ProfileDetail)
def get_profile(vendor: str, kind: str, name: str) -> ProfileDetail:
    detail = profiles_module.catalog.get(vendor, kind, name)
    if detail is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return detail


@router.get("/settings/schema", response_model=SettingsSchema)
def get_settings_schema() -> SettingsSchema:
    return build_settings_schema()
