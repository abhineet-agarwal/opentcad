"""
opentcad.process.doping.anneal — Thermal-anneal diffusion kernel.

Takes a MeshField with as-implanted doping (sharp Gaussians) and
smooths it per the intrinsic Fick's-law diffusivity of each species at
the anneal temperature for the specified time. The result is a
smoother Erf-like profile — the shape device solvers were designed to
equilibrate on.

Mathematical shortcut (Phase 2.3a):

  For intrinsic diffusion `∂C/∂t = D · ∇²C` on a semi-infinite domain
  with no-flux boundaries, the Green's function is a Gaussian with
  σ(t) = √(2 D t). The solution is the convolution of the initial
  profile with that Gaussian:

      C(x, y, t) = C(x, y, 0)  ∗  G(σ = √(2 D t))

  `scipy.ndimage.gaussian_filter` applied to a Cartesian resampling of
  Nd (or Na) does exactly this, in milliseconds. No PDE discretisation
  error — the Gaussian filter is the analytic solution.

Scope / limitations:

  * Intrinsic diffusivity only. The full Fair model has a
    concentration-dependent term `D(n, p) = D_i + D⁻·(n/n_i) + ...`
    that flattens the top of a heavily-doped profile and gives the
    classic phosphorus "kink and tail" shape. Those Arrhenius coefs
    sit in the YAML tables as placeholders for Phase 2.3b. For the
    `make the implanted Gaussian solver-friendly` story we're after
    today, intrinsic D is enough.
  * One species per dopant field. The MeshField's Nd field is treated
    as a single donor species (default: As); Na as a single acceptor
    (default: B). A mixed Nd field with both P and As diffusing at
    different rates would need a per-species decomposition we don't
    track yet.
  * No oxidation-enhanced diffusion (OED), no segregation across
    material interfaces, no out-diffusion to gas. All deferred.
  * No implant-damage-enhanced transient diffusion ("TED"). Real
    anneals of implanted profiles have a brief faster-than-equilibrium
    phase; this gives a conservative (underestimate) of lateral spread.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
import yaml

from opentcad.geometry.formats import Material, MeshField

from .pearson_iv import canonicalize_species


_K_BOLTZMANN_EV_PER_K = 8.617333262e-5
_DATA_DIR = Path(__file__).parent / "data"
_UM_TO_CM = 1e-4


@lru_cache(maxsize=None)
def _load_diffusion_yaml(canonical: str) -> dict:
    """Read the per-species diffusion YAML, cache forever."""
    sym = {"boron": "B", "phosphorus": "P", "arsenic": "As"}[canonical]
    path = _DATA_DIR / f"{sym}_diffusion.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"No diffusion table for {canonical!r}: looked at {path}")
    with path.open("r") as fh:
        return yaml.safe_load(fh)


def diffusivity_intrinsic(species: str, T_K: float,
                           target: Material = Material.SI) -> float:
    """Intrinsic Fick diffusivity D_i(T) in cm²/s per Arrhenius fit.

    Only the single-component intrinsic term is returned; concentration-
    dependent coefficients are deferred to Phase 2.3b.

    Args:
        species: 'B' / 'boron' / 'P' / 'phosphorus' / 'As' / 'arsenic'.
        T_K: anneal temperature in Kelvin.
        target: substrate material. Only Si has tables today.
    """
    if target != Material.SI:
        raise NotImplementedError(
            f"Only Si target supported today; asked for {target}.")
    if T_K <= 0:
        raise ValueError(f"temperature must be > 0 K; got {T_K}")
    canonical = canonicalize_species(species)
    table = _load_diffusion_yaml(canonical)
    D0 = float(table["intrinsic"]["D0_cm2s"])
    Ea = float(table["intrinsic"]["Ea_eV"])
    return D0 * math.exp(-Ea / (_K_BOLTZMANN_EV_PER_K * T_K))


def _arrhenius(block: dict, T_K: float) -> float:
    """D0 * exp(-Ea/kT) from a {D0_cm2s, Ea_eV} YAML dict."""
    D0 = float(block["D0_cm2s"])
    Ea = float(block["Ea_eV"])
    return D0 * math.exp(-Ea / (_K_BOLTZMANN_EV_PER_K * T_K))


def fair_diffusivity_components(species: str, T_K: float
                                 ) -> dict:
    """Load intrinsic + Fair concentration-dependent components at T.

    Returns a dict with keys ``D_i`` and whichever of
    ``D_minus``, ``D_minus_minus``, ``D_plus``, ``D_plus_plus``
    appear in the species' YAML. All values in cm²/s.
    """
    canonical = canonicalize_species(species)
    table = _load_diffusion_yaml(canonical)
    out = {"D_i": _arrhenius(table["intrinsic"], T_K)}
    fair = table.get("fair", {}) or {}
    for key in ("D_minus", "D_minus_minus", "D_plus", "D_plus_plus"):
        if key in fair:
            out[key] = _arrhenius(fair[key], T_K)
    return out


def _intrinsic_carrier_density_cm3(T_K: float) -> float:
    """Silicon n_i(T) via the standard temperature-dependent expression
    used for Fair diffusion (Plummer 1.4.13):

        n_i(T) = 3.1e16 · T^1.5 · exp(-0.603 eV / kT)

    Valid 300 - 1500 K. At 1000 °C (1273 K): ~5e18 cm^-3 — the
    Fair-regime crossover for dopant D(n/n_i) saturates for
    doping below this.
    """
    return 3.1e16 * (T_K ** 1.5) * math.exp(
        -0.603 / (_K_BOLTZMANN_EV_PER_K * T_K))


def temperature_celsius_to_kelvin(T_C: float) -> float:
    return T_C + 273.15


@dataclass(frozen=True)
class AnnealResult:
    """Diagnostic record returned alongside the in-place mutation.

    `sigma_Nd_um` and `sigma_Na_um` are the Gaussian σ(t) = √(2 D t)
    actually applied to the donor and acceptor fields in µm — the one-
    number summary of how much the anneal blurred each profile.
    """
    temperature_C: float
    time_s: float
    species_Nd: str
    species_Na: str
    D_Nd_cm2_s: float
    D_Na_cm2_s: float
    sigma_Nd_um: float
    sigma_Na_um: float
    grid_cell_um: float


def _resample_mesh_to_grid(points_um: np.ndarray,
                            values: np.ndarray,
                            xmin: float, xmax: float,
                            ymin: float, ymax: float,
                            dx_um: float) -> tuple[np.ndarray,
                                                   np.ndarray, np.ndarray]:
    """Linear-interpolate a per-node field onto a Cartesian grid.

    Returns (xs, ys, grid_values) with grid_values shape (ny, nx) so
    numpy / scipy image conventions (first axis = y, second = x) work
    directly with gaussian_filter.
    """
    from scipy.interpolate import griddata

    nx = max(2, int(math.ceil((xmax - xmin) / dx_um)) + 1)
    ny = max(2, int(math.ceil((ymax - ymin) / dx_um)) + 1)
    xs = np.linspace(xmin, xmax, nx)
    ys = np.linspace(ymin, ymax, ny)
    xg, yg = np.meshgrid(xs, ys)
    grid_vals = griddata(points_um, values, (xg, yg),
                          method="linear", fill_value=0.0)
    # Any NaN (points outside the convex hull of mesh nodes) → 0.
    grid_vals = np.nan_to_num(grid_vals, nan=0.0)
    return xs, ys, grid_vals


def _resample_grid_to_mesh(xs: np.ndarray, ys: np.ndarray,
                            grid_values: np.ndarray,
                            points_um: np.ndarray) -> np.ndarray:
    """Interpolate a Cartesian grid back to mesh-node locations."""
    from scipy.interpolate import RegularGridInterpolator
    interp = RegularGridInterpolator(
        (ys, xs), grid_values, bounds_error=False, fill_value=0.0,
        method="linear")
    # points_um is (N, 2) in (x, y); interpolator wants (y, x).
    return interp(np.column_stack([points_um[:, 1], points_um[:, 0]]))


def apply_anneal(mf: MeshField,
                 temperature_C: float,
                 time_s: float,
                 *,
                 species_Nd: str = "As",
                 species_Na: str = "B",
                 grid_resolution_um: float = 0.005,
                 ) -> AnnealResult:
    """Diffuse the Nd and Na fields in place per intrinsic Fick's law.

    Each field is resampled onto a Cartesian grid, convolved with a
    Gaussian of σ = √(2 D t), and resampled back to the mesh. Mutates
    the MeshField in place; returns an AnnealResult diagnostic.

    Args:
        mf: MeshField with doping to anneal. Nd and Na in cm⁻³.
        temperature_C: anneal temperature in °C.
        time_s: anneal duration in seconds.
        species_Nd: dopant species the Nd field represents. Default
            "As" — modern CMOS n+ S/D. Set to "P" for phosphorus flows.
        species_Na: dopant species the Na field represents. Default
            "B".
        grid_resolution_um: Cartesian-grid cell size for the convolution.
            Should resolve both the mesh and the Gaussian kernel —
            default 5 nm matches the ViennaLS grid.

    Returns:
        AnnealResult with the diffusivities and σ actually applied.
    """
    from scipy.ndimage import gaussian_filter

    if time_s < 0:
        raise ValueError(f"time must be ≥ 0 (got {time_s} s)")
    if temperature_C <= -273.15:
        raise ValueError(
            f"temperature must be above absolute zero (got {temperature_C}°C)")

    T_K = temperature_celsius_to_kelvin(temperature_C)
    D_Nd = diffusivity_intrinsic(species_Nd, T_K)
    D_Na = diffusivity_intrinsic(species_Na, T_K)

    # σ = √(2 D t), with D in cm²/s and t in s → σ in cm. Convert to µm
    # for the grid-cell scale.
    sigma_Nd_cm = math.sqrt(2.0 * D_Nd * time_s)
    sigma_Na_cm = math.sqrt(2.0 * D_Na * time_s)
    sigma_Nd_um = sigma_Nd_cm / _UM_TO_CM
    sigma_Na_um = sigma_Na_cm / _UM_TO_CM

    # Nothing to do if σ << grid cell — the convolution would be
    # numerically identical to the identity.
    xmin_mf, xmax_mf, ymin_mf, ymax_mf = mf.bounds[:4]
    pts = np.asarray(mf.grid.points, dtype=float)[:, :2]
    nd = np.asarray(mf.Nd, dtype=float)
    na = np.asarray(mf.Na, dtype=float)

    # Only convolve if σ exceeds some fraction of the grid cell, else
    # it's wasted work (and no-ops are fine — the identity convolution
    # is still itself).
    def _diffuse(field: np.ndarray, sigma_um: float) -> np.ndarray:
        if float(np.max(field)) <= 0.0 or sigma_um <= 0.1 * grid_resolution_um:
            return field
        xs, ys, grid_vals = _resample_mesh_to_grid(
            pts, field, xmin_mf, xmax_mf, ymin_mf, ymax_mf,
            grid_resolution_um)
        sigma_px = sigma_um / grid_resolution_um
        # mode='reflect' = no-flux (zero normal gradient) at boundaries.
        smoothed = gaussian_filter(grid_vals, sigma=sigma_px, mode="reflect")
        return _resample_grid_to_mesh(xs, ys, smoothed, pts)

    new_nd = _diffuse(nd, sigma_Nd_um)
    new_na = _diffuse(na, sigma_Na_um)

    # Writing through the MeshField properties validates shape + non-
    # negativity (the Gaussian convolution can give tiny negatives at
    # interpolation seams; clip to zero).
    mf.Nd = np.clip(new_nd, 0.0, None)
    mf.Na = np.clip(new_na, 0.0, None)

    return AnnealResult(
        temperature_C=float(temperature_C),
        time_s=float(time_s),
        species_Nd=canonicalize_species(species_Nd),
        species_Na=canonicalize_species(species_Na),
        D_Nd_cm2_s=float(D_Nd),
        D_Na_cm2_s=float(D_Na),
        sigma_Nd_um=float(sigma_Nd_um),
        sigma_Na_um=float(sigma_Na_um),
        grid_cell_um=float(grid_resolution_um),
    )


@dataclass(frozen=True)
class FairAnnealResult:
    """Diagnostic record for a concentration-coupled Fair anneal.

    Captures the peak effective diffusivity actually used for each
    species at the hottest, most doped grid cell — the single-number
    summary of how much concentration enhancement mattered.
    """
    temperature_C: float
    time_s: float
    species_Nd: str
    species_Na: str
    n_sub_steps: int
    dt_sub_mean_s: float
    D_i_Nd_cm2_s: float
    D_eff_Nd_peak_cm2_s: float
    D_i_Na_cm2_s: float
    D_eff_Na_peak_cm2_s: float
    grid_cell_um: float


def _fair_D_eff_field(coefs: dict, charge_field: np.ndarray,
                       n_i_T: float) -> np.ndarray:
    """D_eff(x,y) = D_i + Σ D_k · (u^k) where u = max(charge, n_i) / n_i.

    `charge_field` is n (electron density ≈ Nd for n-type regions) or
    p (≈ Na for p-type). Floored at n_i so intrinsic regions see the
    flat D_i and nothing blows up. All [cm^-3] / [cm²/s] units.
    """
    u = np.maximum(charge_field, n_i_T) / n_i_T
    D = np.full_like(u, coefs["D_i"], dtype=float)
    if "D_minus" in coefs:
        D += coefs["D_minus"] * u
    if "D_minus_minus" in coefs:
        D += coefs["D_minus_minus"] * (u * u)
    if "D_plus" in coefs:
        D += coefs["D_plus"] * u
    if "D_plus_plus" in coefs:
        D += coefs["D_plus_plus"] * (u * u)
    return D


def _ftcs_step(C: np.ndarray, D: np.ndarray,
                dx_cm: float, dt_s: float) -> np.ndarray:
    """One explicit FTCS step of ∂C/∂t = ∇·(D ∇C) on a Cartesian grid.

    Uses second-order central differences with D averaged to cell faces
    (harmonic mean). Neumann (reflective) boundaries: no-flux at edges.

    Shape (ny, nx) in (y, x) order per the resample convention.
    """
    # Face-centered diffusivities: D_{i+1/2} = 2·D_i·D_{i+1} / (D_i + D_{i+1})
    # Harmonic average is the standard choice for conductivity-style
    # discretisations because it recovers the exact flux across a jump
    # (unlike arithmetic which overpredicts).
    Dx_face = 2.0 * D[:, :-1] * D[:, 1:] / np.maximum(
        D[:, :-1] + D[:, 1:], 1e-30)
    Dy_face = 2.0 * D[:-1, :] * D[1:, :] / np.maximum(
        D[:-1, :] + D[1:, :], 1e-30)

    # Fluxes through x-faces = D · (C[i+1] - C[i]) / dx, and same y.
    Fx = Dx_face * (C[:, 1:] - C[:, :-1]) / dx_cm       # (ny, nx-1)
    Fy = Dy_face * (C[1:, :] - C[:-1, :]) / dx_cm       # (ny-1, nx)

    # Divergence at each cell: (F_{i+1/2} - F_{i-1/2}) / dx  (Neumann:
    # no flux across domain edges, so pad with zero flux on both sides).
    dCdt = np.zeros_like(C)
    dCdt[:, 1:-1] += (Fx[:, 1:] - Fx[:, :-1]) / dx_cm
    dCdt[:, 0]    += Fx[:, 0]  / dx_cm
    dCdt[:, -1]   -= Fx[:, -1] / dx_cm
    dCdt[1:-1, :] += (Fy[1:, :] - Fy[:-1, :]) / dx_cm
    dCdt[0, :]    += Fy[0, :]  / dx_cm
    dCdt[-1, :]   -= Fy[-1, :] / dx_cm

    return C + dt_s * dCdt


def apply_anneal_fair(mf: MeshField,
                      temperature_C: float,
                      time_s: float,
                      *,
                      species_Nd: str = "P",
                      species_Na: str = "B",
                      grid_resolution_um: float = 0.01,
                      stability_factor: float = 0.4,
                      max_sub_steps: int = 200_000,
                      ) -> FairAnnealResult:
    """Concentration-coupled Fair anneal via explicit FTCS sub-stepping.

    Unlike :func:`apply_anneal` — which does a single Gaussian convolution
    (correct only for intrinsic constant-D diffusion) — this routine
    integrates ∂C/∂t = ∇·(D_eff(C)·∇C) explicitly, with D_eff rebuilt
    each step from the current doping field and the Fair series:

        D_eff = D_i + D⁻·(n/n_i) + D⁻⁻·(n/n_i)²                (donors)
        D_eff = D_i + D⁺·(p/n_i) + D⁺⁺·(p/n_i)²                (acceptors)

    This reproduces the phosphorus "kink-and-tail" profile (D⁻⁻
    dominates at n ≫ n_i) and arsenic's much smaller concentration
    enhancement. Coefficients come from each species' YAML
    (``opentcad/process/doping/data/{P,As,B}_diffusion.yaml``).

    Numerical details:
      * Explicit Euler on a Cartesian grid, Neumann (no-flux) walls.
      * Harmonic-mean D at cell faces — preserves flux across sharp
        concentration gradients where D jumps by orders of magnitude.
      * Sub-step size dt_sub = ``stability_factor`` · dx² / max(D_eff)
        (von Neumann limit for the 2D heat equation is 0.25; 0.4 is
        stable with the harmonic-mean coefficient scheme). D_eff is
        re-evaluated each sub-step, so dt_sub shrinks naturally as the
        profile heats up or spreads.
      * Capped at ``max_sub_steps`` iterations as a runaway guard.

    Mutates the MeshField's Nd and Na fields in place. Use
    :func:`apply_anneal` instead when the profile stays well below
    n_i at the anneal temperature — intrinsic Gaussian is exact there
    and much cheaper.
    """
    from scipy.ndimage import gaussian_filter  # noqa: F401 (keep peer)

    if time_s < 0:
        raise ValueError(f"time must be ≥ 0 (got {time_s} s)")
    if temperature_C <= -273.15:
        raise ValueError(
            f"temperature must be above absolute zero (got {temperature_C}°C)")
    if not 0.0 < stability_factor < 0.5:
        raise ValueError(
            f"stability_factor must lie in (0, 0.5); got {stability_factor}")

    T_K = temperature_celsius_to_kelvin(temperature_C)
    n_i_T = _intrinsic_carrier_density_cm3(T_K)
    coefs_Nd = fair_diffusivity_components(species_Nd, T_K)
    coefs_Na = fair_diffusivity_components(species_Na, T_K)

    xmin, xmax, ymin, ymax = mf.bounds[:4]
    pts = np.asarray(mf.grid.points, dtype=float)[:, :2]
    nd_init = np.asarray(mf.Nd, dtype=float)
    na_init = np.asarray(mf.Na, dtype=float)

    xs, ys, Nd_grid = _resample_mesh_to_grid(
        pts, nd_init, xmin, xmax, ymin, ymax, grid_resolution_um)
    _, _, Na_grid = _resample_mesh_to_grid(
        pts, na_init, xmin, xmax, ymin, ymax, grid_resolution_um)

    dx_cm = grid_resolution_um * _UM_TO_CM
    D_peak_Nd = 0.0
    D_peak_Na = 0.0
    dt_sum = 0.0
    n_steps = 0
    t_left = float(time_s)

    while t_left > 0.0 and n_steps < max_sub_steps:
        D_Nd = _fair_D_eff_field(coefs_Nd, Nd_grid, n_i_T)
        D_Na = _fair_D_eff_field(coefs_Na, Na_grid, n_i_T)
        D_max = max(float(np.max(D_Nd)), float(np.max(D_Na)))
        if D_max <= 0.0:
            break
        dt_sub = stability_factor * (dx_cm * dx_cm) / D_max
        dt_sub = min(dt_sub, t_left)
        Nd_grid = _ftcs_step(Nd_grid, D_Nd, dx_cm, dt_sub)
        Na_grid = _ftcs_step(Na_grid, D_Na, dx_cm, dt_sub)
        D_peak_Nd = max(D_peak_Nd, float(np.max(D_Nd)))
        D_peak_Na = max(D_peak_Na, float(np.max(D_Na)))
        t_left -= dt_sub
        dt_sum += dt_sub
        n_steps += 1

    if t_left > 1e-12 * time_s:
        raise RuntimeError(
            f"max_sub_steps ({max_sub_steps}) hit with {t_left:.2e} s "
            f"of anneal time left. Increase max_sub_steps, coarsen "
            f"grid_resolution_um, or use apply_anneal (intrinsic) "
            f"instead for this condition.")

    # Grid → mesh. Clip tiny negatives from interpolation seams.
    new_nd = _resample_grid_to_mesh(xs, ys, Nd_grid, pts)
    new_na = _resample_grid_to_mesh(xs, ys, Na_grid, pts)
    mf.Nd = np.clip(new_nd, 0.0, None)
    mf.Na = np.clip(new_na, 0.0, None)

    return FairAnnealResult(
        temperature_C=float(temperature_C),
        time_s=float(time_s),
        species_Nd=canonicalize_species(species_Nd),
        species_Na=canonicalize_species(species_Na),
        n_sub_steps=int(n_steps),
        dt_sub_mean_s=float(dt_sum / max(n_steps, 1)),
        D_i_Nd_cm2_s=float(coefs_Nd["D_i"]),
        D_eff_Nd_peak_cm2_s=float(D_peak_Nd),
        D_i_Na_cm2_s=float(coefs_Na["D_i"]),
        D_eff_Na_peak_cm2_s=float(D_peak_Na),
        grid_cell_um=float(grid_resolution_um),
    )
