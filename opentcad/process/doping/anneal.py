"""
opentcad.process.doping.anneal — Thermal-anneal diffusion kernels.

Two models, both acting on a MeshField in place:

  * `apply_anneal` — intrinsic Fick diffusion, ∂C/∂t = D_i ∇²C. On a
    domain with no-flux walls the solution is the initial profile
    convolved with a Gaussian of σ = √(2 D_i t), done by
    `scipy.ndimage.gaussian_filter` on a Cartesian resampling. Exact
    while the profile stays below n_i(T).
  * `apply_anneal_fair` — Fair concentration-coupled diffusion,
    D_eff = D_i + D⁻·(n/n_i) + D⁻⁻·(n/n_i)² (donors; D⁺, D⁺⁺ with p/n_i
    for acceptors), stepped explicitly. Needed at S/D-level doping.

Species: every tracked dopant field ``C_<species>`` on the MeshField
(written by `apply_implant`) diffuses with its own coefficients, so P
and As in the same Nd total spread at their own rates. Doping that is
only in Nd / Na (e.g. painted by the Structure DSL) is the "untracked"
remainder and diffuses with ``species_Nd`` / ``species_Na``'s
coefficients — the original single-species behaviour. Afterwards
Nd = untracked + Σ donor species, Na likewise. In the Fair model each
species' D_eff sees the total same-type concentration (all donors for
n, all acceptors for p) as its carrier density.

Where dopants diffuse: in silicon, the only material with diffusion data.
Every other material, and empty space (an etched trench, the ambient), is a
no-flux wall, and the doping there is left as it is. When silicon fills the
mesh's bounding box, both models work on the Cartesian grid as described
above. Otherwise they diffuse on the mesh's silicon triangles with linear
finite elements: the mesh follows the material interfaces, so the walls sit
exactly on the silicon boundary, and the dose in the silicon is conserved.

Not modelled: oxidation-enhanced diffusion (OED), implant-damage
transient-enhanced diffusion (TED), segregation across material
interfaces, out-diffusion to the ambient.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field as _field
from typing import Optional

import numpy as np

from opentcad.geometry.formats import Material, MeshField

from .pearson_iv import canonicalize_species, dopant_kind


_K_BOLTZMANN_EV_PER_K = 8.617333262e-5
_UM_TO_CM = 1e-4


def _load_diffusion_yaml(canonical: str) -> dict:
    """The ``<Sym>_diffusion.yaml`` table for a canonical species, from
    the dopants data folders (built-in first, then registered ones)."""
    from opentcad.plugins import find_data_file
    from .pearson_iv import _read_yaml, _symbol_for
    name = f"{_symbol_for(canonical)}_diffusion.yaml"
    path = find_data_file("dopants", name)
    if path is None:
        raise FileNotFoundError(
            f"No diffusion table for {canonical!r}: add {name} to a dopants "
            f"data folder (opentcad.plugins.register_data_dir).")
    table = _read_yaml(path)
    declared = str(table.get("species", canonical)).strip().lower()
    if declared != canonical:
        raise ValueError(f"{path} declares species {declared!r}, "
                         f"expected {canonical!r}")
    return table


def _note_diffusion(canonical: str, table: dict, keys) -> None:
    """Note the diffusion coefficients used, with the table's sources."""
    from opentcad.plugins import find_data_file
    from opentcad.provenance import active, note_value, parse_sources, sources_for
    from .pearson_iv import _symbol_for
    if active() is None:
        return
    path = find_data_file("dopants", f"{_symbol_for(canonical)}_diffusion.yaml")
    cited = parse_sources(table, str(path))
    for key in keys:
        block = table["intrinsic"] if key == "intrinsic" else table["fair"][key]
        where = "intrinsic" if key == "intrinsic" else f"fair.{key}"
        note_value(f"Diffusion: {canonical} in Si", f"{where} (D0, Ea)",
                   {"D0_cm2s": float(block["D0_cm2s"]), "Ea_eV": float(block["Ea_eV"])},
                   sources_for(cited, where), file=path)


