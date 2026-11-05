"""
opentcad.process.doping.pearson_iv — Implant moment tables + Pearson profile.

Loads the per-species YAML tables under `data/` and returns the four
moments (Rp, ΔRp, γ, β) for a given (species, energy). Log-interpolates
in energy — implant range vs energy follows a nuclear-stopping-power law
that is very close to a power law across the ranges we tabulate, so
log-linear is accurate to well under 5 % between tabulated points.

`pearson_density` turns the four moments into the depth profile. It
solves the Pearson differential equation

    p'(y) / p(y) = -(a + y) / (b0 + b1·y + b2·y²),    y = depth - Rp

whose coefficients are fixed by (ΔRp, γ, β). This is the general Pearson
system, not only type IV: tabulated rows fall in types I, IV and VI
(e.g. boron above ~30 keV has β < 3 + 1.5γ², which is type I), and each
gets the unique Pearson curve with exactly those four moments. γ = 0,
β = 3 reduces to the Gaussian.

Molecular ions (BF₂) are mapped to their dopant atom at the atom's share
of the beam energy — see `resolve_implant_species`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import yaml

from opentcad.geometry.formats import Material


_DATA_DIR = Path(__file__).parent / "data"


# Species names OpenTCAD recognises. Uses lowercase full name as canonical.
# Add symbol aliases as we ship more species.
_ALIASES = {
    "boron":      "boron",
    "b":          "boron",
    "phosphorus": "phosphorus",
    "p":          "phosphorus",
    "arsenic":    "arsenic",
    "as":         "arsenic",
}


@dataclass(frozen=True)
class PearsonMoments:
    """The four moments of an implant depth distribution.

    Rp and dRp are in µm; γ and β are dimensionless. `dopant_kind` is
    'donor' or 'acceptor' — set from the YAML per species."""
    Rp_um: float
    dRp_um: float
    gamma: float
    beta: float
    dopant_kind: str      # 'donor' | 'acceptor'


@lru_cache(maxsize=None)
def _load_species(canonical_name: str) -> Dict:
    """Read a species YAML once, cache forever."""
    path = _DATA_DIR / f"{_symbol_for(canonical_name)}_in_Si.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"No implant table for species {canonical_name!r}: "
            f"looked at {path}. Ship a YAML there to add one.")
    with path.open("r") as fh:
        return yaml.safe_load(fh)


_SYMBOLS = {"boron": "B", "phosphorus": "P", "arsenic": "As"}


def _symbol_for(canonical_name: str) -> str:
    return _SYMBOLS[canonical_name]


def canonicalize_species(name: str) -> str:
    """Normalize a species name to the canonical lowercase form. Raises
    ValueError with a clear message if we don't ship data for it."""
    key = name.strip().lower()
    if key not in _ALIASES:
        raise ValueError(
            f"Unknown implant species {name!r}. Known: "
            f"{sorted(set(_ALIASES.values()))}")
    return _ALIASES[key]


def available_species() -> List[str]:
    return sorted(set(_ALIASES.values()))


def dopant_kind(species: str) -> str:
    """'donor' or 'acceptor' for an atomic dopant species."""
    return _load_species(canonicalize_species(species))["dopant_kind"]


# Molecular ions: canonical name → (dopant atom, atom's share of the beam
# energy). The molecule splits on impact and each atom carries energy in
# proportion to its mass: BF₂ (49.0 u) puts 11.0/49.0 ≈ 0.225 of E on B.
_MOLECULAR_IONS = {
    "bf2": ("boron", 11.009 / (11.009 + 2 * 18.998)),
}


def resolve_implant_species(name: str, energy_keV: float) -> Tuple[str, str, float]:
    """Map an implanted ion to (ion, dopant, dopant_energy_keV).

    Atomic species pass through unchanged. A molecular ion such as BF₂
    becomes its dopant atom at the mass-scaled energy. Co-implanted
    fluorine (and its effect on diffusion) is not modelled.
    """
    key = name.strip().lower().replace("₂", "2")
    if key in _MOLECULAR_IONS:
        dopant, frac = _MOLECULAR_IONS[key]
        return key, dopant, float(energy_keV) * frac
    canonical = canonicalize_species(name)
    return canonical, canonical, float(energy_keV)


