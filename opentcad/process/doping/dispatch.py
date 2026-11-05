"""
opentcad.process.doping.dispatch — Apply the doping half of a Recipe
to a meshed MeshField.

A Recipe can mix topography steps (deposit, etch, oxidize) with doping
steps (implant, later anneal). The topography half runs during
`simulate()` and ends in a `TopographyState` which becomes a MeshField
via `topography_to_meshfield()`. That MeshField carries material_id
per cell but no dopants — this dispatcher is where doping gets
written in.

The order matters: an As implant at step 3 and a B implant at step 7
should land in the order the Recipe specifies, so a later implant can
counter-dope an earlier one in a window the user chose precisely.
Topography steps are *not* interleaved with doping here — every implant
runs after the mesh exists. That's fine for the NMOS flow (all
topography is done before S/D implant) but doesn't model well implants
followed by oxidation, or dopant transport through a later oxidation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Tuple, Union

from opentcad.geometry.formats import MeshField
from opentcad.plugins import step_handler

from .anneal import AnnealResult, FairAnnealResult
from .implant import ImplantResult
from opentcad.process.topography.recipe import Recipe


@dataclass
class DopingRecipeResult:
    """What apply_doping_recipe did, in order. Useful for the GUI's
    sidebar summary and for debugging a long multi-step recipe.

    ``implants`` and ``anneals`` hold the built-in results; ``steps``
    holds ``(step, result)`` for every doping-stage step in order,
    plugin steps included."""
    implants: List[ImplantResult] = field(default_factory=list)
    anneals: List[Union[AnnealResult, FairAnnealResult]] = field(default_factory=list)
    steps: List[Tuple[Any, Any]] = field(default_factory=list)

    @property
    def n_implants(self) -> int:
        return len(self.implants)

    @property
    def n_anneals(self) -> int:
        return len(self.anneals)


def apply_doping_recipe(mf: MeshField, recipe: Recipe) -> DopingRecipeResult:
    """Walk *recipe* and apply every doping step to *mf* in place.

    Topography-stage steps (deposit / etch / oxidize, or plugin steps
    registered as topography) are skipped — `simulate()` handled them
    upstream and they are already baked into the MeshField's geometry.
    Each doping-stage step runs through its registered handler
    (``opentcad.plugins``); an unregistered step type raises TypeError.

    Returns a `DopingRecipeResult` listing what fired, in order. An empty
    recipe or a topography-only recipe returns an empty result; the
    MeshField is untouched.
    """
    out = DopingRecipeResult()
    for step in recipe:
        handler = step_handler(step)
        if handler.stage != "doping":
            continue
        res = handler.apply(mf, step)
        out.steps.append((step, res))
        if isinstance(res, ImplantResult):
            out.implants.append(res)
        elif isinstance(res, (AnnealResult, FairAnnealResult)):
            out.anneals.append(res)
    return out