def diffusivity_intrinsic(species: str, T_K: float,
                           target: Material = Material.SI) -> float:
    """Intrinsic Fick diffusivity D_i(T) in cm²/s per Arrhenius fit.

    Only the intrinsic term; `fair_diffusivity_components` adds the
    concentration-dependent ones.

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
    _note_diffusion(canonical, table, ["intrinsic"])
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
    _note_diffusion(canonical, table, ["intrinsic", *(k for k in out if k != "D_i")])
    return out


def _intrinsic_carrier_density_cm3(T_K: float) -> float:
    """Silicon n_i(T) via the standard temperature-dependent expression
    used for Fair diffusion (Plummer 1.4.13):

        n_i(T) = 3.1e16 · T^1.5 · exp(-0.603 eV / kT)

    Valid 300 - 1500 K. At 1000 °C (1273 K): ~5e18 cm^-3 — the
    Fair-regime crossover for dopant D(n/n_i) saturates for
    doping below this.
    """
    _note_ni_T()
    return _NI_PREFACTOR * (T_K ** 1.5) * math.exp(
        -_NI_ACTIVATION_EV / (_K_BOLTZMANN_EV_PER_K * T_K))


_NI_PREFACTOR = 3.1e16        # [cm^-3 K^-1.5]
_NI_ACTIVATION_EV = 0.603     # [eV]


def _note_ni_T() -> None:
    from opentcad.provenance import CODATA_2018, Source, active, note_value
    if active() is None:
        return
    note_value("Diffusion: silicon n_i(T) for Fair's model",
               "n_i = A·T^1.5·exp(-E/kT)",
               {"A_cm3_K-1.5": _NI_PREFACTOR, "E_eV": _NI_ACTIVATION_EV},
               (Source("J. D. Plummer, M. D. Deal, P. B. Griffin, Silicon VLSI "
                       "Technology (Prentice Hall, 2000)",
                       note="eq. 1.4.13, as the code cites it"),),
               file=__file__)
    note_value("Physical constants", "k_B [eV/K]", _K_BOLTZMANN_EV_PER_K, (CODATA_2018,))


def temperature_celsius_to_kelvin(T_C: float) -> float:
    return T_C + 273.15


@dataclass(frozen=True)
class AnnealResult:
    """Diagnostic record returned alongside the in-place mutation.

    `D_Nd_cm2_s` / `sigma_Nd_um` (and the Na pair) describe the untracked
    remainder, i.e. all of Nd / Na when no species fields are tracked.
    `species_sigma_um` / `species_D_cm2_s` give the same per tracked
    species. σ(t) = √(2 D t).
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
    species_D_cm2_s: dict = _field(default_factory=dict)
    species_sigma_um: dict = _field(default_factory=dict)
    model: str = "intrinsic"


def _resample_mesh_to_grid(points_um: np.ndarray,
                            values: np.ndarray,
                            xmin: float, xmax: float,
                            ymin: float, ymax: float,
                            dx_um: float) -> tuple[np.ndarray,
                                                   np.ndarray, np.ndarray]:
    """Linear-interpolate per-node field(s) onto a Cartesian grid.

    `values` is (N,) or (N, k). Returns (xs, ys, grid_values) with
    grid_values shape (ny, nx) or (ny, nx, k) — first axis y, second x,
    matching scipy image conventions.
    """
    from scipy.interpolate import LinearNDInterpolator

    nx = max(2, int(math.ceil((xmax - xmin) / dx_um)) + 1)
    ny = max(2, int(math.ceil((ymax - ymin) / dx_um)) + 1)
    xs = np.linspace(xmin, xmax, nx)
    ys = np.linspace(ymin, ymax, ny)
    xg, yg = np.meshgrid(xs, ys)
    interp = LinearNDInterpolator(points_um, values, fill_value=0.0)
    grid_vals = np.nan_to_num(interp(xg, yg), nan=0.0)
    return xs, ys, grid_vals


def _resample_grid_to_mesh(xs: np.ndarray, ys: np.ndarray,
                            grid_values: np.ndarray,
                            points_um: np.ndarray) -> np.ndarray:
    """Interpolate Cartesian grid field(s) back to mesh-node locations."""
    from scipy.interpolate import RegularGridInterpolator
    interp = RegularGridInterpolator(
        (ys, xs), grid_values, bounds_error=False, fill_value=0.0,
        method="linear")
    # points_um is (N, 2) in (x, y); interpolator wants (y, x).
    return interp(np.column_stack([points_um[:, 1], points_um[:, 0]]))


#: Materials dopants diffuse in: those with diffusion data. Every other
#: material, and empty space, is a no-flux wall.
DIFFUSING_MATERIALS = frozenset({Material.SI})


