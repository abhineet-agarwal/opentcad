"""
Phase 0 exit-criterion test: pn-junction IV must follow the Shockley equation.

I = I_s * (exp(V/V_t) - 1)

We don't compare absolute I_s (that depends on diffusion lengths and is sensitive
to mesh + lifetime). Instead we check the slope of log(I) vs V — it must equal
the thermal slope 1/V_t (i.e. ideality factor n=1) across the forward-bias
exponential region.
"""
import numpy as np
import pytest
from opentcad.device.solver import DeviceSolver, KB_J, Q_C, T_K_DEFAULT
from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.materials.database import load_material


@pytest.fixture
def pn_diode_mf():
    s = (Structure(width_um=1.0, name="pn_diode")
         .add_substrate("p", 0.5, Material.SI, doping_Na=1e17)
         .add_layer("n", 0.5, Material.SI, doping_Nd=1e17)
         .add_contact("anode", 0.0, 1.0, "p", surface="bottom")
         .add_contact("cathode", 0.0, 1.0, "n", surface="top"))
    return s.to_meshfield(mesh_size_um=0.1)


@pytest.mark.requires_devsim
def test_pn_junction_shockley_slope(pn_diode_mf):
    """Forward-bias IV slope must match thermal voltage within 5%."""
    si = load_material("Si")
    solver = DeviceSolver(pn_diode_mf, {"Silicon": si})
    V, I = solver.iv_sweep("anode", "cathode", 0.0, 0.6, 0.1)
    V_arr = np.array(V)
    I_arr = np.array(I)

    # Use the exponential region only (V >= 0.2V — below that the diode is
    # still close to zero current and dominated by numerical noise).
    mask = V_arr >= 0.2
    Vf = V_arr[mask]
    If = I_arr[mask]
    assert np.all(If > 0), f"Forward current should be positive, got {If}"

    # log(I) vs V should be linear with slope 1/V_t
    slope, _ = np.polyfit(Vf, np.log(If), 1)
    V_t = KB_J * T_K_DEFAULT / Q_C
    expected_slope = 1.0 / V_t

    rel_err = abs(slope - expected_slope) / expected_slope
    assert rel_err < 0.05, (
        f"Shockley slope mismatch: got 1/{1/slope:.4f}V, "
        f"expected 1/{V_t:.4f}V (rel error {rel_err*100:.1f}%)")
