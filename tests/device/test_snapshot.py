"""
DeviceSolver.snapshot / the `fields` analysis: the solution copied back to
the MeshField, checked against pn-junction analytics.
"""
import math

import numpy as np
import pytest

from opentcad.device.solver import DeviceSolver
from opentcad.materials.database import load_material

VT = 1.380649e-23 * 300.0 / 1.602176634e-19
NI = 9.65e9            # Si.yaml ni_cm3_300K, what the solver uses


@pytest.mark.requires_devsim
def test_equilibrium_snapshot_matches_pn_analytics(simple_si_meshfield):
    mf = simple_si_meshfield                     # 1e17 / 1e17, junction at y = 0.5
    s = DeviceSolver(mf, {"Silicon": load_material("Si")})
    snap = s.run("fields")
    assert snap is not mf and "Potential" not in mf.grid.point_data
    y = np.asarray(snap.points)[:, 1]
    psi = np.asarray(snap.grid.point_data["Potential"])
    n = np.asarray(snap.grid.point_data["Electrons"])
    p = np.asarray(snap.grid.point_data["Holes"])
    p_side, n_side = y < 0.15, y > 0.85
    phi_f = VT * math.log(1e17 / NI)
    assert psi[p_side].mean() == pytest.approx(-phi_f, abs=1e-3)
    assert psi[n_side].mean() == pytest.approx(phi_f, abs=1e-3)
    assert np.allclose(n[n_side], 1e17, rtol=1e-3)
    assert np.allclose(p[p_side], 1e17, rtol=1e-3)
    assert np.allclose(n * p, NI ** 2, rtol=1e-3)          # mass action
    assert snap.metadata["solution_fields"]["Electrons"] == "cm^-3"


@pytest.mark.requires_devsim
def test_forward_bias_follows_law_of_the_junction(simple_si_meshfield):
    s = DeviceSolver(simple_si_meshfield, {"Silicon": load_material("Si")})
    s.solve_equilibrium()
    snap = s.field_snapshot({"anode": 0.4})
    y = np.asarray(snap.points)[:, 1]
    np_ = (np.asarray(snap.grid.point_data["Electrons"])
           * np.asarray(snap.grid.point_data["Holes"]))[np.abs(y - 0.5) < 0.05]
    assert np.median(np_) / NI ** 2 == pytest.approx(math.exp(0.4 / VT), rel=0.01)
    assert snap.metadata["solution_bias_V"]["anode"] == pytest.approx(0.4)
    with pytest.raises(KeyError, match="Unknown contact"):
        s.field_snapshot({"gate": 1.0})
    with pytest.raises(ValueError, match="unknown solution field"):
        s.snapshot(fields=("Temperature",))