class _SiliconFEM:
    """Linear finite elements on the mesh's silicon triangles.

    The mesh follows the material interfaces, so the no-flux walls sit
    exactly on the silicon boundary (the natural boundary condition). Lumped
    mass, so ``M @ C`` (the dose) is conserved exactly by every step.
    Coordinates in µm, D in µm²/s.
    """

    def __init__(self, mf: MeshField):
        from scipy import sparse
        tris = mf.grid.cells_dict.get(5)                       # VTK_TRIANGLE
        if tris is None or len(tris) != mf.n_cells:
            raise ValueError("annealing needs a mesh of triangles only")
        tris = np.asarray(tris, dtype=np.int64)
        si = np.isin(np.asarray(mf.material_ids), [int(m) for m in DIFFUSING_MATERIALS])
        self.any = bool(si.any())
        pts = np.asarray(mf.grid.points, dtype=float)[:, :2]
        self.nodes = np.unique(tris[si])                        # nodes the anneal updates
        local = np.full(mf.n_points, -1, dtype=np.int64)
        local[self.nodes] = np.arange(len(self.nodes))
        T = local[tris[si]]                                     # (m, 3) local indices
        x, y = pts[self.nodes, 0][T], pts[self.nodes, 1][T]
        b = np.stack([y[:, 1] - y[:, 2], y[:, 2] - y[:, 0], y[:, 0] - y[:, 1]], axis=1)
        c = np.stack([x[:, 2] - x[:, 1], x[:, 0] - x[:, 2], x[:, 1] - x[:, 0]], axis=1)
        area = 0.5 * np.abs(b[:, 0] * c[:, 1] - b[:, 1] * c[:, 0])
        keep = area > 0
        T, b, c, area = T[keep], b[keep], c[keep], area[keep]
        self._T = T
        self._ke = (b[:, :, None] * b[:, None, :] + c[:, :, None] * c[:, None, :]) / (4 * area)[:, None, None]
        self._rows = np.repeat(T, 3, axis=1).ravel()
        self._cols = np.tile(T, (1, 3)).ravel()
        n = len(self.nodes)
        self.mass = np.bincount(T.ravel(), weights=np.repeat(area / 3.0, 3), minlength=n)
        self._sparse = sparse

    def stiffness(self, D_tri_um2_s: np.ndarray):
        vals = (self._ke * D_tri_um2_s[:, None, None]).ravel()
        n = len(self.nodes)
        return self._sparse.csc_matrix((vals, (self._rows, self._cols)), shape=(n, n))

    def tri_mean(self, nodal: np.ndarray) -> np.ndarray:
        """Per-triangle mean of a field given on the silicon nodes."""
        return nodal[self._T].mean(axis=1)

    def diffuse(self, C: np.ndarray, D_um2_s: float, time_s: float, n_steps: int = 50) -> np.ndarray:
        """Constant-D diffusion of silicon-node values ``C`` by backward Euler."""
        from scipy.sparse.linalg import splu
        dt = time_s / n_steps
        A = self._sparse.diags(self.mass, format="csc") + dt * self.stiffness(
            np.full(len(self._T), D_um2_s))
        lu = splu(A)
        for _ in range(n_steps):
            C = lu.solve(self.mass * C)
        return C


@dataclass
class _DopantField:
    name: str            # tracked species name, or "untracked_donor/acceptor"
    d_species: str       # species whose coefficients drive this field
    kind: str            # "donor" | "acceptor"
    values: np.ndarray   # per-node concentration [cm^-3]

    @property
    def tracked(self) -> bool:
        return not self.name.startswith("untracked_")


def _collect_fields(mf: MeshField, species_Nd: str, species_Na: str
                    ) -> list[_DopantField]:
    """Decompose Nd / Na into the two untracked remainders + tracked species."""
    tracked = []
    nd_tracked = np.zeros(mf.n_points)
    na_tracked = np.zeros(mf.n_points)
    for s in mf.species_names():
        c = np.asarray(mf.get_species(s), dtype=float)
        kind = dopant_kind(s)
        tracked.append(_DopantField(s, s, kind, c))
        if kind == "donor":
            nd_tracked += c
        else:
            na_tracked += c
    rem_d = np.clip(np.asarray(mf.Nd, dtype=float) - nd_tracked, 0.0, None)
    rem_a = np.clip(np.asarray(mf.Na, dtype=float) - na_tracked, 0.0, None)
    return [_DopantField("untracked_donor", species_Nd, "donor", rem_d),
            _DopantField("untracked_acceptor", species_Na, "acceptor", rem_a),
            *tracked]


