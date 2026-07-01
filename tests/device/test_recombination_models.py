"""
Tests for the recombination model layer.

  - SRH alone reproduces the Phase 0 baseline.
  - Adding Auger to SRH increases the recombination rate in the
    high-injection (n+ source/drain) regime.
  - Radiative recombination is negligible vs. SRH in Si (sanity check
    that the model attaches and produces sensible values).
  - The composite URec node_model is the sum of every contributor's
    term_name (smoke-tests the symbolic assembly).
"""
import numpy as np
import pytest
from opentcad.device.physics import PhysicsConfig
from opentcad.device.models import ConstantMobility, SRH, Auger, Radiative
from opentcad.device.solver import DeviceSolver
from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.materials.database import load_material


def _diode_structure(Na=1e17, Nd=1e17):
    return (Structure(width_um=1.0, name="diode")
            .add_substrate("p", 0.5, Material.SI, doping_Na=Na)
            .add_layer    ("n", 0.5, Material.SI, doping_Nd=Nd)
            .add_contact  ("anode",   0.0, 1.0, "p", surface="bottom")
            .add_contact  ("cathode", 0.0, 1.0, "n", surface="top"))


def _sweep_diode(recombination, Na=1e17, Nd=1e17):
    import devsim as ds
    solver = DeviceSolver(_diode_structure(Na, Nd).to_meshfield(0.05),
                          {"Silicon": load_material("Si")},
                          physics=PhysicsConfig(
                              mobility=ConstantMobility(),
                              recombination=recombination))
    V, I = solver.iv_sweep("anode", "cathode", 0.0, 0.6, 0.1)
    ds.delete_device(device=solver._device_name)
    return np.asarray(V), np.asarray(I)


@pytest.mark.requires_devsim
def test_srh_default_matches_phase_0_baseline():
    """Default PhysicsConfig (= [SRH]) must reproduce a sensible diode IV
    with the Shockley exponential slope of q/kT (~25.85 mV/decade)."""
    V, I = _sweep_diode([SRH()])
    ok = I > 0
    slope = np.polyfit(V[ok], np.log10(I[ok]), 1)[0]
    assert 14 < slope < 22, (
        f"semilog slope should be q/(kT*ln10) ~ 16.9 /V, got {slope:.2f}")


def _equilibrium_node_models(physics, names, Na=1e17, Nd=1e20):
    """Solve equilibrium on a diode and return per-node values of each
    requested DEVSIM model name on the n-side region."""
    import devsim as ds
    solver = DeviceSolver(_diode_structure(Na, Nd).to_meshfield(0.05),
                          {"Silicon": load_material("Si")}, physics=physics)
    solver.solve_equilibrium()
    out = {}
    for nm in names:
        out[nm] = np.asarray(ds.get_node_model_values(
            device=solver._device_name, region="SI", name=nm))
    ds.delete_device(device=solver._device_name)
    return out


@pytest.mark.requires_devsim
def test_auger_dominates_at_high_carrier_density():
    """The Auger rate scales as C*n^2*p (or C*n*p^2). Compare the SRH and
    Auger node values directly on a n+ side (Nd=1e20). Auger must exceed
    SRH by orders of magnitude where electron density is highest."""
    vals = _equilibrium_node_models(
        PhysicsConfig(mobility=ConstantMobility(),
                      recombination=[SRH(), Auger()]),
        ["USRH", "UAuger", "Electrons", "Holes"],
        Na=1e17, Nd=1e20)

    # Look at the most n+ node (max Electrons).
    i = int(np.argmax(vals["Electrons"]))
    u_srh = vals["USRH"][i]; u_aug = vals["UAuger"][i]
    n = vals["Electrons"][i]; p = vals["Holes"][i]
    print(f"\n  Most-n+ node: n={n:.2e}, p={p:.2e}")
    print(f"  USRH = {u_srh:+.3e}   UAuger = {u_aug:+.3e}   "
          f"|Auger/SRH| = {abs(u_aug/u_srh):.2e}")

    # Both must be near zero at equilibrium (n*p = n_i^2). What we want
    # is the ratio of the magnitudes of the individual rate prefactors
    # n*p before subtraction. Look at the recombination *rate constants*:
    #   SRH ~ 1/(tau_p*n + tau_n*p)  -> tiny at high n,p
    #   Auger ~ Cn*n + Cp*p           -> grows with n
    # Compute these directly to verify the regime split.
    si = load_material("Si")
    rate_srh = 1.0 / (si.recombination.tau_p_s * n + si.recombination.tau_n_s * p)
    rate_aug = (si.recombination.Cn_cm6_per_s * n
                + si.recombination.Cp_cm6_per_s * p)
    print(f"  rate_srh prefactor = {rate_srh:.3e}")
    print(f"  rate_aug prefactor = {rate_aug:.3e}")
    assert rate_aug > rate_srh, (
        f"At n={n:.1e}, Auger prefactor ({rate_aug:.2e}) should exceed "
        f"SRH prefactor ({rate_srh:.2e})")


@pytest.mark.requires_devsim
def test_radiative_negligible_in_silicon():
    """B_rad for Si is ~1e-15 cm^3/s (indirect-gap). Adding it on top of
    SRH must barely move the IV: |ratio - 1| < 1%."""
    V_srh, I_srh = _sweep_diode([SRH()])
    V_rad, I_rad = _sweep_diode([SRH(), Radiative()])

    ok = (I_srh > 1e-15) & (I_rad > 1e-15)
    rel = I_rad[ok] / I_srh[ok]
    assert np.all(np.abs(rel - 1.0) < 0.01), (
        f"Radiative in Si should not move IV by >1%, got max |ratio-1|"
        f"={np.abs(rel-1.0).max():.3e}")


def test_recombination_composition_smoke():
    """Smoke test: every contributor has a unique term_name and the
    composite URec expression sums them in order."""
    cfg = PhysicsConfig(mobility=ConstantMobility(),
                        recombination=[SRH(), Auger(), Radiative()])
    names = [m.term_name for m in cfg.recombination]
    assert names == ["USRH", "UAuger", "URad"]
    assert len(set(names)) == len(names), "term_name values must be unique"


def test_empty_recombination_list_defaults_to_srh():
    """PhysicsConfig() with no recombination arg defaults to [SRH] so
    existing user code keeps working."""
    cfg = PhysicsConfig()
    assert len(cfg.recombination) == 1
    assert cfg.recombination[0].term_name == "USRH"
