"""
Phase 2a AC small-signal sweep — DeviceSolver.ac_sweep.

Pairs with transient_sweep (task #22). Wires a 1 V AC voltage source to
a metal-on-insulator gate contact via a DEVSIM circuit node, then calls
``ds.solve(type="ac", frequency=...)`` at each requested frequency and
reads the branch current of the source to recover the admittance

    Y(f) = -I_V1(f) / 1 V        [S/cm]

Converted by the caller to capacitance ``C = Im(Y) / (2πf)`` and
conductance ``G = Re(Y)``.

These tests verify:

* **Shape & validation**: shape, ordering, and rejection of empty /
  non-positive frequency arrays and bad terminal choices.
* **Numerics on a known capacitor**: a p-MOS cap biased in ACCUMULATION
  returns C ≈ C_ox = ε_ox/t_ox regardless of frequency, within mesh
  tolerance (~2 %).
* **Frequency linearity**: Im(Y) ∝ ω in accumulation (pure capacitor),
  within tight tolerance across three decades.
* **Reference raises**: ohmic terminals correctly raise
  NotImplementedError rather than silently returning garbage.

The test uses a tiny (0.5 µm × 1 µm) MOS cap with 10 nm oxide so each
solve is seconds, not minutes.
"""
from __future__ import annotations

import numpy as np
import pytest

from opentcad.device.solver import DeviceSolver
from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.materials.database import load_material


pytest.importorskip("devsim")


# DEVSIM gates adding circuit nodes to "before any analysis has run" —
# that gate is process-global, so a prior test's DC solve blocks the
# next test's circuit setup. reset_devsim() between tests gives each
# an AC-ready DEVSIM state.
def _restore_umfpack_callback():
    """reset_devsim() wipes the UMFPACK callback DEVSIM's umfshim
    installed at import time. Re-register it so subsequent solves work.
    """
    import devsim as ds
    from devsim.umfpack.umfshim import local_solver_callback
    ds.set_parameter(name="direct_solver", value="custom")
    ds.set_parameter(name="solver_callback", value=local_solver_callback)


@pytest.fixture(autouse=True)
def _reset_devsim():
    import devsim as ds
    ds.reset_devsim()
    _restore_umfpack_callback()
    yield
    ds.reset_devsim()
    _restore_umfpack_callback()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _mos_cap(tox_um=0.01, tsi_um=0.5, width_um=1.0, mesh_um=0.02):
    """Tiny p-MOS cap: 1 µm gate × 500 nm Si with 10 nm oxide."""
    return (Structure(width_um=width_um, name="ac_cap")
            .add_substrate("sub", tsi_um, Material.SI, doping_Na=1e17)
            .add_layer("ox", tox_um, Material.SIO2)
            .add_contact("gate", 0.0, width_um, "ox",  surface="top")
            .add_contact("body", 0.0, width_um, "sub", surface="bottom")
            .to_meshfield(mesh_size_um=mesh_um))


def _mat():
    return {"Silicon": load_material("Si"), "SiO2": load_material("SiO2")}


def _cox_per_cm_depth(tox_cm=10e-7, width_um=1.0):
    """C_ox for a parallel-plate oxide per cm of out-of-plane depth."""
    eps_ox = 3.9 * 8.8541878128e-14
    return eps_ox / tox_cm * (width_um * 1e-4)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

@pytest.mark.requires_devsim
def test_ac_sweep_rejects_empty_frequency():
    s = DeviceSolver(_mos_cap(), _mat(), ac_terminals=["gate"])
    with pytest.raises(ValueError, match="1D array"):
        s.ac_sweep("gate", "body", [], dc_bias=-1.0)


@pytest.mark.requires_devsim
def test_ac_sweep_rejects_nonpositive_frequency():
    s = DeviceSolver(_mos_cap(), _mat(), ac_terminals=["gate"])
    with pytest.raises(ValueError, match="> 0"):
        s.ac_sweep("gate", "body", [1e3, -1.0, 1e5], dc_bias=-1.0)


@pytest.mark.requires_devsim
def test_ac_sweep_rejects_unknown_terminal():
    s = DeviceSolver(_mos_cap(), _mat(), ac_terminals=["gate"])
    with pytest.raises(KeyError, match="Unknown terminal"):
        s.ac_sweep("nope", "body", [1e6], dc_bias=0.0)


