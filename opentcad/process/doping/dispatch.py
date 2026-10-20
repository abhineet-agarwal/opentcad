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
Topography steps are *not* interleaved with doping here — in Phase 2.1
we defer every implant to after the mesh exists. That's fine for the
NMOS flow (all topography is done before S/D implant) but doesn't
model well implants or dopant transport through subsequent oxidation.
Those are Phase 2.3+ concerns, documented in KNOWN_ISSUES.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from opentcad.geometry.formats import MeshField

from .implant import ImplantResult, apply_implant
from opentcad.process.topography.recipe import Implant, Recipe


@dataclass
class DopingRecipeResult:
    """What apply_doping_recipe did, in order. Useful for the GUI's
    sidebar summary and for debugging a long multi-step recipe."""
    implants: List[ImplantResult] = field(default_factory=list)

    @property
    def n_implants(self) -> int:
        return len(self.implants)


def apply_doping_recipe(mf: MeshField, recipe: Recipe) -> DopingRecipeResult:
    """Walk *recipe* and apply every doping step to *mf* in place.

    Topography steps (deposit / etch / oxidize) are silently skipped —
    they were handled upstream by `simulate()` and are already baked
    into the MeshField's geometry.

    Returns a `DopingRecipeResult` listing every implant that fired,
    in order, with the Pearson moments and effective dose each one saw.
    An empty recipe or a topography-only recipe returns an empty
    result; the MeshField is untouched.
    """
    out = DopingRecipeResult()
    for step in recipe:
        if isinstance(step, Implant):
            res = apply_implant(
                mf,
                species=step.species,
                energy_keV=step.energy_keV,
                dose_cm2=step.dose_cm2,
                window_x_um=step.window_x_um,
                tilt_deg=step.tilt_deg,
            )
            out.implants.append(res)
        # All other step types are topography-side; already consumed
        # by simulate() and have nothing to do with the doping field.
    return out
