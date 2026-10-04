<!-- Paste this into the Docker Hub repository's "Overview" (Repository > General > Edit). -->
# Trident

**A self-hosted slicer for your server.** Trident runs [OrcaSlicer](https://github.com/OrcaSlicer/OrcaSlicer)'s slicing engine headless in Docker, with a web UI you can use from any browser or phone. It works with the printers OrcaSlicer supports, and with belt (conveyor) printers as a bonus.

![Trident slicing a Benchy for a Snapmaker U1](https://raw.githubusercontent.com/mugenoesis/Trident/master/docs/assets/screenshot-sliced.png)

## Quick start

```bash
docker run -d --name trident --restart unless-stopped \
  -p 8000:8000 \
  -v /path/to/trident/models:/data/models \
  -v /path/to/trident/output:/data/output \
  -v /path/to/trident/orcaslicer-datadir:/data/orcaslicer-datadir \
  mugenoesis/trident:latest
```

Then open `http://<your-server>:8000/`.

> **Security:** in single-user mode there is no login, so anyone who can reach port 8000 can use Trident. Keep it on your home network, or use multi-user mode behind an HTTPS reverse proxy.

## What it does
- OrcaSlicer's full printer, filament and process library (70+ vendors), plus import of your own profiles
- Multi-material and tool-changer printers (for example the Snapmaker U1), multi-plate 3MF files with object picking
- Position, scale, auto-orient, auto-arrange and copies; layer-by-layer G-code preview
- Send G-code to Moonraker (Klipper) or OctoPrint printers
- Belt printer support (IdeaFormer IR3 V2 and similar)
- Phone-friendly web app and an HTTP API at `/docs`

## Details
- **Tags:** `latest`, and a version tag such as `0.1.1`.
- **Platform:** linux/amd64.
- **Port:** 8000. **Volumes:** `/data/models`, `/data/output`, `/data/orcaslicer-datadir`.
- **Docker Compose, Unraid and building from source:** see the [README](https://github.com/mugenoesis/Trident#install).
- **Source:** [Trident](https://github.com/mugenoesis/Trident) and its slicer fork [Pseudorca](https://github.com/mugenoesis/Pseudorca). Licensed under AGPL-3.0.
- **Support the project:** [ko-fi.com/mugenoesis](https://ko-fi.com/mugenoesis).
