"""Mixed filaments: what a mix looks like, and which mix gives a colour (see mixed_filaments.py)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import colour_mixer, mixed_filaments
from ..auth import require_user
from ..mixed_filaments import MixedFilament
from ..userstore import User

router = APIRouter(prefix="/mixes", tags=["mixes"])


class PreviewRequest(BaseModel):
    colours: list[str]  # the physical filaments' colours, `#RRGGBB`, in slot order
    mixes: list[MixedFilament]


class PreviewResponse(BaseModel):
    colours: list[str]  # one per mix


class SuggestRequest(BaseModel):
    colours: list[str]
    target: str
    count: int = Field(default=5, ge=1, le=50)
    max_components: int = Field(default=3, ge=2, le=3)


class SuggestionRecord(BaseModel):
    components: list[int]
    weights: list[float]
    colour: str
    distance: float  # CIE76 difference from the target colour


class SuggestResponse(BaseModel):
    suggestions: list[SuggestionRecord]


def _check_colours(colours: list[str]) -> None:
    unreadable = [colour for colour in colours if not colour_mixer.is_hex(colour)]
    if unreadable:
        raise HTTPException(status_code=400, detail=f"Colours are written #RRGGBB, not {unreadable}")


@router.post("/preview", response_model=PreviewResponse)
def preview(request: PreviewRequest, _user: User = Depends(require_user)) -> PreviewResponse:
    _check_colours(request.colours)
    try:
        for mix in request.mixes:
            mixed_filaments.check(mix, len(request.colours))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PreviewResponse(colours=[mixed_filaments.preview(request.colours, mix) for mix in request.mixes])


@router.post("/suggest", response_model=SuggestResponse)
def suggest(request: SuggestRequest, _user: User = Depends(require_user)) -> SuggestResponse:
    _check_colours([*request.colours, request.target])
    found = mixed_filaments.suggest(request.colours, request.target, request.count, request.max_components)
    return SuggestResponse(
        suggestions=[
            SuggestionRecord(
                components=s.mix.components, weights=s.mix.weights, colour=s.colour, distance=round(s.distance, 2)
            )
            for s in found
        ]
    )
