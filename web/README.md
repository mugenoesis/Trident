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
