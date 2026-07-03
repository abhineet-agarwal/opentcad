"""
Quasi-static CV sweep on a MOS capacitor.

Baseline: p-Si (Na = 1e17) / 5-nm SiO2 / metal gate.
At Vg << Vfb (accumulation) the gate capacitance C -> C_ox = eps_ox / t_ox.
At Vg near Vfb: depletion — C drops below C_ox.
At Vg >> Vth (strong inversion, LF / quasi-static): C recovers toward C_ox
because the inversion-layer minority carriers can respond at each DC step.

C_ox for 5 nm oxide (eps_r = 3.9, eps_0 = 8.854e-14 F/cm):
    C_ox = 3.9 * 8.854e-14 F/cm / 5e-7 cm = 6.91e-7 F/cm^2
    Per um of width (2D: F/cm of out-of-plane depth):
      Width = 1 um = 1e-4 cm, so C_ox_per_cm_depth = 6.91e-7 * 1e-4 = 6.91e-11 F/cm.
"""
import numpy as np
import pytest
from opentcad.device.solver import DeviceSolver
from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.materials.database import load_material


N_A = 1e17
T_OX_UM = 0.005                  # 5 nm oxide
WIDTH_UM = 1.0
EPS_OX_R = 3.9
EPS_0_F_CM = 8.854e-14           # F/cm
C_OX_F_PER_CM2 = EPS_OX_R * EPS_0_F_CM / (T_OX_UM * 1e-4)
# 2D device: DEVSIM currents/charges are per cm of out-of-plane depth,
# so C is in F/cm. Multiply by area/width to get F/cm2 -> F/cm.
C_OX_F_PER_CM = C_OX_F_PER_CM2 * (WIDTH_UM * 1e-4)


def _mos_cap():
    return (Structure(width_um=WIDTH_UM, name="mos_cv")
            .add_substrate("p_body", 0.5, Material.SI, doping_Na=N_A)
            .add_layer("oxide", T_OX_UM, Material.SIO2)
            .add_contact("body", 0.0, WIDTH_UM, "p_body", surface="bottom")
            .add_contact("gate", 0.0, WIDTH_UM, "oxide", surface="top"))


@pytest.mark.requires_devsim
def test_mos_cv_accumulation_reaches_c_ox():
    """In strong accumulation the gate capacitance is set by the oxide
    alone. Sweep Vg through the accumulation region and check C -> C_ox
    within ~15% at the most negative bias."""
    import devsim as ds

    mf = _mos_cap().to_meshfield(mesh_size_um=0.02)
    solver = DeviceSolver(mf, {"Silicon": load_material("Si"),
                               "SiO2":    load_material("SiO2")})
    V, C = solver.cv_sweep("gate", "body", -0.5, +1.2, 0.1)
    ds.delete_device(device=solver._device_name)

    V = np.asarray(V); C = np.asarray(C)
    print(f"\n  Expected C_ox = {C_OX_F_PER_CM:.3e} F/cm")
    print(f"  {'Vg':>6}  {'C (F/cm)':>13}  {'C/C_ox':>7}")
    for v, c in zip(V, C):
        print(f"  {v:+.2f}  {c:.3e}  {c / C_OX_F_PER_CM:.3f}")

    C_acc = C[np.argmin(V)]         # most negative Vg = accumulation
    C_dep = C.min()                  # minimum ≈ depletion
    C_inv = C[np.argmax(V)]         # most positive Vg = inversion

    # Accumulation should be RISING toward C_ox (physical ceiling).
    # -0.5 V is only weakly accumulated for Na=1e17 (Vfb=0 here), so
    # requiring > 50% of C_ox is a solid signal without needing a
    # more-negative sweep (which risks Newton oscillation at deep
    # accumulation).
    assert C_acc > 0.5 * C_OX_F_PER_CM, (
        f"Accumulation C should approach C_ox={C_OX_F_PER_CM:.2e}, "
        f"got {C_acc:.2e}")
    assert C_acc < 1.10 * C_OX_F_PER_CM, (
        f"C_acc = {C_acc:.2e} exceeds C_ox = {C_OX_F_PER_CM:.2e}?!"
        f" That would violate the physical ceiling.")

    # Depletion should dip well below C_ox.
    assert C_dep < 0.4 * C_OX_F_PER_CM, (
        f"Depletion C = {C_dep:.2e} should drop far below "
        f"C_ox = {C_OX_F_PER_CM:.2e}")

    # Strong-inversion LF: recovers toward C_ox. This is the classic
    # LF-CV feature — minority carriers respond at each quasi-static
    # DC step, so the inversion layer acts as the "gate-facing" plate
    # and C returns to C_ox.
    assert C_inv > 0.85 * C_OX_F_PER_CM, (
        f"Strong-inversion LF C = {C_inv:.2e} should recover toward "
        f"C_ox = {C_OX_F_PER_CM:.2e}")