def _write_fields(mf: MeshField, fields: list[_DopantField]) -> None:
    """Write diffused fields back and rebuild Nd / Na as their sums."""
    nd = np.zeros(mf.n_points)
    na = np.zeros(mf.n_points)
    for f in fields:
        v = np.clip(np.asarray(f.values, dtype=float), 0.0, None)
        if f.tracked:
            mf.set_species(f.name, v)
        if f.kind == "donor":
            nd += v
        else:
            na += v
    mf.Nd = nd
    mf.Na = na


def apply_anneal(mf: MeshField,
                 temperature_C: float,
                 time_s: float,
                 *,
                 species_Nd: str = "As",
                 species_Na: str = "B",
                 grid_resolution_um: float = 0.005,
                 ) -> AnnealResult:
    """Diffuse every dopant field in place per intrinsic Fick's law.

    Each field diffuses with its own species' D. When silicon fills the
    mesh's bounding box, the field is resampled onto a Cartesian grid,
    convolved with a Gaussian of σ = √(2 D t) (exact for this equation) and
    resampled back. Otherwise it diffuses on the mesh's silicon triangles
    (linear finite elements, backward Euler), whose edges are no-flux walls
    exactly on the silicon boundary: dopant stays in the silicon, its dose
    is conserved, and doping in other materials is left as it is. Mutates
    the MeshField in place; returns an AnnealResult.

    Args:
        mf: MeshField with doping to anneal. Nd and Na in cm⁻³.
        temperature_C: anneal temperature in °C.
        time_s: anneal duration in seconds.
        species_Nd: species whose D drives the untracked donor remainder
            (Nd not covered by ``C_<species>`` fields). Default "As".
        species_Na: same for the untracked acceptor remainder. Default "B".
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
    xmin, xmax, ymin, ymax = mf.bounds[:4]
    pts = np.asarray(mf.grid.points, dtype=float)[:, :2]
    fields = _collect_fields(mf, species_Nd, species_Na)

    D_by_field = {f.name: diffusivity_intrinsic(f.d_species, T_K) for f in fields}
    sigma_by_field = {n: math.sqrt(2.0 * D * time_s) / _UM_TO_CM
                      for n, D in D_by_field.items()}
    fem = None if _silicon_fills_box(mf) else _SiliconFEM(mf)

    for f in fields:
        sigma_um = sigma_by_field[f.name]
        if fem is not None:
            # Silicon doesn't fill the box: diffuse on the silicon triangles,
            # whose edges are the no-flux walls (a convolution over the box
            # would carry dopant into the oxide or into empty space).
            if fem.any and float(np.max(f.values[fem.nodes])) > 0.0 and time_s > 0:
                v = np.array(f.values, dtype=float, copy=True)
                v[fem.nodes] = fem.diffuse(v[fem.nodes], D_by_field[f.name] / _UM_TO_CM ** 2,
                                           time_s)
                f.values = v
            continue
        # σ far below a grid cell (or an empty field): identity convolution.
        if float(np.max(f.values)) <= 0.0 or sigma_um <= 0.1 * grid_resolution_um:
            continue
        xs, ys, grid_vals = _resample_mesh_to_grid(
            pts, f.values, xmin, xmax, ymin, ymax, grid_resolution_um)
        # The grid's edge samples sit on the domain boundary, so the
        # no-flux wall must pass through them: mode='mirror' (whole-sample
        # symmetric). It conserves the trapezoid integral that the mesh
        # interpolant carries; 'reflect' puts the wall half a cell outside
        # and loses dose wherever the profile is large at the surface.
        smoothed = gaussian_filter(grid_vals, sigma=sigma_um / grid_resolution_um,
                                   mode="mirror")
        f.values = _resample_grid_to_mesh(xs, ys, smoothed, pts)

    _write_fields(mf, fields)

    tracked = [f.name for f in fields if f.tracked]
    return AnnealResult(
        temperature_C=float(temperature_C),
        time_s=float(time_s),
        species_Nd=canonicalize_species(species_Nd),
        species_Na=canonicalize_species(species_Na),
        D_Nd_cm2_s=float(D_by_field["untracked_donor"]),
        D_Na_cm2_s=float(D_by_field["untracked_acceptor"]),
        sigma_Nd_um=float(sigma_by_field["untracked_donor"]),
        sigma_Na_um=float(sigma_by_field["untracked_acceptor"]),
        grid_cell_um=float(grid_resolution_um),
        species_D_cm2_s={n: float(D_by_field[n]) for n in tracked},
        species_sigma_um={n: float(sigma_by_field[n]) for n in tracked},
        model="intrinsic",
    )


@dataclass(frozen=True)
class FairAnnealResult:
    """Diagnostic record for a concentration-coupled Fair anneal.

    `D_i_Nd` / `D_eff_Nd_peak` (and the Na pair) use species_Nd's /
    species_Na's coefficients; `species_D_eff_peak_cm2_s` gives the peak
    effective diffusivity per tracked species — the one-number summary of
    how much concentration enhancement mattered.
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
    species_D_eff_peak_cm2_s: dict = _field(default_factory=dict)
    model: str = "fair"


