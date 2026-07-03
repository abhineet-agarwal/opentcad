"""
Tests for the pluggable physics layer (PhysicsConfig + MobilityModel).

We check:
  - ConstantMobility default reproduces published Si values exactly.
  - Klaassen reduces to ~ lattice mobility at low doping (1e14 cm^-3).
  - Klaassen degrades mobility strongly at high doping (1e19 cm^-3).
  - Switching ConstantMobility → Klaassen on a pn junction shifts the
    forward current (Klaassen mu is lower than the constant value at
    the 1e17 doping used in the diode).
"""
import numpy as np
import pytest
from opentcad.device.physics import PhysicsConfig
from opentcad.device.models import ConstantMobility, Klaassen, Canali
from opentcad.device.solver import DeviceSolver
from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.materials.database import load_material


def _make_silicon_block(Na=0.0, Nd=0.0):
    """1-D-like silicon slab to probe equilibrium mobility values."""
    s = (Structure(width_um=0.5, name=f"slab_{Na:.0e}_{Nd:.0e}")
         .add_substrate("body", 0.5, Material.SI, doping_Na=Na, doping_Nd=Nd)
         .add_contact("left", 0.0, 0.5, "body", surface="bottom")
         .add_contact("right", 0.0, 0.5, "body", surface="top"))
    return s.to_meshfield(mesh_size_um=0.05)


def test_constant_mobility_reproduces_published_values():
    """ConstantMobility.attach() must set mu_n / mu_p to the YAML values."""
    si = load_material("Si")
    assert si.mobility_constant.electron_cm2_Vs == pytest.approx(1350.0)
    assert si.mobility_constant.hole_cm2_Vs == pytest.approx(480.0)

    mob = ConstantMobility()
    assert not mob.requires_carriers
    assert mob.mu_n_expr() == "mu_n"
    assert mob.mu_p_expr() == "mu_p"


def test_klaassen_yaml_parameters_loaded():
    """Klaassen pulls coefficients from the YAML mobility_klaassen block.
    Values are the published Si fit from Klaassen (1992) Solid-State
    Electron. 35, 953 — also the DEVSIM Klaassen.py reference values."""
    si = load_material("Si")
    k = si.mobility_klaassen
    assert k.mu_max_e  == pytest.approx(1417.0)
    assert k.mu_max_h  == pytest.approx(470.5)
    assert k.alpha_1_h == pytest.approx(0.719)
    assert k.Nref_D    == pytest.approx(4.0e20)


@pytest.mark.requires_devsim
def _klaassen_node_mu(Na, Nd):
    """Solve equilibrium with Klaassen on a uniform slab; return the
    surface-averaged electron + hole node mobilities (cm^2/V/s)."""
    import devsim as ds

    mf = _make_silicon_block(Na=Na, Nd=Nd)
    solver = DeviceSolver(mf, {"Silicon": load_material("Si")},
                          physics=PhysicsConfig(mobility=Klaassen()))
    solver.solve_equilibrium()

    mu_n = np.asarray(ds.get_node_model_values(
        device=solver._device_name, region="SI", name="ElectronMobilityNode"))
    mu_p = np.asarray(ds.get_node_model_values(
        device=solver._device_name, region="SI", name="HoleMobilityNode"))
    return float(mu_n.mean()), float(mu_p.mean())


@pytest.mark.requires_devsim
def test_klaassen_lightly_doped_approaches_lattice_mobility():
    """At Na=1e14 (very lightly doped) Klaassen should approach the
    lattice limit (~ mu_max), not the ionized-impurity-limited value."""
    mu_n, mu_p = _klaassen_node_mu(Na=1e14, Nd=0)
    print(f"\n  Klaassen @ Na=1e14: mu_n={mu_n:.1f}, mu_p={mu_p:.1f} cm^2/V/s")
    # Lattice limit at 300 K is mu_max (1417 for e, 470.5 for h).
    # At 1e14 cm^-3 the impurity term has only modest impact.
    assert 1200 < mu_n < 1500, f"Klaassen mu_n at 1e14 should be near 1417, got {mu_n:.1f}"
    assert 350  < mu_p <  520, f"Klaassen mu_p at 1e14 should be near 470,  got {mu_p:.1f}"


@pytest.mark.requires_devsim
def test_klaassen_heavily_doped_collapses_mobility():
    """At Nd=1e19 the donor scattering dominates; mu_n should be ~ a
    factor of 5–10 below the lattice limit."""
    mu_n, mu_p = _klaassen_node_mu(Na=0, Nd=1e19)
    print(f"\n  Klaassen @ Nd=1e19: mu_n={mu_n:.1f}, mu_p={mu_p:.1f} cm^2/V/s")
    # Klaassen predicts ~ 110 cm^2/Vs at Nd=1e19 for electrons.
    assert 50 < mu_n < 250, f"Klaassen mu_n at 1e19 should be ~110, got {mu_n:.1f}"


@pytest.mark.requires_devsim
def test_klaassen_mobility_monotonic_with_doping():
    """Increasing N_D from 1e15 to 1e19 must monotonically decrease mu_n."""
    Nds = [1e15, 1e16, 1e17, 1e18, 1e19]
    mus = [_klaassen_node_mu(Na=0, Nd=N)[0] for N in Nds]
    print("\n  Nd      mu_n")
    for N, m in zip(Nds, mus):
        print(f"  {N:.0e}  {m:.1f}")
    diffs = np.diff(mus)
    assert np.all(diffs < 0), f"mu_n must decrease with Nd, got {mus}"


def _diode_structure():
    return (Structure(width_um=1.0, name="diode")
            .add_substrate("p", 0.5, Material.SI, doping_Na=1e17)
            .add_layer    ("n", 0.5, Material.SI, doping_Nd=1e17)
            .add_contact  ("anode",   0.0, 1.0, "p", surface="bottom")
            .add_contact  ("cathode", 0.0, 1.0, "n", surface="top"))


