"""
Tests for Schottky contact boundary condition.

Geometry: n-Si slab with an ohmic contact on one end and a Schottky
(metal) contact on the other. Sweep bias on the Schottky terminal:
  - Forward (Schottky at +V):    turn-on around phi_Bn ~ 0.4-0.6 V
  - Reverse (Schottky at -V):    blocked, current is orders of magnitude
                                 smaller than forward

Also verified: the ideality-factor-1 diode equation slope on the semilog
plot matches q/kT (Schottky is thermionic-emission at zero-order).
"""
import numpy as np
import pytest
from opentcad.device.physics import PhysicsConfig
from opentcad.device.models import ConstantMobility, SRH
from opentcad.device.solver import DeviceSolver, KB_J, Q_C, T_K_DEFAULT
from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.materials.database import load_material


PHI_M = 4.65      # eV, metal work function (~ TiSi2 / W on n-Si)
CHI_SI = 4.05     # eV, Si electron affinity
PHI_BN = PHI_M - CHI_SI    # eV, ~0.60 eV barrier


def _schottky_diode_structure(Nd=1e15):
    return (Structure(width_um=1.0, name="schottky")
            .add_substrate("bulk", 1.0, Material.SI, doping_Nd=Nd)
            .add_contact("ohmic",    0.0, 1.0, "bulk", surface="bottom",
                         contact_type="ohmic")
            .add_contact("schottky", 0.0, 1.0, "bulk", surface="top",
                         contact_type="schottky", work_function_eV=PHI_M))


def _sweep(v_start, v_end, v_step, Nd=1e15):
    import devsim as ds
    mf = _schottky_diode_structure(Nd=Nd).to_meshfield(mesh_size_um=0.05)
    solver = DeviceSolver(mf, {"Silicon": load_material("Si")},
                          physics=PhysicsConfig(mobility=ConstantMobility(),
                                                recombination=[SRH()]))
    V, I = solver.iv_sweep("schottky", "ohmic", v_start, v_end, v_step)
    ds.delete_device(device=solver._device_name)
    return np.asarray(V), np.asarray(I)


def test_schottky_requires_work_function():
    """A Schottky contact without work_function_eV must raise."""
    import devsim as ds
    s = (Structure(width_um=1.0, name="bad_schottky")
         .add_substrate("bulk", 0.5, Material.SI, doping_Nd=1e15)
         .add_contact("ohm", 0.0, 1.0, "bulk", surface="bottom")
         .add_contact("sch", 0.0, 1.0, "bulk", surface="top",
                      contact_type="schottky"))   # missing work_function_eV
    solver = DeviceSolver(s.to_meshfield(mesh_size_um=0.1),
                          {"Silicon": load_material("Si")})
    try:
        with pytest.raises(ValueError, match="work_function_eV"):
            solver.initialize()
    finally:
        for d in list(ds.get_device_list()):
            ds.delete_device(device=d)


@pytest.mark.requires_devsim
def test_schottky_diode_forward_reverse_asymmetry():
    """Sweep the Schottky terminal from -0.3 V to +0.5 V. The forward
    current at +0.5V must exceed the reverse current at -0.3V by more
    than 4 orders of magnitude — that's the classic rectifying signature
    of a Schottky barrier."""
    V, I = _sweep(-0.3, 0.5, 0.05)

    print(f"\n  n-Si Schottky diode (phi_Bn = {PHI_BN:.2f} eV):")
    print(f"  {'V':>6}  {'I (A/cm)':>14}")
    for v, i in zip(V, I):
        print(f"  {v:+.2f}  {i:+.3e}")

    # I is anode current at the Schottky terminal. Forward = +bias means
    # current flowing out of the metal into semi (electrons injected from
    # metal to n-Si is a forward direction for this geometry).
    i_fwd  = float(I[np.argmin(np.abs(V - 0.5))])
    i_rev  = float(I[np.argmin(np.abs(V + 0.3))])
    rect_ratio = abs(i_fwd / i_rev) if i_rev != 0 else float("inf")
    print(f"\n  I(+0.5V) = {i_fwd:+.3e}   I(-0.3V) = {i_rev:+.3e}")
    print(f"  rectification ratio |I_fwd / I_rev| = {rect_ratio:.2e}")

    assert abs(i_fwd) > abs(i_rev) * 1e4, (
        f"Schottky should rectify; got I_fwd={i_fwd:.3e} vs I_rev={i_rev:.3e}"
        f" (ratio {rect_ratio:.2e})")


@pytest.mark.requires_devsim
def test_schottky_forward_semilog_slope_close_to_thermal():
    """On the semilog plot of |I| vs V, the low-forward-bias slope
    should approach q/(kT ln 10) ~ 16.9 /V at 300 K. At higher V the
    curve rolls off due to bulk series resistance, so fit the very
    lowest V-decade only (thermionic-emission dominated)."""
    V, I = _sweep(0.0, 0.3, 0.02)
    logI = np.log10(np.clip(np.abs(I), 1e-30, None))
    ok = np.isfinite(logI) & (np.abs(I) > 1e-15) & (V > 0.02) & (V < 0.20)
    slope = np.polyfit(V[ok], logI[ok], 1)[0]
    print(f"\n  Schottky low-V semilog slope: {slope:.2f} /V "
          f"(ideal q/kT ln10 = 16.9 /V)")
    # Real devices show n = 1.0 - 1.3; a 12-22 /V window is generous.
    assert 12 < slope < 22, f"Schottky ideality-factor slope off: {slope:.2f}"