def moments_for(species: str, energy_keV: float,
                target: Material = Material.SI) -> PearsonMoments:
    """Interpolate Pearson-IV moments for the given species and energy.

    Uses log-linear interpolation on energy (implant range vs. energy is
    close to a power law across our tabulated range, so log-interp is
    accurate to well under 5% between points).

    Extrapolation is refused — raise ValueError if energy falls outside
    the tabulated range for that species. We'd rather force the caller
    to add a data point than silently return nonsense.
    """
    if target != Material.SI:
        raise NotImplementedError(
            f"Only Si target supported today; asked for {target}. "
            "Ship additional YAMLs to extend.")
    canonical = canonicalize_species(species)
    table = _load_species(canonical)
    rows = sorted(table["moments"], key=lambda r: r["energy_keV"])
    energies = [r["energy_keV"] for r in rows]

    if not (energies[0] <= energy_keV <= energies[-1]):
        raise ValueError(
            f"Energy {energy_keV} keV outside tabulated range for "
            f"{canonical} in Si [{energies[0]} … {energies[-1]}] keV.")

    # find bracketing rows
    for i in range(len(rows) - 1):
        if energies[i] <= energy_keV <= energies[i + 1]:
            lo, hi = rows[i], rows[i + 1]
            break
    else:
        # exact endpoint match
        row = rows[-1] if energy_keV == energies[-1] else rows[0]
        return PearsonMoments(
            Rp_um=row["Rp_um"], dRp_um=row["dRp_um"],
            gamma=row["gamma"], beta=row["beta"],
            dopant_kind=table["dopant_kind"],
        )

    # log-linear interpolation
    import math
    t = ((math.log(energy_keV) - math.log(lo["energy_keV"])) /
         (math.log(hi["energy_keV"]) - math.log(lo["energy_keV"])))

    def _interp_log(key):
        return math.exp(math.log(lo[key]) + t * (math.log(hi[key]) - math.log(lo[key])))

    def _interp_lin(key):
        return lo[key] + t * (hi[key] - lo[key])

    return PearsonMoments(
        Rp_um=_interp_log("Rp_um"),
        dRp_um=_interp_log("dRp_um"),
        gamma=_interp_lin("gamma"),
        beta=_interp_lin("beta"),
        dopant_kind=table["dopant_kind"],
    )


@lru_cache(maxsize=256)
def _pearson_density_cached(Rp_um: float, dRp_um: float, gamma: float,
                            beta: float, n_samples: int):
    sigma = dRp_um
    if not sigma > 0:
        raise ValueError(f"dRp must be > 0 (got {dRp_um} µm)")
    if not beta > gamma * gamma + 1.0:
        raise ValueError(
            f"No distribution has kurtosis β={beta} with skewness γ={gamma} "
            f"(need β > γ² + 1).")
    A = 10.0 * beta - 12.0 * gamma * gamma - 18.0
    if not A > 0:
        raise ValueError(
            f"(γ={gamma}, β={beta}) lies outside the bell-shaped Pearson "
            f"region (10β - 12γ² - 18 must be > 0).")
    b0 = sigma * sigma * (4.0 * beta - 3.0 * gamma * gamma) / A
    b1 = sigma * gamma * (beta + 3.0) / A
    b2 = (2.0 * beta - 3.0 * gamma * gamma - 6.0) / A
    a = b1
    mode = -a

    # Support: ±12σ, cut at any real root of b0 + b1·y + b2·y² (types I/VI).
    lo, hi = -12.0 * sigma, 12.0 * sigma
    if abs(b2) > 1e-12:
        roots = np.roots([b2, b1, b0])
    elif abs(b1) > 1e-12:
        roots = np.array([-b0 / b1])
    else:
        roots = np.array([])
    for r in roots:
        if abs(r.imag) < 1e-12 * sigma:
            r = float(r.real)
            if r < mode:
                lo = max(lo, r)
            else:
                hi = min(hi, r)
    eps = 1e-9 * sigma
    y = np.linspace(lo + eps, hi - eps, n_samples)
    q = b0 + b1 * y + b2 * y * y
    integrand = -(a + y) / q
    # ln p by cumulative trapezoid, then normalise numerically.
    lnp = np.concatenate(([0.0], np.cumsum(
        0.5 * (integrand[1:] + integrand[:-1]) * np.diff(y))))
    p = np.exp(lnp - lnp.max())
    k = int(np.argmax(p))
    if k in (0, len(p) - 1):
        raise ValueError(
            f"(γ={gamma}, β={beta}) gives a J-shaped Pearson curve; not an "
            f"implant profile.")
    p /= np.trapezoid(p, y)
    depth = Rp_um + y
    depth.flags.writeable = False
    p.flags.writeable = False
    return depth, p


def pearson_density(moments: PearsonMoments, n_samples: int = 20001):
    """Sample the Pearson-system depth density for *moments*.

    Returns ``(depth_um, density_per_um)``: the curve has mean Rp,
    standard deviation ΔRp, skewness γ and kurtosis β, and integrates to
    1 over depth (including any part at negative depth — the caller
    decides what happens above the surface). Arrays are read-only and
    cached per moment set.
    """
    return _pearson_density_cached(float(moments.Rp_um), float(moments.dRp_um),
                                   float(moments.gamma), float(moments.beta),
                                   int(n_samples))
