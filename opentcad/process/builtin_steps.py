"""
opentcad.process.builtin_steps — registers the built-in recipe steps.

Deposit / Etch / Oxidize run on the level-set state (ViennaLS, imported
only when a step actually runs); Implant / Anneal run on the meshed
device. ``opentcad.plugins`` calls ``register()`` the first time a
registry is consulted.
"""
from __future__ import annotations

from opentcad.plugins import register_step
from opentcad.process.topography.recipe import (Anneal, Deposit, Etch,
                                                Implant, Oxidize)


def _window(step) -> str:
    if step.window_x_um is None:
        return ""
    x0, x1 = step.window_x_um
    return f" window=[{x0:.3f}..{x1:.3f}] um"


# ---- topography --------------------------------------------------------------
def _apply_deposit(state, step):
    from opentcad.process.topography.simulator import _apply_deposit
    _apply_deposit(state, step)


def _apply_etch(state, step):
    from opentcad.process.topography.simulator import _apply_etch
    _apply_etch(state, step)


def _apply_oxidize(state, step):
    from opentcad.process.topography.simulator import _apply_oxidize
    _apply_oxidize(state, step)


def _describe_deposit(step) -> str:
    return (f"deposit {step.thickness_um*1000:.1f} nm of "
            f"{step.material.name} ({step.model})")


def _describe_etch(step) -> str:
    bits = [_window(step)]
    if step.mask_material is not None:
        bits.append(f" mask={step.mask_material.name}")
    if step.rates is not None:
        rate_bits = ", ".join(f"{m.name}:{r:g}" for m, r in step.rates.items())
        bits.append(f" rates=[{rate_bits}]")
    return f"etch {step.depth_um*1000:.1f} nm ({step.model}){''.join(bits)}"


def _describe_oxidize(step) -> str:
    bits = [_window(step)]
    if step.bird_beak_length_um > 0:
        bits.append(f" bird_beak={step.bird_beak_length_um*1000:.0f} nm")
    return (f"oxidize @ {step.temperature_C:.0f}°C for {step.time_s:.0f} s "
            f"({step.ambient}){''.join(bits)}")


# ---- doping ------------------------------------------------------------------
def _apply_implant(mf, step):
    from opentcad.process.doping.implant import apply_implant
    return apply_implant(mf, species=step.species, energy_keV=step.energy_keV,
                         dose_cm2=step.dose_cm2, window_x_um=step.window_x_um,
                         tilt_deg=step.tilt_deg, profile=step.profile)


def _apply_anneal(mf, step):
    from opentcad.process.doping.anneal import apply_anneal, apply_anneal_fair
    kernel = apply_anneal_fair if step.model == "fair" else apply_anneal
    return kernel(mf, temperature_C=step.temperature_C, time_s=step.time_s,
                  species_Nd=step.species_Nd, species_Na=step.species_Na)


def _describe_implant(step) -> str:
    bits = [_window(step)]
    if step.tilt_deg:
        bits.append(f" tilt={step.tilt_deg:+.1f}°")
    if step.profile != "pearson":
        bits.append(f" profile={step.profile}")
    return (f"implant {step.species} @ {step.energy_keV:g} keV, "
            f"dose {step.dose_cm2:.1e} cm⁻²{''.join(bits)}")


def _describe_anneal(step) -> str:
    return (f"anneal @ {step.temperature_C:.0f}°C for {step.time_s:.0f} s "
            f"({step.model}; untracked Nd:{step.species_Nd}, "
            f"Na:{step.species_Na})")


def register() -> None:
    register_step(Deposit, stage="topography", apply=_apply_deposit,
                  describe=_describe_deposit)
    register_step(Etch, stage="topography", apply=_apply_etch,
                  describe=_describe_etch)
    register_step(Oxidize, stage="topography", apply=_apply_oxidize,
                  describe=_describe_oxidize)
    register_step(Implant, stage="doping", apply=_apply_implant,
                  describe=_describe_implant)
    register_step(Anneal, stage="doping", apply=_apply_anneal,
                  describe=_describe_anneal)
