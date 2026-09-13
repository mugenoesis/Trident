from __future__ import annotations

from fastapi import APIRouter

from ..config import settings
from ..schemas import SourceInfo

router = APIRouter(tags=["source"])


@router.get("/source", response_model=SourceInfo)
def get_source() -> SourceInfo:
    """AGPL-3.0 source-offer link (docs/AGPL-COMPLIANCE.md)."""
    return SourceInfo(
        orcaslicer_fork_url=settings.orcaslicer_fork_url,
        orcaslicer_commit_sha=settings.orcaslicer_commit_sha,
        wrapper_repo_url=settings.wrapper_repo_url,
    )
