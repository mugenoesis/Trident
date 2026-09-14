# headless-orca web UI

React + Vite + TypeScript frontend for headless-orca: upload a model, pick a
printer/nozzle/material, adjust the common slicing settings, slice, and
download the G-code. See `../docs/ARCHITECTURE.md` for the overall project.

In production this is built to static files and served by the FastAPI app
itself (`api/app/main.py`'s `StaticFiles` mount, wired up in `docker/Dockerfile`'s
`frontend` build stage) — same origin as the API, no CORS, and installable as
a PWA ("Add to Home Screen") on Android.

## Development

```bash
npm install
npm run dev        # Vite dev server on :5173, talking to the API on :8000
                    # (see src/api.ts -- CORS on the API side covers this)
```

The API needs to be running separately (e.g. the deployed `headless-orca`
Docker container, or `cd ../api && uvicorn app.main:app --reload`).

## Known limitation: G-code preview's "Solid" mode is GPU-heavy

The G-code preview (`src/components/GcodeViewer.tsx`) has two render modes.
"Lines" (the default) is cheap -- one `LineSegments` draw call. "Solid"
renders every extruded move as its own lit, shadow-casting box via an
`InstancedMesh`, which is a lot more per-pixel work (shadow map pass + real
lighting), all done client-side in the browser's WebGL context -- nothing
runs server-side for this, so there's nothing to move off-device. It's tuned
down some (device pixel ratio capped at 2x, no MSAA, a smaller shadow map)
but a large/detailed model can still be genuinely heavy on a phone, especially
high-resolution/high-DPR devices (e.g. foldables). If it's sluggish, switch
back to "Lines" -- there isn't currently a way to make "Solid" itself lighter
beyond what's already applied without changing what it looks like (e.g.
decimating the toolpath, which would need a real quality tier of its own).

## Build

```bash
npm run build       # -> dist/
```

## End-to-end smoke test

`smoke-test.mjs` drives a real browser (Playwright) against a *running*
headless-orca instance: uploads `fixtures/test-cube.stl`, picks a printer and
material, slices, and waits for success. This host can't install Playwright's
browser binaries directly (no system package manager outside Docker), so run
it in a container that already has them:

```bash
docker run --rm --network host -v "$(pwd):/work" -w /work \
  mcr.microsoft.com/playwright:v1.63.0-jammy npm run smoke
```

(Keep the image tag in sync with the `playwright` version in `package.json`.)
