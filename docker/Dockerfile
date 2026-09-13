# syntax=docker/dockerfile:1.7
#
# Multi-stage build: compile OrcaSlicer's headless-patched fork, then
# assemble a slim runtime image that runs it under Xvfb behind the
# FastAPI wrapper. See docs/ARCHITECTURE.md for the full design and
# docs/AGPL-COMPLIANCE.md for why the fork commit SHA is baked in below.
#
# PREREQUISITE (not yet done as of this scaffold): `vendor/orcaslicer`
# must be a git submodule pointing at a public patched fork before this
# builds. Until then, `docker build` will fail at the COPY step — that's
# expected, not a bug in this Dockerfile.

ARG UBUNTU_VERSION=24.04

# ---------------------------------------------------------------------------
# Builder stage
# ---------------------------------------------------------------------------
FROM ubuntu:${UBUNTU_VERSION} AS builder

ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /src
COPY vendor/orcaslicer/ ./orcaslicer/
WORKDIR /src/orcaslicer

# Install system deps via the fork's own script rather than
# hand-transcribing them (docs/ARCHITECTURE.md).
RUN --mount=type=cache,target=/var/cache/apt \
    ./build_linux.sh -u

# Dependency build: slow (multi-hour, ~15-30GB) and cacheable in its own
# layer, kept separate from the main-build layer below so source-only
# changes don't invalidate it.
RUN --mount=type=cache,target=/root/.cache/ccache \
    --mount=type=cache,target=/root/.cache/sccache \
    cmake -S deps -B deps/build -G Ninja \
    && cmake --build deps/build -j"$(nproc)"

RUN --mount=type=cache,target=/root/.cache/ccache \
    --mount=type=cache,target=/root/.cache/sccache \
    cmake -S . -B build -G "Ninja Multi-Config" \
        -DSLIC3R_PCH=ON -DORCA_TOOLS=ON \
    && cmake --build build --config Release --target OrcaSlicer -j"$(nproc)"

# ---------------------------------------------------------------------------
# Runtime stage
# ---------------------------------------------------------------------------
FROM ubuntu:${UBUNTU_VERSION} AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    ORCA_API_ORCASLICER_BIN=/opt/orcaslicer/OrcaSlicer \
    ORCA_API_PROFILES_DIR=/opt/orcaslicer/resources/profiles \
    ORCA_API_ORCASLICER_DATADIR=/data/orcaslicer-datadir \
    ORCA_API_MODELS_DIR=/data/models \
    ORCA_API_OUTPUT_DIR=/data/output \
    ORCA_API_JOBSTORE_PATH=/data/output/jobstore.sqlite3

# GTK3/X11/GL runtime libs the binary links regardless of SLIC3R_GUI at
# compile time, plus Xvfb + software Mesa as the offscreen-rendering path
# for thumbnail generation (GLFW's actual backend is X11/GLX, not EGL).
RUN --mount=type=cache,target=/var/cache/apt \
    apt-get update && apt-get install -y --no-install-recommends \
        xvfb \
        libgl1-mesa-dri \
        libgtk-3-0 \
        libx11-6 \
        libxkbcommon0 \
        libglu1-mesa \
        ca-certificates \
        python3 \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

# TODO once the builder stage is real: `ldd` the built binary here (or in
# a throwaway build step) to capture the definitive runtime lib list,
# including dlopen-loaded GStreamer libs invisible to ldd, and add any
# missing packages above.

COPY --from=builder /src/orcaslicer/build/Release/OrcaSlicer /opt/orcaslicer/OrcaSlicer
COPY --from=builder /src/orcaslicer/resources /opt/orcaslicer/resources
RUN ln -s /opt/orcaslicer/OrcaSlicer /usr/local/bin/orca-slicer

# Pass e.g. --build-arg ORCASLICER_COMMIT_SHA=$(git -C vendor/orcaslicer rev-parse HEAD)
ARG ORCASLICER_COMMIT_SHA=unknown
ENV ORCA_API_ORCASLICER_COMMIT_SHA=${ORCASLICER_COMMIT_SHA}

WORKDIR /opt/api
COPY api/pyproject.toml ./
COPY api/app ./app
RUN python3 -m venv /opt/api/.venv \
    && /opt/api/.venv/bin/pip install --no-cache-dir .

VOLUME ["/data/models", "/data/output", "/data/orcaslicer-datadir"]

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
CMD ["serve"]