@pytest.mark.requires_devsim
def test_ac_sweep_requires_predeclared_terminal():
    """A terminal not named in ac_terminals at construction must raise
    with guidance to recreate the solver (DEVSIM's one-time gate)."""
    s = DeviceSolver(_mos_cap(), _mat())   # no ac_terminals
    with pytest.raises(RuntimeError, match="not declared in ac_terminals"):
        s.ac_sweep("gate", "body", [1e6], dc_bias=0.0)


@pytest.mark.requires_devsim
def test_ac_sweep_rejects_ohmic_terminal_at_construction():
    """Ohmic-contact AC path isn't wired; declaring one in ac_terminals
    must raise cleanly at initialize() time."""
    mf = (Structure(width_um=1.0, name="pn_ac")
          .add_substrate("p", 0.5, Material.SI, doping_Na=1e17)
          .add_layer   ("n", 0.5, Material.SI, doping_Nd=1e17)
          .add_contact ("anode",   0.0, 1.0, "p", surface="bottom")
          .add_contact ("cathode", 0.0, 1.0, "n", surface="top")
          .to_meshfield(mesh_size_um=0.04))
    with pytest.raises(NotImplementedError, match="semiconductor"):
        s = DeviceSolver(mf, {"Silicon": load_material("Si")},
                         ac_terminals=["anode"])
        s.initialize()


# ---------------------------------------------------------------------------
# Numerical behavior (accumulation → ideal capacitor)
# ---------------------------------------------------------------------------

@pytest.mark.requires_devsim
def test_ac_sweep_accumulation_matches_cox():
    """In deep accumulation on a p-sub MOS cap, C_hf → C_ox.
    Mesh-discretization error is a few %; allow ≤ 5 %."""
    s = DeviceSolver(_mos_cap(), _mat(), ac_terminals=["gate"])
    freqs, Y = s.ac_sweep("gate", "body", [1e6], dc_bias=-2.0)
    C = Y[0].imag / (2 * np.pi * freqs[0])
    Cox = _cox_per_cm_depth()
    assert C == pytest.approx(Cox, rel=0.05), (
        f"C={C:.3e} F/cm vs C_ox={Cox:.3e} F/cm")


@pytest.mark.requires_devsim
def test_ac_sweep_accumulation_frequency_linear():
    """Im(Y) must scale linearly with ω in accumulation — pure cap."""
    s = DeviceSolver(_mos_cap(), _mat(), ac_terminals=["gate"])
    freqs = np.array([1e3, 1e5, 1e7])
    _, Y = s.ac_sweep("gate", "body", freqs, dc_bias=-2.0)
    # C = Im(Y)/ω — should be constant across frequency
    C = np.array([y.imag for y in Y]) / (2 * np.pi * freqs)
    # Each pair within 1 % of the mean
    mean_C = C.mean()
    assert np.all(np.abs(C - mean_C) / mean_C < 0.01), (
        f"C(f) varied beyond 1 %: {C}")


@pytest.mark.requires_devsim
def test_ac_sweep_returns_complex_array_shape():
    """Returned admittance length matches the input frequency array."""
    s = DeviceSolver(_mos_cap(), _mat(), ac_terminals=["gate"])
    freqs = [1e4, 1e5, 1e6, 1e7]
    f_out, Y = s.ac_sweep("gate", "body", freqs, dc_bias=-2.0)
    assert len(f_out) == len(freqs)
    assert len(Y) == len(freqs)
    assert all(isinstance(y, complex) for y in Y)
    assert list(f_out) == list(freqs)


@pytest.mark.requires_devsim
def test_ac_sweep_second_call_same_solver_matches():
    """Calling ac_sweep twice on the same solver (and bias) yields the
    same admittance — the DC state reproduces through circuit_alter."""
    s = DeviceSolver(_mos_cap(), _mat(), ac_terminals=["gate"])
    _, Y1 = s.ac_sweep("gate", "body", [1e6], dc_bias=-2.0)
    _, Y2 = s.ac_sweep("gate", "body", [1e6], dc_bias=-2.0)
    C1 = Y1[0].imag / (2 * np.pi * 1e6)
    C2 = Y2[0].imag / (2 * np.pi * 1e6)
    assert C2 == pytest.approx(C1, rel=1e-3), (
        f"Repeat call drifted: {C1:.3e} -> {C2:.3e}")
