from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

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

app.add_middleware(
    CORSMiddleware,
    # Wide open: this is only exercised by `npm run dev` (frontend on a
    # different port) hitting this API directly. The built frontend is
    # served from this same app (see the StaticFiles mount below), so
    # production traffic is same-origin and never touches CORS at all.
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
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


# Mounted last so it never shadows the API routes/docs above: Starlette
# matches routes in registration order, and StaticFiles here is a catch-all.
# html=True serves index.html for unmatched paths too, which is what a
# client-side-routed SPA needs (this app has none yet, but costs nothing).
if settings.static_dir.is_dir():
    app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="static")
