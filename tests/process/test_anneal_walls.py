"""Anneals keep dopant in the silicon.

Silicon is the only material with diffusion data, so every other material
(here a gate oxide or an oxide block) is a no-flux wall: the dose in the
silicon is conserved, doping in the oxide is left alone, and the profile next
to the wall is the reflecting-wall solution.
"""
from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.ndimage import gaussian_filter1d

from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.process.doping import apply_anneal, apply_anneal_fair, apply_implant
from opentcad.process.doping import moments_for, pearson_density
from opentcad.process.doping.anneal import diffusivity_intrinsic, temperature_celsius_to_kelvin

H_SI = 0.6
TOX = 0.01


def _capped(mesh=0.006):
    """Si with an oxide cap: the Si/SiO2 interface is a wall."""
    return (Structure(width_um=0.3, name="capped")
            .add_substrate("si", H_SI, Material.SI)
            .add_layer("ox", TOX, Material.SIO2)
            .to_meshfield(mesh_size_um=mesh))


def _si_dose(mf, values):
    pts = np.asarray(mf.grid.points)[:, :2]
    tris = np.asarray(mf.grid.cells_dict[5])
    si = np.asarray(mf.material_ids) == int(Material.SI)
    p = pts[tris[si]]
    area = 0.5 * np.abs((p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1])
                        - (p[:, 2, 0] - p[:, 0, 0]) * (p[:, 1, 1] - p[:, 0, 1]))
    return float(np.sum(area * np.asarray(values)[tris[si]].mean(axis=1)))


def _oxide_only_nodes(mf):
    tris = np.asarray(mf.grid.cells_dict[5])
    si = np.asarray(mf.material_ids) == int(Material.SI)
    return np.setdiff1d(np.arange(mf.n_points), np.unique(tris[si]))


def _column(mf, values, x0=0.15, half=0.01):
    pts = np.asarray(mf.grid.points)[:, :2]
    sel = (np.abs(pts[:, 0] - x0) < half) & (pts[:, 1] <= H_SI + 1e-9)
    depth = H_SI - pts[sel, 1]
    o = np.argsort(depth)
    return depth[o], np.asarray(values)[sel][o]


@pytest.mark.parametrize("anneal", [apply_anneal, apply_anneal_fair])
def test_dose_stays_in_the_silicon(anneal):
    mf = _capped()
    apply_implant(mf, "B", 10.0, 5e12)
    b0 = np.asarray(mf.get_species("boron")).copy()
    anneal(mf, 1000.0, 300.0)
    b1 = np.asarray(mf.get_species("boron"))
    assert _si_dose(mf, b1) == pytest.approx(_si_dose(mf, b0), rel=1e-9)
    ox = _oxide_only_nodes(mf)
    assert len(ox) > 0 and np.array_equal(b1[ox], b0[ox])
    assert np.allclose(mf.Na, b1)


def test_profile_at_the_wall_is_the_reflecting_solution():
    mf = _capped(mesh=0.004)
    apply_implant(mf, "B", 10.0, 5e12)
    T_C, t_s = 1000.0, 300.0
    apply_anneal(mf, T_C, t_s)
    depth, b = _column(mf, mf.get_species("boron"))
    # The implant enters through the oxide, so the Si profile starts TOX deep.
    z = np.arange(0.0, H_SI, 2e-4)
    d_um, dens = pearson_density(moments_for("B", 10.0))
    prof = 5e12 * np.interp(z + TOX, d_um, dens, left=0.0, right=0.0) / 1e-4
    D = diffusivity_intrinsic("B", temperature_celsius_to_kelvin(T_C))
    sigma_um = math.sqrt(2 * D * t_s) / 1e-4
    exact = gaussian_filter1d(prof, sigma_um / 2e-4, mode="mirror")   # wall through z = 0
    sel = depth < 0.08
    ratio = b[sel] / np.interp(depth[sel], z, exact)
    assert np.max(np.abs(ratio - 1.0)) < 0.03


def test_an_oxide_block_beside_the_silicon_is_a_wall_too():
    # Si on the left half, oxide on the right half of the same layer.
    mf = (Structure(width_um=0.4, name="side")
          .add_substrate("si", 0.3, Material.SI)
          .add_region("block", 0.2, 0.4, 0.0, 0.3, Material.SIO2)
          .to_meshfield(mesh_size_um=0.01))
    pts = np.asarray(mf.grid.points)[:, :2]
    c = np.where(pts[:, 0] < 0.2, 1e18 * np.exp(-((pts[:, 0] - 0.19) / 0.02) ** 2), 0.0)
    mf.set_species("boron", c)
    mf.Na = c.copy()
    before = _si_dose(mf, c)
    apply_anneal(mf, 1100.0, 600.0)
    after = np.asarray(mf.get_species("boron"))
    assert _si_dose(mf, after) == pytest.approx(before, rel=1e-9)
    ox = _oxide_only_nodes(mf)
    assert np.all(after[ox] == c[ox])


def test_fair_behind_a_wall_matches_fair_on_bare_silicon():
    # The same Si column with and without an oxide cap: the cap's wall sits
    # where bare silicon's top edge is, so the Fair profiles must agree. Bare
    # silicon runs on the Cartesian grid, refined to 2.5 nm (it converges
    # from above: 88.1, 86.1, 85.5 nm at 10, 5, 2.5 nm); the capped column
    # runs on the mesh (84.8 nm at 6 nm, 84.6 nm at 3 nm).
    bare = (Structure(width_um=0.3, name="bare").add_substrate("si", H_SI, Material.SI)
            .to_meshfield(mesh_size_um=0.006))
    capped = _capped()
    for mf, offset in ((bare, 0.0), (capped, TOX)):
        mf.Na = np.full(mf.n_points, 1e17)
        pts = np.asarray(mf.grid.points)[:, :2]
        depth = H_SI - pts[:, 1]
        c = np.where(depth >= 0, 1e20 * np.exp(-((depth - 0.03) / 0.02) ** 2), 0.0)
        mf.set_species("arsenic", c)
        mf.Nd = c.copy()
        apply_anneal_fair(mf, 1000.0, 30.0, species_Nd="As",
                          **({"grid_resolution_um": 0.0025} if offset == 0.0 else {}))

    def xj(mf):
        d, nd = _column(mf, mf.Nd)
        _, na = _column(mf, mf.Na)
        net = nd - na
        k = int(np.flatnonzero((net[:-1] > 0) & (net[1:] <= 0))[-1])
        return d[k] + net[k] / (net[k] - net[k + 1]) * (d[k + 1] - d[k])

    assert xj(capped) == pytest.approx(xj(bare), rel=0.02)
