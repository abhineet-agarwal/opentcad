"""
Implant geometry: beam tilt and per-column surface.

  * Tilt: dose per unit wafer area is conserved; the implanted-ion
    centroid sits at (x_c + Rp·sin θ, Rp·cos θ) below the window centre;
    θ → 0 matches the closed-form erf window; ±θ mirror each other.
  * Surface: depth is measured from the local top of the meshed stack,
    so an implant into an etched trench lands Rp below the trench floor.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.process.doping import (
    apply_implant, pearson_density, surface_height_function,
)
from opentcad.process.topography import Recipe, simulate, topography_to_meshfield
from opentcad.process.topography.recipe import Implant


def _bare_si(width_um=1.0, body_um=0.5, mesh=0.005):
    return (Structure(width_um=width_um, name="t")
            .add_substrate("body", body_um, Material.SI)
            .to_meshfield(mesh_size_um=mesh))


def _node_areas_um2(mf):
    """Lumped (1/3 triangle) area per node."""
    pts = np.asarray(mf.grid.points)[:, :2]
    tri = np.asarray(mf.grid.cells).reshape(-1, 4)[:, 1:]
    p0, p1, p2 = pts[tri[:, 0]], pts[tri[:, 1]], pts[tri[:, 2]]
    area = 0.5 * np.abs((p1[:, 0] - p0[:, 0]) * (p2[:, 1] - p0[:, 1])
                        - (p2[:, 0] - p0[:, 0]) * (p1[:, 1] - p0[:, 1]))
    out = np.zeros(mf.n_points)
    for k in range(3):
        np.add.at(out, tri[:, k], area / 3.0)
    return out


def _column_dose(mf, field, x0, half=0.01):
    pts = np.asarray(mf.grid.points)[:, :2]
    sel = np.abs(pts[:, 0] - x0) < half
    y, c = pts[sel, 1], field[sel]
    o = np.argsort(y)
    return float(np.trapezoid(c[o], y[o] * 1e-4))


@pytest.mark.parametrize("tilt", [0.0, 7.0, 30.0, 45.0])
def test_tilted_blanket_implant_conserves_dose(tilt):
    mf = _bare_si(mesh=0.004)
    apply_implant(mf, "P", 60, 1e15, tilt_deg=tilt)
    assert _column_dose(mf, mf.Nd, 0.5) == pytest.approx(1e15, rel=0.02)


@pytest.mark.parametrize("tilt", [20.0, -20.0])
def test_tilted_window_centroid_follows_beam(tilt):
    mf = _bare_si(width_um=2.0, body_um=0.6, mesh=0.005)
    r = apply_implant(mf, "P", 100, 1e15, window_x_um=(0.9, 1.1), tilt_deg=tilt)
    pts = np.asarray(mf.grid.points)[:, :2]
    w = mf.Nd * _node_areas_um2(mf)
    x_c = float(np.sum(w * pts[:, 0]) / np.sum(w))
    d_c = float(np.sum(w * (pts[:, 1].max() - pts[:, 1])) / np.sum(w))
    th = math.radians(tilt)
    Rp = r.moments.Rp_um
    assert x_c == pytest.approx(1.0 + Rp * math.sin(th), abs=0.03 * Rp)
    assert d_c == pytest.approx(Rp * math.cos(th), abs=0.03 * Rp)


def test_tilt_to_zero_matches_closed_form():
    a, b = _bare_si(), _bare_si()
    apply_implant(a, "As", 50, 1e15, window_x_um=(0.3, 0.7))
    apply_implant(b, "As", 50, 1e15, window_x_um=(0.3, 0.7), tilt_deg=1e-6)
    assert np.max(np.abs(a.Nd - b.Nd)) < 1e-6 * a.Nd.max()


def test_tilted_blanket_peak_depth_is_Rp_cos_theta():
    """Gaussian profile: the vertical marginal of the rotated 2D Gaussian
    peaks at Rp·cos θ."""
    mf = _bare_si(width_um=0.4, body_um=0.6, mesh=0.003)
    r = apply_implant(mf, "B", 100, 1e15, tilt_deg=30, profile="gaussian")
    pts = np.asarray(mf.grid.points)[:, :2]
    sel = np.abs(pts[:, 0] - 0.2) < 0.005
    peak_depth = pts[:, 1].max() - pts[sel, 1][int(np.argmax(mf.Na[sel]))]
    assert peak_depth == pytest.approx(r.moments.Rp_um * math.cos(math.radians(30)),
                                       abs=0.004)


def test_tilt_out_of_range_rejected():
    with pytest.raises(ValueError, match="tilt"):
        apply_implant(_bare_si(), "As", 30, 1e14, tilt_deg=89.0)
    with pytest.raises(ValueError, match="tilt"):
        Implant("As", 30, 1e14, tilt_deg=-90.0)
    with pytest.raises(ValueError, match="profile"):
        Implant("As", 30, 1e14, profile="lorentz")


def test_surface_function_flat_for_layer_stack():
    mf = _bare_si(width_um=1.0, body_um=0.5, mesh=0.02)
    y_top = float(np.asarray(mf.grid.points)[:, 1].max())
    xs = np.linspace(0.0, 1.0, 51)
    np.testing.assert_allclose(surface_height_function(mf)(xs), y_top, atol=1e-9)


def test_implant_into_trench_lands_below_trench_floor():
    pytest.importorskip("viennals")
    struct =Structure(width_um=1.0, name="trench").add_substrate("body", 0.5, Material.SI)
    state = simulate(struct, Recipe("t").etch(0.1, model="directional",
                                              window_x_um=(0.35, 0.65)),
                     grid_delta_um=0.005)
    mf = topography_to_meshfield(state, mesh_size_um=0.01)
    surf = surface_height_function(mf)
    y_top = float(np.asarray(mf.grid.points)[:, 1].max())
    assert float(surf(np.array([0.1]))[0]) == pytest.approx(y_top, abs=0.005)
    assert float(surf(np.array([0.5]))[0]) == pytest.approx(y_top - 0.1, abs=0.01)

    r = apply_implant(mf, "As", 50, 1e15)
    depth, p = pearson_density(r.moments)
    mode = depth[int(np.argmax(p))]
    pts = np.asarray(mf.grid.points)[:, :2]
    for x0, floor in ((0.1, y_top), (0.5, y_top - 0.1)):
        sel = np.abs(pts[:, 0] - x0) < 0.01
        y_peak = pts[sel, 1][int(np.argmax(mf.Nd[sel]))]
        assert floor - y_peak == pytest.approx(mode, abs=0.012), x0
