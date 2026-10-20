<p align="center">
  <img src="docs/assets/trident-icon-512.png" alt="Trident" width="160">
</p>

<h1 align="center">Trident Studio</h1>

<p align="center">
  <b>A self-hosted slicer for your server.</b><br>
  OrcaSlicer's slicing engine, run headless in Docker, with a web UI you can use from any browser or phone.
  Works with the printers OrcaSlicer supports, and with belt printers as a bonus.

<p align="center">
  <a href="https://ko-fi.com/mugenoesis"><img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="Support me on Ko-fi"></a>
</p>

</p>
<p align="center">
https://www.youtube.com/watch?v=1vSq-iEaazE
</p>

<p align="center">
  <img src="docs/assets/screenshot-sliced.png" alt="Trident showing a sliced 3DBenchy for a Snapmaker U1" width="900">
</p>

## What it does

Upload a model, pick a printer and material, slice, preview the G-code layer by layer, and download it or send it
straight to your printer. It runs on a NAS or home server, so you can slice from your phone, or from a
machine that has no slicer installed.

- **Your printer is probably already in it.** OrcaSlicer's whole printer, filament and process library is built in,
  from 70+ vendors (Bambu Lab, Prusa, Creality, Snapmaker, Voron, Elegoo, Anycubic, Qidi, Sovol and many more). You can
  also import your own profiles (`.json`, `.zip`, `.orca_printer`, `.orca_filament`, `.orca_bundle`).
- **Make your own printers.** A printer that isn't in the list: copy one (or start from nothing, or a generic Marlin, Klipper, RRF, Repetier or belt printer) and set the bed, nozzle, firmware, start and end G-code and motion, with every other printer setting a search away on the Advanced tab. Belt printers can be endless or have a real length. You can export your printers and materials for desktop OrcaSlicer. A Klipper printer can fill the form in itself: **Read it from a Klipper printer** takes its address (and an API key if Moonraker wants one) and reads its own config through Moonraker, read-only. It fills in the bed, nozzle, speeds, retraction and the end macro (and the start line when the start macro takes temperatures), marks each value as read from the printer, says where each came from, and lists what to check (a toolchanger's travel is bigger than its bed, a macro that takes no temperatures is not guessed at). Nothing is saved until you save the printer; the same read is `POST /printers/klipper-import`.
- **Make your own materials.** Create a new material from any existing one with a short form (temperatures, bed
  temperature per plate, flow, fan); everything else is inherited, and any other material setting is a search away on the Advanced tab, and you choose whether it is for the current printer only or for every printer.
- **Multi-material and tool changers.** Assign a file's colours to nozzles and slice multi-colour models, including
  4-head printers like the Snapmaker U1. The build plate list only offers plates your chosen filament supports.
- **Multi-plate 3MF files.** Preview each plate, slice any plate, and choose which objects in a file to print, with
  thumbnails so you can tell them apart.
- **Rotate and move.** A preview of your plate with sliders to place the model and to turn it on each axis, plus
  "Lay flat" and "Pick a face" (choose the face that should sit on the plate in a window of its own, and the plate is
  see-through so you can pick the underside). Works for 3MF files too. For a file with several objects, pick one and
  turn or move it while the others stay greyed out; Apply writes them all together, and overlaps are flagged. With a
  multi-plate file it works on the plate you have picked and leaves the other plates alone.
- **Scale, auto-orient, auto-arrange and copies.** Scale the model, let the slicer orient or arrange it, and print
  several copies.
- **Mesh check.** STL files are checked on upload for the defects the slicer repairs, and holes it cannot repair are
  flagged before they become a bad print.