def _fair_D_eff_field(coefs: dict, charge_field: np.ndarray,
                       n_i_T: float) -> np.ndarray:
    """D_eff(x,y) = D_i + Σ D_k · (u^k) where u = max(charge, n_i) / n_i.

    `charge_field` is n (≈ total donors in n-type regions) or p (≈ total
    acceptors in p-type). Floored at n_i so intrinsic regions see the
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
    (harmonic mean). Edge samples lie on the domain boundary and own a
    half control volume (quarter at corners), so the no-flux wall passes
    through them and the trapezoid integral of C is conserved exactly.
    Stable and positivity-preserving for D·dt/dx² ≤ 0.25.

    Shape (ny, nx) in (y, x) order per the resample convention.
    """
    # Face-centered diffusivities: D_{i+1/2} = 2·D_i·D_{i+1} / (D_i + D_{i+1})
    # Harmonic average recovers the exact flux across a jump (arithmetic
    # overpredicts it).
    Dx_face = 2.0 * D[:, :-1] * D[:, 1:] / np.maximum(
        D[:, :-1] + D[:, 1:], 1e-30)
    Dy_face = 2.0 * D[:-1, :] * D[1:, :] / np.maximum(
        D[:-1, :] + D[1:, :], 1e-30)

    Fx = Dx_face * (C[:, 1:] - C[:, :-1]) / dx_cm       # (ny, nx-1)
    Fy = Dy_face * (C[1:, :] - C[:-1, :]) / dx_cm       # (ny-1, nx)

    # Divergence; no flux across domain edges. Edge samples have a half
    # control volume in that direction, hence the factor 2.
    dCdt = np.zeros_like(C)
    dCdt[:, 1:-1] += (Fx[:, 1:] - Fx[:, :-1]) / dx_cm
    dCdt[:, 0]    += 2.0 * Fx[:, 0]  / dx_cm
    dCdt[:, -1]   -= 2.0 * Fx[:, -1] / dx_cm
    dCdt[1:-1, :] += (Fy[1:, :] - Fy[:-1, :]) / dx_cm
    dCdt[0, :]    += 2.0 * Fy[0, :]  / dx_cm
    dCdt[-1, :]   -= 2.0 * Fy[-1, :] / dx_cm

    return C + dt_s * dCdt


