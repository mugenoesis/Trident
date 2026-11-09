"""Mixed filaments: filament slots that are not loaded in any nozzle but are a mix of two or three physical filaments,
which the slicer prints layer by layer (see docs/MIXED_COLOUR.md).

A job lists its physical filaments and, apart from them, its mixes. Each mix becomes one more slot after the physical
ones, and `expand` writes the per-slot options the slicer reads (`filament_is_mixed`, `filament_mixed_components`,
`filament_mixed_sublayer_ratios`, and the process option `enable_mixed_color_sublayer`), checked the way the slicer
checks them so a bad mix is refused before a slice is started.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from itertools import combinations
from typing import Any

from pydantic import BaseModel

from app import colour_mixer

MIN_COMPONENTS = 2
MAX_COMPONENTS = 3


class MixedFilament(BaseModel):
    # 1-based numbers of the physical filaments that make the mix up, and one weight (any positive number) for each.
    components: list[int]
    weights: list[float]


def ratio_text(weights: list[float]) -> str:
    """The weights as the slicer writes ratios: shares of their total, four decimals, comma separated."""
    total = sum(weights)
    return ",".join(f"{weight / total:.4f}" for weight in weights)


def check(mix: MixedFilament, physical: int) -> None:
    """Raises ValueError for a mix the slicer would refuse: it needs 2 or 3 different physical filaments, one weight each."""
    if not MIN_COMPONENTS <= len(mix.components) <= MAX_COMPONENTS:
        raise ValueError(f"A mix is made of 2 or 3 filaments, not {len(mix.components)}")
    if any(not 1 <= component <= physical for component in mix.components):
        raise ValueError(f"A mix can only use the physical filaments 1 to {physical}: {mix.components}")
    if len(set(mix.components)) != len(mix.components):
        raise ValueError(f"A mix cannot use the same filament twice: {mix.components}")
    if len(mix.weights) != len(mix.components):
        raise ValueError(f"A mix needs one weight for each filament: {len(mix.weights)} weights for {mix.components}")
    if any(not weight > 0 for weight in mix.weights):
        raise ValueError(f"The weights of a mix must be positive: {mix.weights}")


def _per_slot(physical: int, mixes: list[str]) -> str:
    """A text option with one entry per slot: empty for the physical ones, then the mixes', each in quotes (they hold commas)."""
    return ";".join(f'"{entry}"' for entry in [""] * physical + mixes)


def expand(
    filament_profiles: list[str], mixes: list[MixedFilament], sublayers: bool = False
) -> tuple[list[str], dict[str, str]]:
    """The filament profiles and setting overrides that make a job slice `mixes` after its `filament_profiles`.

    A mixed slot is not printed with its own material, but the slicer wants a profile for every slot; it gets the one of
    the mix's first component. `sublayers` splits every layer into one sub-layer per component, where otherwise whole
    layers alternate by ratio. Nothing is added when there are no mixes: the slicer refuses mix options without one."""
    physical = len(filament_profiles)
    for mix in mixes:
        check(mix, physical)
    if not mixes:
        return list(filament_profiles), {}
    overrides = {
        "filament_is_mixed": ",".join(["0"] * physical + ["1"] * len(mixes)),
        "filament_mixed_components": _per_slot(physical, [",".join(map(str, mix.components)) for mix in mixes]),
        "filament_mixed_sublayer_ratios": _per_slot(physical, [ratio_text(mix.weights) for mix in mixes]),
    }
    if sublayers:
        overrides["enable_mixed_color_sublayer"] = "1"
    return [*filament_profiles, *(filament_profiles[mix.components[0] - 1] for mix in mixes)], overrides


def preview(colours: list[str], mix: MixedFilament) -> str:
    """What the mix looks like, as `#RRGGBB`, given the colours of the physical filaments (see colour_mixer)."""
    total = sum(mix.weights)
    weights = [max(1, round(weight / total * 1000)) for weight in mix.weights]
    return colour_mixer.blend([colours[component - 1] for component in mix.components], weights)


MIX_OPTION_KEYS = frozenset(
    {"filament_is_mixed", "filament_mixed_components", "filament_mixed_sublayer_ratios", "enable_mixed_color_sublayer"}
)


def hand_set_keys(setting_overrides: dict[str, Any]) -> frozenset[str]:
    """The mix options a job set by hand, which cannot be combined with a mix defined the proper way."""
    return MIX_OPTION_KEYS & setting_overrides.keys()


@dataclass(frozen=True)
class Suggestion:
    mix: MixedFilament
    colour: str
    distance: float


def _compositions(total: int, parts: int) -> Iterator[tuple[int, ...]]:
    """Every way to split `total` into `parts` whole numbers of at least 1."""
    if parts == 1:
        yield (total,)
        return
    for first in range(1, total - parts + 2):
        for rest in _compositions(total - first, parts - 1):
            yield (first, *rest)


def suggest(
    colours: list[str], target: str, count: int = 5, max_components: int = MAX_COMPONENTS, steps: int = 10
) -> list[Suggestion]:
    """The mixes of `colours` (the physical filaments') that come closest to the `target` colour, closest first.

    Every pair, and with `max_components` 3 every triple, of the filaments is tried in whole tenths (`steps`); a mix
    is previewed as the engine blends it, so what is found is what the preview then shows."""
    found = []
    for size in range(MIN_COMPONENTS, min(max_components, MAX_COMPONENTS) + 1):
        for chosen in combinations(range(1, len(colours) + 1), size):
            for weights in _compositions(steps, size):
                mix = MixedFilament(components=list(chosen), weights=[float(w) for w in weights])
                colour = preview(colours, mix)
                found.append(Suggestion(mix, colour, colour_mixer.distance(colour, target)))
    found.sort(key=lambda suggestion: (suggestion.distance, len(suggestion.mix.components)))
    return found[:count]