- **Resin (MSLA) printers.** Switch to **Resin** to slice for resin printers: pick one of the 150+ in the catalogue (Elegoo, Anycubic, Creality, Phrozen, FlashForge, UniFormation and more), pick a resin from the built-in library of published exposure and lift settings (each with its source), listed for the printer you picked: a resin with no settings for it is not offered (tick "Also show resins with no settings for this printer" to start from a resin made for another printer: its bottom and transition layers carry over, the exposure is left for you with the other printer's numbers as a hint, and "Make my own resin based on this config…" keeps the result for your printer), adjust them, set supports, pad and hollowing, and download the file your printer reads (.ctb, .goo, .pwmb, ...). Look at the layers as the printer will expose them (a slider through the sliced layers). Bring in a resin profile from another slicer (a Chitubox .cfg or a PrusaSlicer .ini) with Import a resin file…; it is saved as resins of your own. Make your own resin printer when yours is not in the list: copy one from the catalogue or start from its screen size, pixel counts, build height and file format; the numbers are checked (a printer rejects a file that does not match its screen). Give a bottle price and size and the result shows what the print cost in resin (the price and size are kept with a resin of your own). A layer too big to peel easily from the film (over 20 cm², our rule of thumb) gets a warning. Save the exposure and lift values on screen as a resin of your own (listed under "My resins", private to your account). Save a resin setup (printer, resin and slice settings) as a saved printer; saved printers are listed in FDM and Resin groups. The slicer can write most of those formats; printers whose format it cannot write yet are listed and marked. None of the formats has been checked on a real printer yet, so please report what works.
- **Send to your printer.** Upload the G-code to a Moonraker (Klipper, Mainsail, Fluidd) or OctoPrint printer.
- **Watch your printers.** The **Printers** button in the header opens a page with a card for each saved printer that has a Klipper (Moonraker) address: its state (printing, paused, finished, error, offline), the file, progress with layers and an estimate of the time left, every nozzle, the bed and the chamber temperature, and its webcam (a picture renewed about once a second, through Trident, so the printer's address and key stay on the server). **Pause**, **Resume** and **Cancel** (which asks first) are all the page can do to a printer. The page asks the printers only while it is open (`GET /printers/{id}/status`, `POST /printers/{id}/print/{pause|resume|cancel}`, `GET /printers/{id}/webcams`).
- **Every setting is reachable.** The common ones (layer height, infill, walls, seam, brim, supports, build plate) are
  up front, and all 800+ OrcaSlicer settings are under Advanced. Saved printers and settings profiles keep your setups.
- **Works on a phone.** Responsive single-page app, installable as a PWA. There is also an HTTP API with Swagger docs
  at `/docs`.
- **Single-user or multi-user.** Run it just for yourself with no login, or switch to accounts.
- **API keys.** Another program can use Trident without a login: make a key in the settings menu (the cog, **API keys…**).
  A **Holecraft** key may only upload models, so a program such as [Holecraft](https://github.com/mugenoesis/holecraft) can
  send a design here and open it (the page opens at `/?model=<id>`); a **Holecraft resin tools** key may also have models hollowed (`POST /resin/hollow`: a wall of 0.5 to 20 mm, answered with the hollow model as an STL) and ask for the support points the slicer would use (`POST /resin/supports`, answered as JSON) and see the list of resin printers (`GET /resin/printers`) and the resin printers you have saved (`GET /resin/saved-printers`), which is what Holecraft's Hollow and support-editing tools use; a model given points (`PUT /models/<id>/support-points`, the points moved or added to) is printed with exactly those supports unless the job sets `hand_placed_supports` to false; a **full-access** key may use every API. A key is shown
  once when you make it, only a hash is stored, and it can be revoked at any time. Send it as `Authorization: Bearer <key>`.

<p align="center">
  <img src="docs/assets/screenshot-model.png" alt="Trident with a model loaded on the plate" width="560">
</p>

### Bonus: belt printers

Belt (conveyor) printers such as the IdeaFormer IR3 V2 work too, which most slicers can't do well. Trident adds tree
supports that grow down to the belt, a flat pad at the belt, purge-line alignment so the print starts right at the
purge, and an endless-length bed. You can line several objects up along the belt and drag them into print order.

<p align="center">
  <img src="docs/assets/screenshot-belt.png" alt="A sliced 3DBenchy on a belt printer" width="560">
</p>

## Install

Trident is one container. It needs port 8000 and three folders to keep your data.

### Docker

```bash
docker run -d --name trident --restart unless-stopped \
  -p 8000:8000 \
  -v /path/to/trident/models:/data/models \
  -v /path/to/trident/output:/data/output \
  -v /path/to/trident/orcaslicer-datadir:/data/orcaslicer-datadir \
  mugenoesis/trident:latest
```

Then open `http://<your-server>:8000/`. The first visit asks whether it's just you (no login) or several people.

> **Security:** in single-user mode there is no login, so anyone who can reach port 8000 can use Trident, see your models and use your saved printers. Keep it on your home network. Before exposing it to the internet, switch on multi-user mode (accounts) and put it behind an HTTPS reverse proxy.

### Docker Compose

```yaml
services:
  trident:
    image: mugenoesis/trident:latest
    container_name: trident
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - ./data/models:/data/models                    # uploaded models
      - ./data/output:/data/output                    # sliced G-code, jobs, saved printers and settings
      - ./data/orcaslicer-datadir:/data/orcaslicer-datadir
```

### Unraid

Open the **Apps** tab, search for "Trident" and click **Install**. The template maps port 8000 and stores everything
under `/mnt/user/appdata/trident/`. The template lives in
[mugenoesis/unraid-templates](https://github.com/mugenoesis/unraid-templates).

### Notes

- **Architecture:** the image is `linux/amd64` only.
- **Size:** about 1.4 GB on disk (about 560 MB to download).
- **Your data** lives only in the three mounted folders; the container itself keeps nothing.
- **Exposing it outside your network:** see the security note above (multi-user mode and an HTTPS reverse proxy).

## Build it yourself

```bash
git clone --recurse-submodules https://github.com/mugenoesis/Trident.git
cd Trident
docker build -f docker/Dockerfile -t trident \
  --build-arg ORCASLICER_COMMIT_SHA=$(git -C vendor/orcaslicer rev-parse HEAD) .
```

The first build compiles OrcaSlicer from source and takes a long time (about an hour on a fast machine). Pass
`--build-arg BUILD_JOBS=<n>` to limit how many cores it uses. Later builds reuse the cached layers.

## Developing

```bash
cd api
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                          # mocked, no OrcaSlicer binary needed
.venv/bin/uvicorn app.main:app --reload   # http://localhost:8000/docs
```

Without a real `orca-slicer` binary the slicing endpoints degrade gracefully, which is handy for working on the API.
The web app lives in [`web/`](web/README.md). The design is in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

### Code quality checks

AI coding sessions: read [`AGENTS.md`](AGENTS.md) first.


The real-slicer API tests run in an engine image with `scripts/slicer-tests.sh <image>`.

One gate runs everything CI runs: `scripts/check.sh` (or `scripts/check.sh web` / `api`). A host with no Python can run the
Python tools through `scripts/py.sh`, a throwaway container, for example `scripts/py.sh ruff check app`.

| Area | Tools |
|---|---|
| Web | [Biome](https://biomejs.dev) (format, lint, cognitive complexity), [knip](https://knip.dev) (unused code and dependencies), `tsc` |
| API | [black](https://black.readthedocs.io) (format), [ruff](https://docs.astral.sh/ruff) (lint, security, imports), [pyright](https://github.com/microsoft/pyright) (types), [complexipy](https://github.com/rohaquinlop/complexipy) (cognitive complexity), [vulture](https://github.com/jendrikseipp/vulture) (dead code), pytest with a coverage floor |
| Both | `scripts/audit.sh` (known vulnerabilities in what ships), `scripts/docker-lint.sh` (hadolint and trivy on the Dockerfile), Dependabot |

Format with `npm run format` in `web/` and `black app tests tests_slicer` in `api/`. Every function is held to a cognitive
complexity of 15 (Biome in the web app, complexipy in the API): when one goes over, split it into smaller pieces. Run `git config blame.ignoreRevsFile .git-blame-ignore-revs` so `git blame` skips the reformat commits.

```
Trident/
├── vendor/orcaslicer/   # git submodule: the patched OrcaSlicer fork
├── docker/              # multi-stage Dockerfile and entrypoint
├── api/                 # FastAPI service
├── web/                 # React/Vite web app
├── docs/                # architecture and AGPL notes
└── scripts/             # the check gate, audits, smoke tests and helpers
```

## Support the project

Trident is free and I build it in my spare time. If it saves you time or gets your printer printing, you can
[buy me a coffee on Ko-fi](https://ko-fi.com/mugenoesis). Bug reports and ideas are welcome as GitHub issues.

## License and credits

Trident is licensed under the [GNU Affero General Public License v3.0](LICENSE). Copyright (C) 2026 mugenoesis.

It is built on [OrcaSlicer](https://github.com/OrcaSlicer/OrcaSlicer) (AGPL-3.0), which descends from Bambu
Studio, PrusaSlicer and Slic3r. This project is not affiliated with or endorsed by any of them. The slicer inside the
container is a patched fork (see `vendor/orcaslicer`, a git submodule). If you use a hosted instance over a network,
you are entitled to the corresponding source:

- Pseudorca, the patched OrcaSlicer fork: <https://github.com/mugenoesis/Pseudorca/tree/headless-orca>
- This repository: <https://github.com/mugenoesis/Trident>

The exact commit the running container was built from is shown by the app's `/source` and `/version` endpoints.
See [`docs/AGPL-COMPLIANCE.md`](docs/AGPL-COMPLIANCE.md).
