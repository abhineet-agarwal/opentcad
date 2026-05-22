"""
tests/device/test_solver_api.py

Tests for DeviceSolver API contract. These test the interface without
requiring a working DEVSIM implementation — they verify that the right
NotImplementedError is raised with useful messages.

Once the solver is implemented, these tests will be updated to verify results.
"""
import pytest
from opentcad.device.solver import DeviceSolver
from opentcad.materials.database import load_material


@pytest.fixture
def simple_mf(simple_si_meshfield):
    """2D Si pn-junction MeshField — Nd/Na/contacts already set by the
    Structure-based shared fixture."""
    return simple_si_meshfield


def test_solver_construction(simple_mf):
    si = load_material("Si")
    solver = DeviceSolver(simple_mf, {"Silicon": si})
    assert solver.mf is simple_mf
    assert not solver._initialized


@pytest.mark.requires_devsim
def test_iv_sweep_returns_lists(simple_mf):
    """iv_sweep returns two equal-length lists of floats."""
    si = load_material("Si")
    solver = DeviceSolver(simple_mf, {"Silicon": si})
    V, I = solver.iv_sweep("anode", "cathode", 0.0, 0.3, 0.1)
    assert len(V) == len(I)
    assert all(isinstance(v, float) for v in V)
    assert all(isinstance(i, float) for i in I)


@pytest.mark.requires_devsim
def test_diode_forward_bias_increases(simple_mf):
    """Forward bias current increases monotonically."""
    import numpy as np
    si = load_material("Si")
    solver = DeviceSolver(simple_mf, {"Silicon": si})
    V, I = solver.iv_sweep("anode", "cathode", 0.0, 0.6, 0.1)
    I_arr = np.array(I)
    # Current should increase with voltage in forward bias
    assert np.all(np.diff(I_arr) >= 0), "Forward bias current not monotonically increasing"
