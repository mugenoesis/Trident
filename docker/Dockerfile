# syntax=docker/dockerfile:1.7
#
# Multi-stage build: compile OrcaSlicer's headless-patched fork, then
# assemble a slim runtime image that runs it under Xvfb behind the
# FastAPI wrapper. See docs/ARCHITECTURE.md for the full design and
# docs/AGPL-COMPLIANCE.md for why the fork commit SHA is baked in below.
#
# `vendor/orcaslicer` is a git submodule pointing at the headless-orca
# branch of https://github.com/mugenoesis/Pseudorca — run
# `git submodule update --init` before building.

ARG UBUNTU_VERSION=24.04

# ---------------------------------------------------------------------------
# Frontend build stage -- independent of the OrcaSlicer C++ build below, so
# changes here never invalidate that (multi-hour, cached) stage.
# ---------------------------------------------------------------------------
FROM node:22-slim AS frontend

WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Builder stage
# ---------------------------------------------------------------------------
FROM ubuntu:${UBUNTU_VERSION} AS builder

ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /src
COPY vendor/orcaslicer/ ./orcaslicer/
WORKDIR /src/orcaslicer

# Install system deps via the fork's own script rather than
# hand-transcribing them (docs/ARCHITECTURE.md). `sudo` isn't present in
# the base ubuntu image and build_linux.sh -u shells out to it.
RUN --mount=type=cache,target=/var/cache/apt,id=apt-cache-builder,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends sudo git \
    && ./build_linux.sh -u

# vendor/orcaslicer is a git submodule, so the `.git` COPY'd in above is a
# gitlink (a one-line text file) pointing at the superproject's
# .git/modules/... -- which isn't part of this build context. Several deps
# CMake patch steps shell out to `git apply` and walk up looking for a real
# repo, so replace the dangling gitlink with a throwaway one so those
# succeed the same way they would against a normal (non-submodule) checkout.
RUN rm -rf .git \
    && git init -q \
    && git config user.email "build@headless-orca.local" \
    && git config user.name "headless-orca build" \
    && git add -A \
    && git commit -q -m "Snapshot for Docker build"

# Dependency build: slow (multi-hour, ~15-30GB) and cacheable in its own
# layer, kept separate from the main-build layer below so source-only
# changes don't invalidate it. Both compile steps run under nice -n 10 and
# use $(nproc) jobs by default; pass --build-arg BUILD_JOBS=<n> to leave CPU
# headroom for other workloads on the build host.
ARG BUILD_JOBS
RUN --mount=type=cache,target=/root/.cache/ccache \
    --mount=type=cache,target=/root/.cache/sccache \
    cmake -S deps -B deps/build -G Ninja \
    && nice -n 10 cmake --build deps/build -j${BUILD_JOBS:-$(nproc)}

RUN --mount=type=cache,target=/root/.cache/ccache \
    --mount=type=cache,target=/root/.cache/sccache \
    cmake -S . -B build -G "Ninja Multi-Config" \
        -DSLIC3R_PCH=ON -DORCA_TOOLS=ON \
    && nice -n 10 cmake --build build --config Release --target OrcaSlicer -j${BUILD_JOBS:-$(nproc)}

# ---------------------------------------------------------------------------
# Runtime stage
# ---------------------------------------------------------------------------
FROM ubuntu:${UBUNTU_VERSION} AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    ORCA_API_ORCASLICER_BIN=/opt/orcaslicer/orca-slicer \
    ORCA_API_PROFILES_DIR=/opt/orcaslicer/resources/profiles \
    ORCA_API_ORCASLICER_DATADIR=/data/orcaslicer-datadir \
    ORCA_API_MODELS_DIR=/data/models \
    ORCA_API_OUTPUT_DIR=/data/output \
    ORCA_API_JOBSTORE_PATH=/data/output/jobstore.sqlite3 \
    LD_LIBRARY_PATH=/opt/orcaslicer

# GTK3/X11/GL runtime libs the binary links regardless of SLIC3R_GUI at
# compile time, plus Xvfb + software Mesa as the offscreen-rendering path
# for thumbnail generation (GLFW's actual backend is X11/GLX, not EGL).
# libegl1/libgstreamer1.0-0/libgstreamer-plugins-base1.0-0/libwebkit2gtk-4.1-0
# were found by `ldd`'ing the built binary
# (wx's WebView backend and GStreamer media backend, both compiled in
# unconditionally regardless of whether they're ever exercised headlessly).
RUN --mount=type=cache,target=/var/cache/apt,id=apt-cache-runtime,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
        xvfb \
        libgl1-mesa-dri \
        libegl1 \
        libgtk-3-0 \
        libx11-6 \
        libxkbcommon0 \
        libglu1-mesa \
        libgstreamer1.0-0 \
        libgstreamer-plugins-base1.0-0 \
        libwebkit2gtk-4.1-0 \
        ca-certificates \
        python3 \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

# The whole Release/ directory, not just the executable: CMake stages the
# embedded Python distribution (src/slic3r/plugin's pybind11::embed target)
# and a self-built FFmpeg (newer .so versions than Ubuntu 24.04 ships) as
# siblings of the binary. The executable's RUNPATH covers $ORIGIN/python/lib;
# the FFmpeg libs aren't covered by any RUNPATH entry, hence LD_LIBRARY_PATH
# above pointing at this same directory.
COPY --from=builder /src/orcaslicer/build/src/Release/ /opt/orcaslicer/
COPY --from=builder /src/orcaslicer/resources /opt/orcaslicer/resources
RUN ln -s /opt/orcaslicer/orca-slicer /usr/local/bin/orca-slicer

# Pass e.g. --build-arg ORCASLICER_COMMIT_SHA=$(git -C vendor/orcaslicer rev-parse HEAD)
ARG ORCASLICER_COMMIT_SHA=unknown
ENV ORCA_API_ORCASLICER_COMMIT_SHA=${ORCASLICER_COMMIT_SHA}

WORKDIR /opt/api
COPY api/pyproject.toml ./
COPY api/app ./app
RUN python3 -m venv /opt/api/.venv \
    && /opt/api/.venv/bin/pip install --no-cache-dir .

# Built web/ frontend, served by the API itself (app/main.py mounts this as
# a StaticFiles catch-all after all API routes) -- one container, one port,
# same-origin so the Android "Add to Home Screen" PWA flow needs no CORS.
COPY --from=frontend /web/dist /opt/api/static
ENV ORCA_API_STATIC_DIR=/opt/api/static

VOLUME ["/data/models", "/data/output", "/data/orcaslicer-datadir"]

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
CMD ["serve"]
