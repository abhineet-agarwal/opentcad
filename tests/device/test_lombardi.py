"""
Tests for Lombardi surface mobility.

  - Composes over any base MobilityModel; requires_carriers is always True.
  - At very low field mu_surf approaches mu_bulk (Matthiessen with the
    surface terms diverging).
  - At high field mu_surf drops well below mu_bulk (surface roughness
    dominates).
  - Integration: NMOS Id-Vgs with Lombardi should give lower Ion than
    the same NMOS with only Klaassen — that's the expected
    inversion-layer mobility degradation.
"""
import numpy as np
import pytest
from opentcad.device.physics import PhysicsConfig
from opentcad.device.models import (ConstantMobility, Klaassen, Canali,
                                    Lombardi)
from opentcad.device.solver import DeviceSolver
from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.materials.database import load_material


def test_lombardi_requires_carriers():
    assert Lombardi().requires_carriers is True
    assert Lombardi(base=Klaassen()).requires_carriers is True


def test_lombardi_returns_composed_edge_model():
    assert Lombardi().mu_n_expr() == "ElectronMobilityLombardi"
    assert Lombardi().mu_p_expr() == "HoleMobilityLombardi"


def _resistor_iv(physics, Nd=1e17, v_end=0.05, v_step=0.01):
    """Small-bias resistor sweep — quasi-linear so we can extract R."""
    import devsim as ds
    s = (Structure(width_um=1.0, name="lomb_res")
         .add_substrate("body", 1.0, Material.SI, doping_Nd=Nd)
         .add_contact("left",  0.0, 1.0, "body", surface="bottom")
         .add_contact("right", 0.0, 1.0, "body", surface="top"))
    mf = s.to_meshfield(mesh_size_um=0.1)
    solver = DeviceSolver(mf, {"Silicon": load_material("Si")}, physics=physics)
    V, I = solver.iv_sweep("left", "right", 0.0, v_end, v_step)
    ds.delete_device(device=solver._device_name)
    return np.asarray(V), np.asarray(I)


@pytest.mark.requires_devsim
def test_lombardi_low_field_close_to_bulk():
    """At very small bias the field is essentially zero, so Matthiessen's
    surface terms (mu_ac ∝ 1/E, mu_sr ∝ 1/E^gamma) are huge → mu_surf
    reduces to the bulk mobility. The resistance should be close to the
    same setup with just the base model."""
    V_b, I_b = _resistor_iv(PhysicsConfig(mobility=ConstantMobility()))
    V_l, I_l = _resistor_iv(PhysicsConfig(mobility=Lombardi(ConstantMobility())))

    R_b = (V_b[-1] - V_b[0]) / (I_b[-1] - I_b[0])
    R_l = (V_l[-1] - V_l[0]) / (I_l[-1] - I_l[0])
    ratio = R_l / R_b
    print(f"\n  low-field R: bulk={R_b:.3e}, Lombardi={R_l:.3e}, ratio={ratio:.4f}")

    # The 1 V/cm floor on Lb_Emag introduces a small (~few percent) knock
    # on mu_surf even at zero bias. Accept up to 20% deviation at low
    # field on this resistor geometry — the important thing is Lombardi
    # is not off by orders of magnitude when the interface field is absent.
    assert 0.8 < ratio < 1.25, (
        f"Lombardi at low field should track bulk, got R ratio {ratio:.3f}")


def _nmos_structure():
    """Same 2D NMOS as tests/device/test_nmos_idvg.py."""
    from tests.device.test_nmos_idvg import (
        N_A, N_D, T_OX_UM, L_GATE_UM, W_SD_UM, H_BODY_UM, SD_DEPTH_UM)
    w = 2 * W_SD_UM + L_GATE_UM
    return (Structure(width_um=w, name="nmos_lomb")
            .add_substrate("p_body", H_BODY_UM, Material.SI, doping_Na=N_A)
            .add_layer("oxide", T_OX_UM, Material.SIO2)
            .add_region("source", 0.0, W_SD_UM,
                        H_BODY_UM - SD_DEPTH_UM, H_BODY_UM + T_OX_UM,
                        Material.SI, doping_Nd=N_D)
            .add_region("drain", w - W_SD_UM, w,
                        H_BODY_UM - SD_DEPTH_UM, H_BODY_UM + T_OX_UM,
                        Material.SI, doping_Nd=N_D)
            .add_contact("source", 0.0, W_SD_UM, "oxide", surface="top")
            .add_contact("drain",  w - W_SD_UM, w, "oxide", surface="top")
            .add_contact("gate",   W_SD_UM, W_SD_UM + L_GATE_UM,
                         "oxide", surface="top")
            .add_contact("body",   0.0, w, "p_body", surface="bottom"))


def _nmos_id_at_vgs(physics, Vgs=1.2, Vds=0.05):
    """Solve one bias point (Vgs, Vds) on the NMOS and return Id."""
    import devsim as ds
    mf = _nmos_structure().to_meshfield(mesh_size_um=0.03)
    solver = DeviceSolver(mf, {"Silicon": load_material("Si"),
                               "SiO2":    load_material("SiO2")},
                          physics=physics)
    solver.solve_equilibrium()
    for vd in np.linspace(0.0, Vds, 6)[1:]:
        solver._set_contact_voltage("drain", float(vd))
        solver._solve_dc()
    for vg in np.linspace(0.0, Vgs, 7)[1:]:
        solver._set_contact_voltage("gate", float(vg))
        solver._solve_dc()
    Id = abs(solver._get_contact_current("drain"))
    ds.delete_device(device=solver._device_name)
    return float(Id)


@pytest.mark.requires_devsim
@pytest.mark.slow
def test_lombardi_reduces_nmos_ion_vs_klaassen():
    """The whole point of surface mobility: at Vgs above threshold the
    inversion-layer carriers see the Si/SiO2 interface, and their
    effective mobility is degraded. So Ion(Lombardi over Klaassen) must
    be LESS than Ion(Klaassen alone)."""
    Id_kl = _nmos_id_at_vgs(
        PhysicsConfig(mobility=Klaassen()), Vgs=1.2, Vds=0.05)
    Id_lb = _nmos_id_at_vgs(
        PhysicsConfig(mobility=Lombardi(base=Klaassen())), Vgs=1.2, Vds=0.05)

    print(f"\n  NMOS Ion at Vgs=1.2V, Vds=50mV:")
    print(f"    Klaassen only:     {Id_kl:.3e} A/cm")
    print(f"    Lombardi(Klaassen): {Id_lb:.3e} A/cm")
    print(f"    ratio: {Id_lb / Id_kl:.3f}")

    assert Id_lb > 0, "Lombardi should still turn on the NMOS"
    assert Id_lb < Id_kl, (
        f"Lombardi should degrade Ion vs. Klaassen-only; got "
        f"Ion(Lombardi)={Id_lb:.3e} >= Ion(Klaassen)={Id_kl:.3e}")
