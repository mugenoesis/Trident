# Slicer tests

These run the real OrcaSlicer on multi-colour 3MF projects the tests generate (a cube painted in 1 to 6 colours,
saved for a Bambu X1C or the Snapmaker U1) and check that a job started the way the app starts one slices and
writes G-code, over colour counts, printers (U1, a single-nozzle printer, the belt printer) and colour-to-nozzle
assignments. They need the slicer binary and profiles, so they are skipped where those are missing, and they are
kept out of the fast suite (`tests/`).

Run them in the container image (about four minutes):

    docker run --rm --entrypoint sh -v "$PWD/api":/src:ro mugenoesis/trident:latest -c \
        'cp -r /src /work && cd /work && /opt/api/.venv/bin/python -m pip install -q pytest && \
         /opt/api/.venv/bin/python -m pytest tests_slicer -v'

To test code that is not in the image yet, mount it over the installed app:

    -v "$PWD/api/app":/opt/api/.venv/lib/python3.12/site-packages/app:ro

A new case is a row in `test_multicolour_matrix.py`. When a real file crashes or fails, reduce it to the colour
count, printer and assignment that reproduce it and add that row.