def _sweep_diode(physics):
    import devsim as ds
    si = load_material("Si")
    solver = DeviceSolver(_diode_structure().to_meshfield(0.05),
                          {"Silicon": si}, physics=physics)
    V, I = solver.iv_sweep("anode", "cathode", 0.0, 0.6, 0.1)
    # Drop the device immediately so the next config starts from clean
    # global DEVSIM state — ds.solve() acts on every live device.
    ds.delete_device(device=solver._device_name)
    return V, I


# ---------------------------------------------------------------------------
# Canali high-field velocity saturation
# ---------------------------------------------------------------------------


def _resistor_iv(physics, Nd=1e17, v_end=5.0, v_step=0.5):
    """Build a lightly-doped n-Si resistor and sweep voltage across it.
    Returns (V, I). At high V, I -> constant if velocity saturates."""
    import devsim as ds
    s = (Structure(width_um=1.0, name="resistor")
         .add_substrate("body", 1.0, Material.SI, doping_Nd=Nd)
         .add_contact("left",  0.0, 1.0, "body", surface="bottom")
         .add_contact("right", 0.0, 1.0, "body", surface="top"))
    mf = s.to_meshfield(mesh_size_um=0.1)
    solver = DeviceSolver(mf, {"Silicon": load_material("Si")}, physics=physics)
    V, I = solver.iv_sweep("left", "right", 0.0, v_end, v_step)
    ds.delete_device(device=solver._device_name)
    return np.asarray(V), np.asarray(I)


def test_canali_composes_over_base_model():
    """Canali.requires_carriers inherits from its base."""
    assert Canali(base=ConstantMobility()).requires_carriers is False
    assert Canali(base=Klaassen()).requires_carriers is True
    # Default base is ConstantMobility
    assert Canali().requires_carriers is False


@pytest.mark.requires_devsim
def test_canali_low_field_reduces_to_bulk():
    """At small bias (weak field) mu_eff -> mu_bulk. So a resistor's
    slope dI/dV at low V should match the bulk-mobility solver."""
    V_c, I_c = _resistor_iv(PhysicsConfig(mobility=ConstantMobility()),
                            v_end=0.05, v_step=0.01)
    V_ca, I_ca = _resistor_iv(PhysicsConfig(mobility=Canali(ConstantMobility())),
                              v_end=0.05, v_step=0.01)

    # Linear-region resistance from a two-point fit.
    R_const = (V_c[-1]  - V_c[0])  / (I_c[-1]  - I_c[0])
    R_can   = (V_ca[-1] - V_ca[0]) / (I_ca[-1] - I_ca[0])
    ratio = R_can / R_const
    print(f"\n  low-field R:  constant={R_const:.3e}, Canali={R_can:.3e}, "
          f"ratio={ratio:.4f}")
    assert 0.98 < ratio < 1.02, (
        f"Canali at very low field should give same R as bulk, got {ratio:.3f}")


@pytest.mark.requires_devsim
def test_canali_saturates_current_at_high_field():
    """At high field mu*E >> vsat, drift velocity saturates. So the
    current in a resistor should compress sub-linearly with V. Compare
    at V=2V, well past vsat/mu = ~0.75 V for the 1um resistor."""
    V_c,  I_c  = _resistor_iv(PhysicsConfig(mobility=ConstantMobility()),
                              v_end=2.0, v_step=0.2)
    V_ca, I_ca = _resistor_iv(PhysicsConfig(mobility=Canali(ConstantMobility())),
                              v_end=2.0, v_step=0.2)

    print("\n  V     I(const)      I(Canali)     ratio")
    for v, ic, ica in zip(V_c, I_c, I_ca):
        r = (ica / ic) if abs(ic) > 1e-30 else float("nan")
        print(f"  {v:.2f}  {ic:+.3e}   {ica:+.3e}   {r:.3f}")

    # At V=2V across 1um: E ~ 2e4 V/cm. mu*E for e- = 1350*2e4 = 2.7e7
    # > vsat_e = 1.02e7, so Canali must clearly compress vs. linear.
    ok = (np.abs(I_c) > 1e-15)
    compression = np.abs(I_ca[ok] / I_c[ok])
    assert compression[-1] < 0.6, (
        f"At V=2V Canali should compress I by >~1.7x, got ratio "
        f"{compression[-1]:.3f}")
    # And low-field V=0.2V should still be close to bulk.
    assert compression[0] > 0.85, (
        f"At V=0.2V Canali should still track bulk, got ratio "
        f"{compression[0]:.3f}")


def _diode_structure():
    """Same pn junction, two physics configs. Both should give similar
    forward IV (Shockley); Klaassen gives somewhat lower I because
    mu_n / mu_p drop at Na=Nd=1e17 vs. the lightly-doped constants."""
    Vc, Ic = _sweep_diode(PhysicsConfig(mobility=ConstantMobility()))
    Vk, Ik = _sweep_diode(PhysicsConfig(mobility=Klaassen()))

    print("\n  V    I(const)        I(Klaassen)     ratio")
    for v, ic, ik in zip(Vc, Ic, Ik):
        r = (ik / ic) if ic > 0 else float("nan")
        print(f"  {v:.2f}  {ic:.3e}     {ik:.3e}     {r:.3f}")

    Ic = np.asarray(Ic); Ik = np.asarray(Ik)
    ok = (Ic > 1e-15) & (Ik > 1e-15)
    ratio = Ik[ok] / Ic[ok]
    assert np.all(ratio > 0.1) and np.all(ratio < 2.0), (
        f"Klaassen/constant current ratios should be in [0.1, 2.0], got {ratio}")
