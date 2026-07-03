"""
Tests for bandgap-narrowing models.

  - NoBGN default keeps n_i unchanged (identity).
  - Slotboom n_i_eff matches the closed-form formula at various dopings.
  - Slotboom is negligible at N << 1e17 and significant (>2x) at 1e19.
  - Slotboom on a pn diode with a heavy n+ side raises the forward
    current — the classic BJT-emitter-BGN degradation direction.
"""
import numpy as np
import pytest
from opentcad.device.physics import PhysicsConfig
from opentcad.device.models import (ConstantMobility, SRH, Auger,
                                    NoBGN, Slotboom)
from opentcad.device.solver import DeviceSolver
from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.materials.database import load_material


T_K = 300.0
V_T = 8.617333e-5 * T_K   # eV / K * K = eV = V for 1 unit charge


def _slotboom_ni_eff(N, n_i=9.65e9, E_ref=6.92e-3, N_ref=1e17):
    """Closed-form Slotboom n_i_eff for cross-checking DEVSIM output."""
    N = max(N, 1.0)
    ln = np.log(N / N_ref)
    dEg = E_ref * (ln + np.sqrt(ln**2 + 0.5))
    return n_i * np.exp(dEg / (2 * V_T))


def test_nobgn_returns_bare_ni():
    assert NoBGN().n_i_expr() == "n_i"


def test_slotboom_returns_ni_eff():
    assert Slotboom().n_i_expr() == "n_i_eff"


def _diode(Na, Nd):
    return (Structure(width_um=1.0, name="diode")
            .add_substrate("p", 0.5, Material.SI, doping_Na=Na)
            .add_layer    ("n", 0.5, Material.SI, doping_Nd=Nd)
            .add_contact  ("anode",   0.0, 1.0, "p", surface="bottom")
            .add_contact  ("cathode", 0.0, 1.0, "n", surface="top"))


@pytest.mark.requires_devsim
def test_slotboom_ni_eff_matches_closed_form():
    """Register Slotboom on a diode and query n_i_eff node values on
    both the p-side (Na=1e17) and n+ side (Nd=1e20). Compare to the
    Python closed-form formula."""
    import devsim as ds

    solver = DeviceSolver(_diode(Na=1e17, Nd=1e20).to_meshfield(0.1),
                          {"Silicon": load_material("Si")},
                          physics=PhysicsConfig(mobility=ConstantMobility(),
                                                bgn=Slotboom()))
    solver.initialize()

    donors = np.asarray(ds.get_node_model_values(
        device=solver._device_name, region="SI", name="Donors"))
    acceptors = np.asarray(ds.get_node_model_values(
        device=solver._device_name, region="SI", name="Acceptors"))
    ni_eff = np.asarray(ds.get_node_model_values(
        device=solver._device_name, region="SI", name="n_i_eff"))
    ds.delete_device(device=solver._device_name)

    # Sample one node from each side.
    N_total = donors + acceptors
    ip = int(np.argmax(acceptors))
    inplus = int(np.argmax(donors))

    print("\n  Slotboom n_i_eff check:")
    for label, i in (("p-side (Na=1e17)", ip), ("n+ side (Nd=1e20)", inplus)):
        expected = _slotboom_ni_eff(N_total[i])
        print(f"  {label}: N={N_total[i]:.2e}  "
              f"n_i_eff(sim)={ni_eff[i]:.3e}  "
              f"n_i_eff(theory)={expected:.3e}  "
              f"ratio={ni_eff[i]/expected:.4f}")
        assert abs(ni_eff[i] / expected - 1.0) < 0.05, (
            f"n_i_eff mismatch: sim={ni_eff[i]:.3e} vs theory={expected:.3e}")


def test_slotboom_closed_form_behavior():
    """Sanity of the closed-form itself: n_i_eff ~ n_i below 1e17, and
    grows to > 2x n_i by 1e19."""
    n_i = 9.65e9
    assert _slotboom_ni_eff(1e14, n_i) / n_i == pytest.approx(1.0, abs=0.1)
    assert _slotboom_ni_eff(1e16, n_i) / n_i < 1.3   # small effect
    assert _slotboom_ni_eff(1e19, n_i) / n_i > 2.0   # significant


def _sweep(physics, Na=1e17, Nd=1e20, v_end=0.5, v_step=0.05):
    import devsim as ds
    solver = DeviceSolver(_diode(Na, Nd).to_meshfield(0.05),
                          {"Silicon": load_material("Si")}, physics=physics)
    V, I = solver.iv_sweep("anode", "cathode", 0.0, v_end, v_step)
    ds.delete_device(device=solver._device_name)
    return np.asarray(V), np.asarray(I)


@pytest.mark.requires_devsim
def test_slotboom_increases_forward_current_at_heavy_nplus():
    """BGN raises n_i_eff in the n+ side, which raises the pn-junction
    saturation current I0 (Shockley: I0 ∝ n_i_eff^2). Compare a diode
    with Nd=1e20 side-by-side."""
    V_no, I_no = _sweep(PhysicsConfig(mobility=ConstantMobility(),
                                      recombination=[SRH(), Auger()],
                                      bgn=NoBGN()))
    V_sl, I_sl = _sweep(PhysicsConfig(mobility=ConstantMobility(),
                                      recombination=[SRH(), Auger()],
                                      bgn=Slotboom()))

    print("\n  V     I(NoBGN)      I(Slotboom)   ratio")
    for v, i0, i1 in zip(V_no, I_no, I_sl):
        r = (i1 / i0) if i0 > 0 else float("nan")
        print(f"  {v:.2f}  {i0:+.3e}   {i1:+.3e}   {r:.3f}")

    ok = (I_no > 1e-15) & (I_sl > 1e-15)
    ratio = I_sl[ok] / I_no[ok]
    # Slotboom in the n+ side (1e20) should push I0 up. Direction check:
    # somewhere in the mid-bias range the Slotboom current should exceed
    # NoBGN by >5% (real BGN effect on saturation current).
    assert ratio.max() > 1.05, (
        f"Slotboom should raise IV somewhere, got max ratio {ratio.max():.4f}")
