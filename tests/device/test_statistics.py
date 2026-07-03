"""
Tests for the pluggable statistics layer.

  - Boltzmann is the default (identity wrap).
  - FermiDirac (Blakemore) at light doping (n << N_c) is numerically
    indistinguishable from Boltzmann.
  - FermiDirac at heavy doping (n approaching N_c) softens the Poisson
    n(V) relationship, giving a different equilibrium built-in
    potential for a pn junction.
  - FermiDirac's built-in potential shift is bounded by Blakemore
    ceiling (n_max = N_c / 0.27) so the solve stays numerically stable.
"""
import numpy as np
import pytest
from opentcad.device.physics import PhysicsConfig
from opentcad.device.models import (ConstantMobility, SRH,
                                    Boltzmann, FermiDirac)
from opentcad.device.solver import DeviceSolver
from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.materials.database import load_material


def test_boltzmann_wraps_are_identity():
    b = Boltzmann()
    assert b.wrap_electron_density("n_boltz", None) == "n_boltz"
    assert b.wrap_hole_density("p_boltz", None) == "p_boltz"


def test_fermidirac_wraps_apply_blakemore():
    fd = FermiDirac()
    n = fd.wrap_electron_density("n_i*exp(V/Vt)", None)
    p = fd.wrap_hole_density("n_i*exp(-V/Vt)", None)
    assert "FD_xi" in n and "N_c" in n
    assert "FD_xi" in p and "N_v" in p


def test_physics_config_defaults_to_boltzmann():
    cfg = PhysicsConfig()
    assert isinstance(cfg.statistics, Boltzmann)


def _diode_structure(Na, Nd):
    return (Structure(width_um=1.0, name=f"stat_diode_{Na:.0e}_{Nd:.0e}")
            .add_substrate("p", 0.5, Material.SI, doping_Na=Na)
            .add_layer    ("n", 0.5, Material.SI, doping_Nd=Nd)
            .add_contact  ("anode",   0.0, 1.0, "p", surface="bottom")
            .add_contact  ("cathode", 0.0, 1.0, "n", surface="top"))


def _equilibrium_built_in_potential(physics, Na, Nd):
    """Solve equilibrium on a pn diode and return Vbi as the potential
    difference between the two contact regions (max - min of Potential)."""
    import devsim as ds
    mf = _diode_structure(Na, Nd).to_meshfield(mesh_size_um=0.05)
    solver = DeviceSolver(mf, {"Silicon": load_material("Si")},
                          physics=physics)
    solver.solve_equilibrium()
    pot = np.asarray(ds.get_node_model_values(
        device=solver._device_name, region="SI", name="Potential"))
    Vbi = float(pot.max() - pot.min())
    ds.delete_device(device=solver._device_name)
    return Vbi


@pytest.mark.requires_devsim
def test_fermidirac_matches_boltzmann_at_light_doping():
    """At 1e15 both stats should give the same Vbi (n << N_c, correction
    negligible)."""
    Vbi_b = _equilibrium_built_in_potential(
        PhysicsConfig(mobility=ConstantMobility(), recombination=[SRH()],
                      statistics=Boltzmann()),
        Na=1e15, Nd=1e15)
    Vbi_f = _equilibrium_built_in_potential(
        PhysicsConfig(mobility=ConstantMobility(), recombination=[SRH()],
                      statistics=FermiDirac()),
        Na=1e15, Nd=1e15)
    print(f"\n  Light doping (Nd=Na=1e15):")
    print(f"    Vbi Boltzmann : {Vbi_b:.4f} V")
    print(f"    Vbi FermiDirac: {Vbi_f:.4f} V")
    print(f"    diff          : {(Vbi_f - Vbi_b)*1000:+.2f} mV")

    assert abs(Vbi_f - Vbi_b) < 5e-4, (
        f"At light doping FD should agree with Boltzmann; got "
        f"|dVbi|={abs(Vbi_f-Vbi_b)*1000:.2f} mV")


@pytest.mark.requires_devsim
def test_fermidirac_shifts_vbi_at_heavy_doping():
    """At heavy doping (Nd=Na=1e19 in Si, N_c = 2.86e19) the Blakemore
    correction becomes measurable. Direction: n_FD = n_boltz / (1 +
    xi*n_boltz/N_c) < n_boltz, so for the same Potential the FD Poisson
    solve needs a slightly higher |Potential| to satisfy neutrality —
    ergo Vbi(FD) > Vbi(Boltzmann)."""
    Vbi_b = _equilibrium_built_in_potential(
        PhysicsConfig(mobility=ConstantMobility(), recombination=[SRH()],
                      statistics=Boltzmann()),
        Na=1e19, Nd=1e19)
    Vbi_f = _equilibrium_built_in_potential(
        PhysicsConfig(mobility=ConstantMobility(), recombination=[SRH()],
                      statistics=FermiDirac()),
        Na=1e19, Nd=1e19)
    print(f"\n  Heavy doping (Nd=Na=1e19):")
    print(f"    Vbi Boltzmann : {Vbi_b:.4f} V")
    print(f"    Vbi FermiDirac: {Vbi_f:.4f} V")
    print(f"    diff          : {(Vbi_f - Vbi_b)*1000:+.2f} mV")

    assert Vbi_f > Vbi_b, (
        f"FD should raise Vbi at heavy doping vs Boltzmann; got FD={Vbi_f:.4f}, "
        f"Boltzmann={Vbi_b:.4f}")
    # Sanity: correction must be small (Blakemore is O(xi*n/N_c) at
    # n/N_c ~ 0.35 for 1e19 in Si), typically 5-50 mV.
    assert 0.002 < (Vbi_f - Vbi_b) < 0.1, (
        f"FD-Boltzmann Vbi difference should be a few tens of mV, got "
        f"{(Vbi_f - Vbi_b)*1000:.2f} mV")
