"""
Tests for the compact-model oxide-charge / interface-trap Vfb shift.

`Structure.add_contact(..., flat_band_shift_V=...)` on a metal-on-
insulator (gate) contact packs Qf, midgap Dit, and phi_MS into a single
Vfb offset:

    Vfb_eff = -Qf/Cox - q * Dit * (Emidgap - Ef_ref) / Cox + phi_MS

The metal-on-insulator BC becomes Potential = Vg - Vfb, so an inversion
point that appeared at Vg = Vth without the shift now appears at
Vg = Vth + Vfb.

This test builds two identical MOS capacitors: one with Vfb=0 (baseline)
and one with Vfb=+0.5 V. At the same Vg, the biased-Vfb device should
be less inverted; a Vg=+0.5 V larger should reproduce the same surface
carrier concentration.
"""
import numpy as np
import pytest
from opentcad.device.solver import DeviceSolver
from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.materials.database import load_material


N_A = 1e17
T_OX_UM = 0.005


def _mos_cap(flat_band_shift_V=0.0):
    return (Structure(width_um=1.0, name=f"mos_qf_{flat_band_shift_V}")
            .add_substrate("p_body", 0.5, Material.SI, doping_Na=N_A)
            .add_layer("oxide", T_OX_UM, Material.SIO2)
            .add_contact("body", 0.0, 1.0, "p_body", surface="bottom")
            .add_contact("gate", 0.0, 1.0, "oxide", surface="top",
                         flat_band_shift_V=flat_band_shift_V))


def _top_si_node(solver):
    import devsim as ds
    y_cm = np.asarray(ds.get_node_model_values(
        device=solver._device_name, region="SI", name="y"))
    return int(np.argmin(np.abs(y_cm - 5e-5)))   # top of 0.5 um body


def _ramp_and_measure(solver, top_si, Vg_target, Vg_from=0.0, step=0.1):
    """Ramp gatebias from Vg_from to Vg_target in small steps and return
    the surface electron density at the top-Si node."""
    import devsim as ds
    steps = np.arange(Vg_from + step, Vg_target + 1e-9, step)
    for v in steps:
        ds.set_parameter(device=solver._device_name, region="SIO2",
                         name="gatebias", value=float(v))
        solver._solve_dc()
    return float(ds.get_node_model_values(
        device=solver._device_name, region="SI", name="Electrons")[top_si])


def test_flat_band_shift_default_is_zero():
    """add_contact without flat_band_shift_V leaves it at 0.0 so the
    behavior for every non-MOS test path stays unchanged."""
    s = (Structure(width_um=1.0)
         .add_substrate("body", 0.5, Material.SI, doping_Na=1e17)
         .add_layer("ox", 0.005, Material.SIO2)
         .add_contact("gate", 0.0, 1.0, "ox", surface="top"))
    mf = s.to_meshfield(mesh_size_um=0.1)
    assert mf.get_contact("gate").flat_band_shift_V == 0.0


def test_flat_band_shift_propagates_to_contact_tag():
    """The value set in add_contact must be readable on the ContactTag."""
    s = (Structure(width_um=1.0)
         .add_substrate("body", 0.5, Material.SI, doping_Na=1e17)
         .add_layer("ox", 0.005, Material.SIO2)
         .add_contact("gate", 0.0, 1.0, "ox", surface="top",
                      flat_band_shift_V=-0.7))
    mf = s.to_meshfield(mesh_size_um=0.1)
    assert mf.get_contact("gate").flat_band_shift_V == pytest.approx(-0.7)


@pytest.mark.requires_devsim
def test_flat_band_shift_moves_inversion_by_the_same_voltage():
    """Whatever Vg turns on the baseline (Vfb=0) device should turn on
    the shifted (Vfb=+0.5V) device at exactly Vg + 0.5 V, because the
    shift enters the gate BC as an additive constant."""
    import devsim as ds

    si = load_material("Si"); ox = load_material("SiO2")
    Vfb = 0.5

    def build_and_solve(vfb):
        mf = _mos_cap(vfb).to_meshfield(mesh_size_um=0.05)
        solver = DeviceSolver(mf, {"Silicon": si, "SiO2": ox})
        solver.solve_equilibrium()
        top = _top_si_node(solver)
        ds.set_parameter(device=solver._device_name, region="SI",
                         name="bodybias", value=0.0)
        return solver, top

    baseline_solver, baseline_top = build_and_solve(0.0)
    n_at_vg1_2 = _ramp_and_measure(baseline_solver, baseline_top, 1.2)
    print(f"\n  Baseline (Vfb=0.0): n_surf(Vg=1.2V) = {n_at_vg1_2:.2e}")

    ds.delete_device(device=baseline_solver._device_name)

    shifted_solver, shifted_top = build_and_solve(Vfb)
    n_at_vg1_2_shifted = _ramp_and_measure(shifted_solver, shifted_top, 1.2)
    # Continue ramping to Vg=1.7 from the current state.
    n_at_vg_shifted    = _ramp_and_measure(
        shifted_solver, shifted_top, 1.2 + Vfb, Vg_from=1.2)
    print(f"  Vfb=+0.5V:  n_surf(Vg=1.2V)      = {n_at_vg1_2_shifted:.2e}")
    print(f"              n_surf(Vg=1.2+0.5V)  = {n_at_vg_shifted:.2e}")

    ds.delete_device(device=shifted_solver._device_name)

    # (1) At the same Vg=1.2V, the shifted device should be measurably
    # less inverted (Vfb of +0.5 pushes threshold higher). Above strong
    # inversion the response is closer to CV than exponential, so ~10x
    # suppression is a solid signal.
    assert n_at_vg1_2_shifted < n_at_vg1_2 / 5, (
        f"Positive Vfb should suppress inversion at same Vg: "
        f"baseline {n_at_vg1_2:.2e}, shifted {n_at_vg1_2_shifted:.2e}")

    # (2) With the compensating Vg = 1.2 + Vfb, inversion should match
    # the baseline within a factor of ~2 (mesh discretisation etc.).
    ratio = n_at_vg_shifted / n_at_vg1_2
    print(f"  ratio n(shifted, Vg=1.7) / n(baseline, Vg=1.2) = {ratio:.3f}")
    assert 0.5 < ratio < 2.0, (
        f"Compensating Vg=Vfb should restore the same inversion state, "
        f"got ratio {ratio:.3f}")
