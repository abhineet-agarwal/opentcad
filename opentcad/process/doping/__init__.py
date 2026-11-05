"""
opentcad.process.doping — Dopant simulation (Phase 2).

Implant (Pearson-system depth profile matched to tabulated moments,
Gaussian lateral straggle, tilt, per-column surface, BF₂) and anneal
(intrinsic Gaussian convolution or concentration-coupled Fair). Each
implanted species is tracked in its own ``C_<species>`` MeshField field
and diffuses with its own coefficients; Nd / Na stay the totals.

Public surface:
    apply_implant                  — implant kernel, in-place on a MeshField
    apply_anneal                   — intrinsic anneal
    apply_anneal_fair              — Fair concentration-coupled anneal
    apply_doping_recipe            — play a Recipe's implant/anneal steps
    moments_for                    — moment-table lookup (Rp, ΔRp, γ, β)
    pearson_density                — depth density matched to those moments
    canonicalize_species           — normalise 'B'/'boron'/'Boron' → 'boron'
    available_species              — dopant species we ship data for
    surface_height_function        — y_surface(x) of a meshed stack
"""
from .anneal import (
    AnnealResult, FairAnnealResult, apply_anneal, apply_anneal_fair,
    diffusivity_intrinsic,
)
from .dispatch import DopingRecipeResult, apply_doping_recipe
from .implant import ImplantResult, apply_implant, surface_height_function
from .pearson_iv import (
    PearsonMoments,
    available_species,
    canonicalize_species,
    dopant_kind,
    moments_for,
    pearson_density,
    resolve_implant_species,
)

__all__ = [
    "apply_implant",
    "apply_anneal",
    "apply_anneal_fair",
    "apply_doping_recipe",
    "ImplantResult",
    "AnnealResult",
    "FairAnnealResult",
    "DopingRecipeResult",
    "moments_for",
    "pearson_density",
    "diffusivity_intrinsic",
    "PearsonMoments",
    "canonicalize_species",
    "available_species",
    "dopant_kind",
    "resolve_implant_species",
    "surface_height_function",
]
