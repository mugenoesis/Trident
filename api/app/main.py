from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import profiles as profiles_module
from .config import settings
from .routers import jobs, models, profiles, source


@asynccontextmanager
async def lifespan(app: FastAPI):
    profiles_module.catalog.load()
    yield


app = FastAPI(
    title="headless-orca",
    description=(
        "HTTP wrapper around a headless, patched OrcaSlicer CLI. "
        "AGPL-3.0 — see GET /source."
    ),
    lifespan=lifespan,
)

app.include_router(models.router)
app.include_router(profiles.router)
app.include_router(jobs.router)
app.include_router(source.router)


@app.middleware("http")
async def add_source_header(request, call_next):
    response = await call_next(request)
    response.headers["X-Source-Available-At"] = "/source"
    return response


@app.get("/version")
def version() -> dict[str, str]:
    return {
        "orcaslicer_fork_url": settings.orcaslicer_fork_url,
        "orcaslicer_commit_sha": settings.orcaslicer_commit_sha,
    }


@app.get("/healthz")
def healthz() -> dict[str, bool]:
    return {"ok": True}
