"""
Process → device handoff (Phase 2 milestone 2.4): run_recipe writes the
implant + anneal straight onto the device mesh, so the junction it hands
to DeviceSolver must not depend on how fine that mesh is.

As 50 keV / 1e15 cm⁻² into p-Si (1e17), 1000 °C / 30 min: the metallurgical
junction depth at 20 nm vs 5 nm mesh agrees within 5 % for both anneal
models, and Fair (As D⁻ enhancement) drives it deeper than intrinsic.
"""
from __future__ import annotations

import numpy as np
import pytest

from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.process import run_recipe
from opentcad.process.topography import Recipe


def _junction_depth_um(mf, x0=0.3, half=0.012):
    """Depth where Nd = Na along a column, interpolating log(Nd/Na)."""
    pts = np.asarray(mf.grid.points)[:, :2]
    sel = np.abs(pts[:, 0] - x0) < half
    d = pts[:, 1].max() - pts[sel, 1]
    nd, na = mf.Nd[sel], mf.Na[sel]
    o = np.argsort(d)
    d, nd, na = d[o], nd[o], na[o]
    f = np.log(np.maximum(nd, 1.0)) - np.log(na)
    k = int(np.where((f[:-1] > 0) & (f[1:] <= 0))[0][0])
    return float(d[k] + (d[k + 1] - d[k]) * f[k] / (f[k] - f[k + 1]))


@pytest.fixture(scope="module")
def depths():
    struct = (Structure(width_um=0.6, name="xj")
              .add_substrate("p", 0.5, Material.SI, doping_Na=1e17))
    out = {}
    for model in ("intrinsic", "fair"):
        recipe = Recipe("xj").implant("As", 50, 1e15).anneal(1000, 1800, model=model)
        for h in (0.02, 0.005):
            mf = run_recipe(struct, recipe, mesh_size_um=h).meshfield
            out[model, h] = _junction_depth_um(mf)
    return out


@pytest.mark.parametrize("model", ["intrinsic", "fair"])
def test_junction_depth_independent_of_device_mesh(depths, model):
    coarse, fine = depths[model, 0.02], depths[model, 0.005]
    assert coarse == pytest.approx(fine, rel=0.05)


def test_fair_drives_arsenic_junction_deeper(depths):
    assert depths["fair", 0.005] > 1.1 * depths["intrinsic", 0.005]