def apply_anneal_fair(mf: MeshField,
                      temperature_C: float,
                      time_s: float,
                      *,
                      species_Nd: str = "P",
                      species_Na: str = "B",
                      grid_resolution_um: float = 0.01,
                      stability_factor: float = 0.2,
                      max_sub_steps: int = 200_000,
                      ) -> FairAnnealResult:
    """Concentration-coupled Fair anneal via explicit FTCS sub-stepping.

    Unlike :func:`apply_anneal` — a single Gaussian convolution, correct
    only for constant-D diffusion — this integrates ∂C/∂t = ∇·(D_eff ∇C)
    explicitly for every dopant field, with D_eff rebuilt each step from
    the current doping and the Fair series:

        D_eff = D_i + D⁻·(n/n_i) + D⁻⁻·(n/n_i)²                (donors)
        D_eff = D_i + D⁺·(p/n_i) + D⁺⁺·(p/n_i)²                (acceptors)

    n is taken as the total donor concentration and p as the total
    acceptor concentration, so every donor species feels the electrons
    from all of them. This reproduces the phosphorus high-concentration
    enhancement (D⁻⁻ dominates at n ≫ n_i) and arsenic's much smaller
    one. Coefficients come from
    ``opentcad/process/doping/data/{P,As,B}_diffusion.yaml``.

    Numerical details:
      * Explicit Euler on a Cartesian grid, Neumann (no-flux) walls, when
        silicon fills the mesh's bounding box. Otherwise linear finite
        elements on the silicon triangles (no-flux walls exactly on the
        silicon boundary), backward Euler with D_eff lagged one step.
      * Harmonic-mean D at cell faces — preserves flux across sharp
        concentration gradients where D jumps by orders of magnitude.
      * Sub-step dt = ``stability_factor`` · dx² / max(D_eff) over all
        fields. The 2D explicit scheme is stable only for factors ≤ 0.25
        (von Neumann; also the positivity bound here), so the factor is
        restricted to (0, 0.25], default 0.2. D_eff is re-evaluated each
        sub-step.
      * Capped at ``max_sub_steps`` iterations as a runaway guard.

    Untracked Nd / Na (not covered by ``C_<species>`` fields) diffuse
    with ``species_Nd`` / ``species_Na``'s coefficients. Mutates the
    MeshField in place. Use :func:`apply_anneal` when the profile stays
    well below n_i at the anneal temperature — it is exact there and
    much cheaper.
    """
    if time_s < 0:
        raise ValueError(f"time must be ≥ 0 (got {time_s} s)")
    if temperature_C <= -273.15:
        raise ValueError(
            f"temperature must be above absolute zero (got {temperature_C}°C)")
    if not 0.0 < stability_factor <= 0.25:
        raise ValueError(
            f"stability_factor must lie in (0, 0.25] (2D explicit stability "
            f"limit); got {stability_factor}")

    T_K = temperature_celsius_to_kelvin(temperature_C)
    n_i_T = _intrinsic_carrier_density_cm3(T_K)

    xmin, xmax, ymin, ymax = mf.bounds[:4]
    pts = np.asarray(mf.grid.points, dtype=float)[:, :2]
    fields = _collect_fields(mf, species_Nd, species_Na)
    coefs = [fair_diffusivity_components(f.d_species, T_K) for f in fields]
    is_donor = [f.kind == "donor" for f in fields]

    if not _silicon_fills_box(mf):
        return _fair_on_silicon(mf, fields, coefs, is_donor, n_i_T, temperature_C,
                                time_s, species_Nd, species_Na)
    xs, ys, stack = _resample_mesh_to_grid(
        pts, np.column_stack([f.values for f in fields]),
        xmin, xmax, ymin, ymax, grid_resolution_um)
    grids = [stack[:, :, k].copy() for k in range(len(fields))]

    dx_cm = grid_resolution_um * _UM_TO_CM
    D_peak = [0.0] * len(fields)
    dt_sum = 0.0
    n_steps = 0
    t_left = float(time_s)

    while t_left > 0.0 and n_steps < max_sub_steps:
        n_tot = sum(g for g, d in zip(grids, is_donor) if d)
        p_tot = sum(g for g, d in zip(grids, is_donor) if not d)
        Ds = [_fair_D_eff_field(c, n_tot if d else p_tot, n_i_T)
              for c, d in zip(coefs, is_donor)]
        D_max = max(float(np.max(D)) for D in Ds)
        if D_max <= 0.0:
            break
        dt_sub = min(stability_factor * (dx_cm * dx_cm) / D_max, t_left)
        for k, D in enumerate(Ds):
            grids[k] = _ftcs_step(grids[k], D, dx_cm, dt_sub)
            D_peak[k] = max(D_peak[k], float(np.max(D)))
        t_left -= dt_sub
        dt_sum += dt_sub
        n_steps += 1

    if t_left > 1e-12 * time_s:
        raise RuntimeError(
            f"max_sub_steps ({max_sub_steps}) hit with {t_left:.2e} s "
            f"of anneal time left. Increase max_sub_steps, coarsen "
            f"grid_resolution_um, or use apply_anneal (intrinsic) "
            f"instead for this condition.")

    back = _resample_grid_to_mesh(xs, ys, np.stack(grids, axis=-1), pts)
    for k, f in enumerate(fields):
        f.values = back[:, k]
    _write_fields(mf, fields)

    names = [f.name for f in fields]
    i_d, i_a = names.index("untracked_donor"), names.index("untracked_acceptor")
    return FairAnnealResult(
        temperature_C=float(temperature_C),
        time_s=float(time_s),
        species_Nd=canonicalize_species(species_Nd),
        species_Na=canonicalize_species(species_Na),
        n_sub_steps=int(n_steps),
        dt_sub_mean_s=float(dt_sum / max(n_steps, 1)),
        D_i_Nd_cm2_s=float(coefs[i_d]["D_i"]),
        D_eff_Nd_peak_cm2_s=float(D_peak[i_d]),
        D_i_Na_cm2_s=float(coefs[i_a]["D_i"]),
        D_eff_Na_peak_cm2_s=float(D_peak[i_a]),
        grid_cell_um=float(grid_resolution_um),
        species_D_eff_peak_cm2_s={f.name: float(D_peak[k])
                                  for k, f in enumerate(fields) if f.tracked},
        model="fair",
    )


