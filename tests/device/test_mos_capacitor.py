"""
Phase 0 exit-criterion test (capacitor half): a Si/SiO2 MOS capacitor must
exhibit the three classic regimes — accumulation, depletion, inversion —
and the surface potential must saturate near 2*phi_F at strong inversion.

We don't assert an exact Vth (depends on flat-band voltage / work-function
modeling, which is not in Phase 0). We assert qualitative behavior:
  Vg << 0:  p_surf > N_A (accumulation),   n_surf negligible
  Vg ~ 0:   n_surf, p_surf both << N_A     (depletion)
  Vg >> 0:  n_surf > N_A and phi_s ~ 2*phi_F (strong inversion)
"""
import numpy as np
import pytest
from opentcad.device.solver import DeviceSolver, KB_J, Q_C, T_K_DEFAULT
from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.materials.database import load_material


N_A = 1e17       # [cm^-3] p-body doping
T_OX_UM = 0.005  # 5 nm gate oxide


@pytest.fixture
def mos_cap_mf():
    s = (Structure(width_um=1.0, name="mos_cap")
         .add_substrate("p_body", 0.5, Material.SI, doping_Na=N_A)
         .add_layer("oxide", T_OX_UM, Material.SIO2)
         .add_contact("body", 0.0, 1.0, "p_body", surface="bottom")
         .add_contact("gate", 0.0, 1.0, "oxide", surface="top"))
    return s.to_meshfield(mesh_size_um=0.05)


def _surface_node_idx(solver, region):
    """Index of the Si node closest to the top of the body (under oxide)."""
    import devsim as ds
    y_cm = np.asarray(ds.get_node_model_values(
        device=solver._device_name, region=region, name="y"))
    # body is 0.5 um thick → top is at y = 5e-5 cm
    return int(np.argmin(np.abs(y_cm - 5e-5)))


@pytest.mark.requires_devsim
def test_mos_cap_three_regimes(mos_cap_mf):
    import devsim as ds

    si = load_material("Si"); ox = load_material("SiO2")
    solver = DeviceSolver(mos_cap_mf, {"Silicon": si, "SiO2": ox})
    solver.solve_equilibrium()
    top_si = _surface_node_idx(solver, "SI")
    ds.set_parameter(device=solver._device_name, region="SI",
                     name="bodybias", value=0.0)

    V_t = KB_J * T_K_DEFAULT / Q_C
    n_i = si.band_structure.ni_cm3_300K
    phi_F = V_t * np.log(N_A / n_i)

    def sweep(Vg):
        ds.set_parameter(device=solver._device_name, region="SIO2",
                         name="gatebias", value=Vg)
        solver._solve_dc()
        n = ds.get_node_model_values(device=solver._device_name,
                                     region="SI", name="Electrons")[top_si]
        p = ds.get_node_model_values(device=solver._device_name,
                                     region="SI", name="Holes")[top_si]
        pot = ds.get_node_model_values(device=solver._device_name,
                                       region="SI", name="Potential")[top_si]
        return float(n), float(p), float(pot)

    n_acc, p_acc, _ = sweep(-0.5)
    assert p_acc > N_A, (
        f"Accumulation: p_surf should exceed N_A={N_A:.0e}, got {p_acc:.2e}")
    assert n_acc < 1e6, (
        f"Accumulation: n_surf should be tiny, got {n_acc:.2e}")

    n_dep, p_dep, _ = sweep(0.3)
    assert n_dep < N_A and p_dep < N_A, (
        f"Depletion: both carriers should be < N_A, got n={n_dep:.2e} "
        f"p={p_dep:.2e}")

    n_inv, p_inv, pot_inv = sweep(1.2)
    assert n_inv > N_A, (
        f"Strong inversion: n_surf should exceed N_A={N_A:.0e}, "
        f"got {n_inv:.2e}")
    # Surface potential reference: the body contact sits at -phi_F at equilibrium
    # (V_body = 0 with the contact BC `Potential = -V_t*log(N_A/n_i)`).
    # phi_s relative to the body bulk = pot_surface + phi_F.
    phi_s = pot_inv + phi_F
    # Saturates near 2*phi_F; allow a generous 25% band for short-channel /
    # depletion-width / discretization effects.
    assert abs(phi_s - 2 * phi_F) / (2 * phi_F) < 0.25, (
        f"Strong inversion: phi_s should be near 2*phi_F={2*phi_F:.3f}V, "
        f"got {phi_s:.3f}V")
