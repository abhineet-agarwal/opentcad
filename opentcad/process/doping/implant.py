"""
opentcad.process.doping.implant — Analytic ion-implant kernel.

Takes a MeshField with populated geometry (material_id per cell) and
*adds* an ion-implant profile to it: to the per-species field
``C_<dopant>`` and to the donor / acceptor total (Nd or Na) the device
solver reads.

Physics:

  * Range distribution along the beam is the Pearson curve matched to
    the tabulated (Rp, ΔRp, γ, β) — see `pearson_iv.pearson_density`.
    ``profile="gaussian"`` keeps only (Rp, ΔRp).

  * Lateral (transverse) straggle is a Gaussian of width
    σ_lat = ``sigma_lat_frac`` · ΔRp (0.7 by default, a first-order
    literature value; the true ratio depends weakly on species/energy).

  * Each ion enters the surface at x_s inside the mask window, travels a
    distance s along the beam and t across it. For a beam tilted by θ
    from the vertical (positive θ leans toward +x with depth), the
    concentration at a node is

        C(x, d) = (Φ / cos θ) ∫ f((d + t·sin θ)/cos θ) · g(t) dt

    over the t-range whose entry points x_s = x - d·tan θ - t/cos θ lie
    in the window. At θ = 0 this factorises into f(d) times the familiar
    erf mask-edge blur. Dose per unit wafer area is conserved for any θ.
    Channeling is not modelled (amorphous target), so a 7° tilt only
    changes geometry here.

  * Depth d is measured from the local top surface of the meshed stack,
    found per column from the mesh's top boundary. For a tilted beam the
    surface is sampled at the beam's entry column. Material above the Si
    (e.g. a screen oxide) is traversed with the Si range tables; no
    separate SiO₂ stopping data is shipped.

  * Molecular ions (BF₂) become their dopant atom at the mass-scaled
    energy. Donors (P, As) add to Nd, acceptors (B) to Na; repeated
    implants accumulate and nothing is clipped.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

import numpy as np

from opentcad.geometry.formats import Material, MeshField

from .pearson_iv import (
    PearsonMoments, dopant_kind, moments_for, pearson_density,
    resolve_implant_species,
)


#: µm → cm conversion for the DEVSIM side of the house.
_UM_TO_CM = 1e-4

_PROFILES = ("pearson", "gaussian")
_GL_NODES, _GL_WEIGHTS = np.polynomial.legendre.leggauss(64)


@dataclass(frozen=True)
class ImplantResult:
    """Diagnostic summary returned alongside the in-place mutation.

    `species` is the dopant atom written to the mesh; `ion` is what was
    implanted (they differ for BF₂). `moments` are looked up at
    `dopant_energy_keV`."""
    species: str
    energy_keV: float
    dose_cm2: float
    moments: PearsonMoments
    sigma_lat_um: float
    window_x_um: Optional[Tuple[float, float]]
    added_to: str                       # "Nd" or "Na"
    integrated_added_per_unit_width: float   # cm⁻¹ (dose · window width in cm)
    ion: str = ""
    dopant_energy_keV: float = 0.0
    profile: str = "pearson"
    tilt_deg: float = 0.0


def surface_height_function(mf: MeshField) -> Callable[[np.ndarray], np.ndarray]:
    """Return y_surface(x) [µm]: the top of the meshed stack at each x.

    Built from the mesh's boundary edges: on every interval between
    boundary-vertex x positions the topmost non-vertical edge is the
    surface, so steps and trench floors are exact. Falls back to a flat
    max(y) surface for non-triangle meshes.
    """
    pts = np.asarray(mf.grid.points, dtype=float)[:, :2]
    import pyvista as pv
    if not np.all(np.asarray(mf.grid.celltypes) == pv.CellType.TRIANGLE):
        y_top = float(pts[:, 1].max())
        return lambda x: np.full(np.shape(x), y_top)

    tri = np.asarray(mf.grid.cells).reshape(-1, 4)[:, 1:]
    edges = np.sort(np.concatenate(
        [tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]]), axis=1)
    uniq, counts = np.unique(edges, axis=0, return_counts=True)
    bnd = uniq[counts == 1]
    xa, ya = pts[bnd[:, 0], 0].copy(), pts[bnd[:, 0], 1].copy()
    xb, yb = pts[bnd[:, 1], 0].copy(), pts[bnd[:, 1], 1].copy()
    swap = xa > xb
    xa[swap], xb[swap] = xb[swap], xa[swap].copy()
    ya[swap], yb[swap] = yb[swap], ya[swap].copy()
    keep = (xb - xa) > 1e-12
    xa, ya, xb, yb = xa[keep], ya[keep], xb[keep], yb[keep]
    slope = (yb - ya) / (xb - xa)

    bx = np.unique(np.concatenate([xa, xb]))
    mid = 0.5 * (bx[:-1] + bx[1:])
    top = np.empty(len(mid), dtype=int)
    for i0 in range(0, len(mid), 256):
        m = mid[i0:i0 + 256, None]
        y_at = ya[None, :] + (m - xa[None, :]) * slope[None, :]
        y_at = np.where((xa[None, :] <= m) & (xb[None, :] >= m), y_at, -np.inf)
        top[i0:i0 + 256] = np.argmax(y_at, axis=1)

    def y_surface(x):
        xq = np.clip(np.asarray(x, dtype=float), bx[0], bx[-1])
        k = np.clip(np.searchsorted(bx, xq, side="right") - 1, 0, len(mid) - 1)
        e = top[k]
        return ya[e] + (xq - xa[e]) * slope[e]

    return y_surface


def _range_density_per_cm(moments: PearsonMoments, profile: str):
    """Return f(s_um) → density per cm along the beam."""
    if profile == "gaussian":
        Rp, dRp = moments.Rp_um, moments.dRp_um
        norm = 1.0 / (math.sqrt(2.0 * math.pi) * dRp * _UM_TO_CM)
        return lambda s: norm * np.exp(-0.5 * ((s - Rp) / dRp) ** 2)
    depth, dens_per_um = pearson_density(moments)
    dens_per_cm = dens_per_um / _UM_TO_CM
    return lambda s: np.interp(s, depth, dens_per_cm, left=0.0, right=0.0)


def apply_implant(mf: MeshField,
                  species: str,
                  energy_keV: float,
                  dose_cm2: float,
                  window_x_um: Optional[Tuple[float, float]] = None,
                  *,
                  target: Material = Material.SI,
                  sigma_lat_frac: float = 0.7,
                  tilt_deg: float = 0.0,
                  profile: str = "pearson",
                  ) -> ImplantResult:
    """Apply an ion implant to *mf* in place; return a diagnostic record.

    Args:
        mf: MeshField to dope. Mutated in place — the ``C_<dopant>``
            species field and Nd or Na get the implant contribution added.
        species: "boron" / "B" / "phosphorus" / "P" / "arsenic" / "As" /
            "BF2" (case-insensitive).
        energy_keV: ion energy in keV. The dopant energy (for BF₂, about
            0.225 × this) must lie in the tabulated range — the moment
            lookup refuses to extrapolate.
        dose_cm2: dose per unit wafer area in cm⁻². Typical S/D implants
            are 1e14-1e16 cm⁻².
        window_x_um: optional (x0, x1) mask opening in µm, measured at
            the surface. None is a blanket implant.
        target: substrate material the tables apply to. Only Si is
            tabulated today.
        sigma_lat_frac: σ_lat as a fraction of ΔRp. Default 0.7.
        tilt_deg: beam tilt from the wafer normal in the cross-section
            plane, |tilt| < 89°. Positive leans toward +x with depth.
        profile: "pearson" (default; all four moments) or "gaussian"
            (Rp and ΔRp only).

    Returns:
        ImplantResult diagnostic record.
    """
    if dose_cm2 <= 0:
        raise ValueError(f"dose must be positive (got {dose_cm2} cm⁻²)")
    if profile not in _PROFILES:
        raise ValueError(f"profile must be one of {_PROFILES}; got {profile!r}")
    if not abs(tilt_deg) < 89.0:
        raise ValueError(f"|tilt_deg| must be < 89°; got {tilt_deg}")
    if window_x_um is not None and not (window_x_um[1] > window_x_um[0]):
        raise ValueError(
            f"window_x_um must be (x0, x1) with x1 > x0; got {window_x_um!r}")

    ion, dopant, dopant_energy = resolve_implant_species(species, energy_keV)
    try:
        moments = moments_for(dopant, dopant_energy, target=target)
    except ValueError as e:
        if ion != dopant:
            raise ValueError(
                f"{ion.upper()} at {energy_keV} keV puts {dopant_energy:.3g} keV "
                f"on {dopant}: {e}") from e
        raise
    sigma_lat_um = float(sigma_lat_frac) * moments.dRp_um
    f = _range_density_per_cm(moments, profile)

    pts_um = np.asarray(mf.grid.points, dtype=float)[:, :2]
    xs_um = pts_um[:, 0]
    ys_um = pts_um[:, 1]
    surface = surface_height_function(mf)

    theta = math.radians(float(tilt_deg))
    tan_t, sin_t, cos_t = math.tan(theta), math.sin(theta), math.cos(theta)
    depth_um = surface(xs_um) - ys_um
    if theta != 0.0:
        # Re-sample the surface where the beam through this node entered.
        depth_um = surface(xs_um - np.clip(depth_um, 0.0, None) * tan_t) - ys_um
    below = depth_um >= -1e-9
    depth_um = np.clip(depth_um, 0.0, None)

    contribution = np.zeros(mf.n_points)
    if theta == 0.0:
        vertical = f(depth_um)
        if window_x_um is None:
            local_dose = np.full_like(xs_um, float(dose_cm2))
        else:
            from scipy.special import erf
            x0, x1 = window_x_um
            r2s = math.sqrt(2.0) * sigma_lat_um
            local_dose = float(dose_cm2) * 0.5 * (
                erf((x1 - xs_um) / r2s) - erf((x0 - xs_um) / r2s))
        contribution = vertical * local_dose
    else:
        tmax = 8.0 * sigma_lat_um
        x_beam = xs_um - depth_um * tan_t
        t_lo = np.full_like(xs_um, -tmax)
        t_hi = np.full_like(xs_um, tmax)
        if window_x_um is not None:
            x0, x1 = window_x_um
            t_lo = np.maximum(t_lo, (x_beam - x1) * cos_t)
            t_hi = np.minimum(t_hi, (x_beam - x0) * cos_t)
        g_norm = 1.0 / (math.sqrt(2.0 * math.pi) * sigma_lat_um)
        for i0 in range(0, mf.n_points, 20000):
            sl = slice(i0, i0 + 20000)
            lo, hi = t_lo[sl], t_hi[sl]
            half = np.clip(0.5 * (hi - lo), 0.0, None)
            t = 0.5 * (hi + lo)[:, None] + half[:, None] * _GL_NODES[None, :]
            s = (depth_um[sl, None] + t * sin_t) / cos_t
            g = g_norm * np.exp(-0.5 * (t / sigma_lat_um) ** 2)
            integral = (f(s) * g) @ _GL_WEIGHTS * half
            contribution[sl] = float(dose_cm2) / cos_t * integral
    contribution = np.where(below, contribution, 0.0)

    mf.set_species(dopant, mf.get_species(dopant) + contribution)
    if dopant_kind(dopant) == "donor":
        mf.Nd = mf.Nd + contribution
        added_to = "Nd"
    else:
        mf.Na = mf.Na + contribution
        added_to = "Na"

    window_width_cm = (
        (window_x_um[1] - window_x_um[0]) * _UM_TO_CM
        if window_x_um is not None
        else (float(xs_um.max()) - float(xs_um.min())) * _UM_TO_CM
    )
    integrated = float(dose_cm2) * window_width_cm

    return ImplantResult(
        species=dopant,
        energy_keV=float(energy_keV),
        dose_cm2=float(dose_cm2),
        moments=moments,
        sigma_lat_um=sigma_lat_um,
        window_x_um=window_x_um,
        added_to=added_to,
        integrated_added_per_unit_width=integrated,
        ion=ion,
        dopant_energy_keV=float(dopant_energy),
        profile=profile,
        tilt_deg=float(tilt_deg),
    )