def _silicon_fills_box(mf: MeshField) -> bool:
    """True when every cell is silicon and the cells tile the bounding box,
    so the box edges are the only walls."""
    mats = np.asarray(mf.material_ids)
    if not np.all(np.isin(mats, [int(m) for m in DIFFUSING_MATERIALS])):
        return False
    xmin, xmax, ymin, ymax = mf.bounds[:4]
    tris = mf.grid.cells_dict.get(5)
    if tris is None:
        return False
    p = np.asarray(mf.grid.points, dtype=float)[:, :2][np.asarray(tris)]
    area = 0.5 * np.abs((p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1])
                        - (p[:, 2, 0] - p[:, 0, 0]) * (p[:, 1, 1] - p[:, 0, 1]))
    return bool(abs(area.sum() - (xmax - xmin) * (ymax - ymin)) <= 1e-9 * (xmax - xmin) * (ymax - ymin))


def _fair_on_silicon(mf, fields, coefs, is_donor, n_i_T, temperature_C, time_s,
                     species_Nd, species_Na, n_steps: int = 200) -> FairAnnealResult:
    """The Fair anneal on the silicon triangles (see apply_anneal_fair)."""
    from scipy.sparse.linalg import splu
    fem = _SiliconFEM(mf)
    D_peak = [0.0] * len(fields)
    if fem.any and time_s > 0:
        Cs = [np.asarray(f.values, dtype=float)[fem.nodes].copy() for f in fields]
        dt = time_s / n_steps
        M = fem._sparse.diags(fem.mass, format="csc")
        for _ in range(n_steps):
            n_tot = sum(c for c, d in zip(Cs, is_donor) if d)
            p_tot = sum(c for c, d in zip(Cs, is_donor) if not d)
            for k, (coef, d) in enumerate(zip(coefs, is_donor)):
                if not np.any(Cs[k] > 0):
                    continue
                D = _fair_D_eff_field(coef, n_tot if d else p_tot, n_i_T)   # cm²/s, nodal
                D_peak[k] = max(D_peak[k], float(np.max(D)))
                A = M + dt * fem.stiffness(fem.tri_mean(D) / _UM_TO_CM ** 2)
                Cs[k] = splu(A).solve(fem.mass * Cs[k])
        for f, c in zip(fields, Cs):
            v = np.array(f.values, dtype=float, copy=True)
            v[fem.nodes] = c
            f.values = v
    _write_fields(mf, fields)
    names = [f.name for f in fields]
    i_d, i_a = names.index("untracked_donor"), names.index("untracked_acceptor")
    return FairAnnealResult(
        temperature_C=float(temperature_C),
        time_s=float(time_s),
        species_Nd=canonicalize_species(species_Nd),
        species_Na=canonicalize_species(species_Na),
        n_sub_steps=int(n_steps if time_s > 0 else 0),
        dt_sub_mean_s=float(time_s / n_steps),
        D_i_Nd_cm2_s=float(coefs[i_d]["D_i"]),
        D_eff_Nd_peak_cm2_s=float(D_peak[i_d]),
        D_i_Na_cm2_s=float(coefs[i_a]["D_i"]),
        D_eff_Na_peak_cm2_s=float(D_peak[i_a]),
        grid_cell_um=0.0,
        species_D_eff_peak_cm2_s={f.name: float(D_peak[k])
                                  for k, f in enumerate(fields) if f.tracked},
        model="fair",
    )
