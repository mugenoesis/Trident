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

## How a job asks for a mix (`api/app/mixed_filaments.py`)

`POST /jobs` takes `mixed_filaments`: a list of `{components: [1, 2], weights: [3, 1]}` (1-based physical filaments, 2 or 3 different ones, one
positive weight each) and `mixed_sublayers`. Trident puts each mix in a slot after the `filament_profiles` (sliced with its first component's
material, since the slicer wants a profile for every slot), writes the per-slot options of the table above into `setting_overrides` and answers
with the job as it was sliced, so a mix can be read back from the record. Ratios are written the way the engine writes them (shares of the
total, `%.4f`). A mix the engine would refuse (one component, a repeat, a filament that is not physical, a missing or non-positive weight) is a
400 before any slicing, mix options set by hand cannot be combined with `mixed_filaments`, and nothing is sent when there is no mix. Models put
their parts on a mixed slot the same way as on any slot: slot number physical filaments + 1 for the first mix.

`POST /mixes/preview` (`colours` of the physical filaments, `mixes`) returns the colour of each mix; `POST /mixes/suggest` (`colours`, `target`,
`count`, `max_components`) tries every pair, and every triple, of the filaments in tenths and returns the closest to the target by CIE76 colour
difference. The real slicer tests (`test_mixed_filament.py`) cover a job with three filaments and one mix, and four physical filaments with a
mix on a four-nozzle printer.

## The colour preview (`api/app/colour_mixer.py`)

A Python port of the engine's mixer, so the app can show what a mix looks like without slicing. It is the degree-4 polynomial of the two
colours and the ratio; three components are folded in one at a time (each by its share of the total so far), as the engine's
`blend_color_multi` does. `scripts/mixer-reference.sh` compiles the engine's own `FilamentMixerModel.hpp` to write the model's numbers
(`api/app/mixer_model/filament_mixer_model.json`) and a reference set (`api/tests/fixtures/colour_mixer_reference.json`); the tests require the
port to match it exactly. Run the script again when the engine submodule moves.

The engine first looks a blend up in a table of measured recipes (`standard_color_recipes.json`, PLA Basic colours at 20 to 80% ratios) and
uses the polynomial only when there is no entry. The port does not carry that table, so its colour is the polynomial's estimate: for the few
measured colours the engine's own preview can differ a little. The preview is a guide, not a promise of the printed colour.

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

0. **Verify the engine** (done): the real-slicer tests above, and this note.
1. **API** (this change): `mixed_filaments` on jobs with the checks above, the Python colour mixer (checked against the engine's numbers), and the preview and suggest routes.
2. **Web UI**: a Mixed colours panel next to the colour assignment. A hosted HTML/React mockup is approved first.
3. **Holecraft**: a palette slot can be a mix, and the OrcaSlicer 3MF export and Send to Trident carry it.
4. **Later**: gradients with a curve editor, image-to-mixed-colours, dithering.
