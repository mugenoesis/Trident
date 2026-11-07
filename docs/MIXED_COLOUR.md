# Mixed colours (virtual filaments)

A **mixed filament** is a filament slot that is not loaded in any nozzle. The slicer resolves it, layer by layer, into 2 or 3 of the
physical filaments, so thin alternating layers read as a blend (the idea behind the Full Spectrum fork of OrcaSlicer, later taken into
Snapmaker Orca and upstream OrcaSlicer). Nothing is mixed in the nozzle; the G-code only ever selects physical tools.

The engine (`vendor/orcaslicer`) already has all of it. What Trident adds is a way to define a mix, see its colour, and apply it to a model.

## What the engine does (checked by `api/tests_slicer/test_mixed_filament.py`)

Slots are 1-based, and mixed slots come after the physical ones (4 physical filaments: the first mix is slot 5).

| Option (per filament slot) | Meaning |
|---|---|
| `filament_is_mixed` | `1` for a mixed slot. Components and ratios are refused (`filament_is_mixed: must be set ...`) when no slot is flagged, so send them only when a mix exists. |
| `filament_mixed_components` | The physical slots, e.g. `"1,2"`. Two or three, none of them mixed. |
| `filament_mixed_sublayer_ratios` | One weight per component, e.g. `"0.75,0.25"`. Normalised by the engine. |
| `filament_mixed_gradient*` | A gradient from one component to the other along Z (two components only). Needs the sub-layer option. |
| `enable_mixed_color_sublayer` (process) | Off: whole layers alternate by ratio. On: each layer is split into sub-layers, one per component. |

On the command line a per-slot list is `;`-separated and each entry is quoted when it holds a comma:
`--filament-mixed-components='"";"";"1,2"'`. Trident already passes `setting_overrides` through as `--key=value`, so none of these
needs engine or `cli_runner` changes.

Seen with a model on a mixed slot of the Snapmaker U1 (0.20 mm layers):

- ratios `0.5/0.5`, `0.75/0.25` and `0.8/0.2` give that share of layers to each component (within 4%);
- three components (`0.5,0.25,0.25`) share the layers the same way;
- with the sub-layer option every layer selects every component;
- the mixed slot itself is never selected: a mixed slot prints on its components only.

### Open: painted models

A cube painted in three colours, where the third is a mixed slot, printed with a single tool per layer, as if the painted
physical colours had been dropped. A model whose objects each sit on one slot behaves correctly. Before Holecraft's palette can carry
mixes (painted triangles), reproduce this with a project saved by Snapmaker Orca and find out whether it is the fixture or the engine.

## Licences of what this uses

Anything Trident ports or ships must be open and credited (AGENTS.md rule 10).

- **FilamentMixer polynomial model** (`FilamentMixerModel.hpp`, upstream `justinh-rahb/filament-mixer`): MIT, Copyright (c) 2026 Justin Hayes.
  Its coefficients were fitted to approximate Mixbox output (Mixbox is CC BY-NC); the project states it contains no Mixbox code, binaries
  or data. A Python port keeps the MIT notice.
- **`standard_color_recipes.json`** (measured and interpolated blend recipes, `resources/filament_mixing/`): the same file exists in
  [bambulab/BambuStudio](https://github.com/bambulab/BambuStudio) (AGPL-3.0); OrcaSlicer's commit that updated it says it was ported from
  there. AGPL-3.0, which is what Trident is.
- **ratdoux/OrcaSlicer-FullSpectrum**: AGPL-3.0, the origin of the mixed-slot feature. Snapmaker Orca and OrcaSlicer carry it on.

## Plan

Each step is its own branch and PR.

0. **Verify the engine** (this change): the real-slicer tests above, and this note.
1. **API**: a mix model in the job's `setting_overrides`, checks that mirror the engine's, and a Python port of the mixer for a colour preview
   and a "find a mix for this colour" match (with its own tests, checked against the engine's numbers).
2. **Web UI**: a Mixed colours panel next to the colour assignment. A hosted HTML/React mockup is approved first.
3. **Holecraft**: a palette slot can be a mix, and the OrcaSlicer 3MF export and Send to Trident carry it.
4. **Later**: gradients with a curve editor, image-to-mixed-colours, dithering.
