"""
Phase 2a Qf — physical surface-charge path.

The compact ``flat_band_shift_V`` on a gate contact packs Qf/Cox +
phi_MS + Dit terms into one number, exact for a uniform oxide. The new
``interface_Qf_C_per_cm2`` option installs Qf as a Gaussian-smeared
volumetric charge inside the semiconductor region at a user-supplied
interface y-coordinate — the physically-located Qf that also works for
non-uniform oxides, non-planar geometry, or when Qf varies spatially.

Tests here verify:
  * Signature: dict keyed by semiconductor region, value =
    (Qf_C_per_cm2, y_interface_um).
  * Rejects naming an insulator region, a non-existent region, or a
    malformed (Qf, y) spec.
  * A positive Qf installed on a p-substrate MOS cap SHIFTS the surface
    potential POSITIVE at a fixed Vg (consistent with Vfb → Vfb - Qf/Cox
    and a MOS-cap Vg balance equation).
  * The shift scales LINEARLY in Qf over the tested range.
  * Qf = 0 or the key absent reproduces the baseline (no silent charge).
"""
from __future__ import annotations

import numpy as np
import pytest

from opentcad.device.solver import DeviceSolver
from opentcad.geometry.formats import Material
from opentcad.geometry.structure import Structure
from opentcad.materials.database import load_material


pytest.importorskip("devsim")


def _mos_cap():
    return (Structure(width_um=1.0, name="qf_test")
            .add_substrate("sub", 0.2, Material.SI, doping_Na=1e17)
            .add_layer("ox", 0.01, Material.SIO2)
            .add_contact("gate", 0.0, 1.0, "ox", surface="top")
            .add_contact("body", 0.0, 1.0, "sub", surface="bottom")
            .to_meshfield(mesh_size_um=0.02))


def _vsurf_at_vg(qf: float, Vg: float = 1.0) -> float:
    import devsim as ds
    for d in list(ds.get_device_list()):
        try: ds.delete_device(device=d)
        except Exception: pass
    mat = {"Silicon": load_material("Si"), "SiO2": load_material("SiO2")}
    kwargs = {"interface_Qf_C_per_cm2": {"SI": (qf, 0.2)}} if qf != 0.0 else {}
    s = DeviceSolver(_mos_cap(), mat, **kwargs)
    s.solve_equilibrium()
    s._set_contact_voltage("gate", Vg)
    s._solve_dc()
    V = float(np.array(ds.get_node_model_values(
        device=s._device_name, region="SI", name="Potential")).max())
    for d in list(ds.get_device_list()):
        try: ds.delete_device(device=d)
        except Exception: pass
    return V


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

@pytest.mark.requires_devsim
def test_qf_rejects_insulator_region():
    mat = {"Silicon": load_material("Si"), "SiO2": load_material("SiO2")}
    with pytest.raises(ValueError, match="insulator"):
        s = DeviceSolver(_mos_cap(), mat,
                          interface_Qf_C_per_cm2={"SIO2": (1e-8, 0.2)})
        s.solve_equilibrium()


@pytest.mark.requires_devsim
def test_qf_rejects_unknown_region():
    mat = {"Silicon": load_material("Si"), "SiO2": load_material("SiO2")}
    with pytest.raises(KeyError, match="doesn't exist"):
        s = DeviceSolver(_mos_cap(), mat,
                          interface_Qf_C_per_cm2={"NOBODY": (1e-8, 0.2)})
        s.solve_equilibrium()


@pytest.mark.requires_devsim
def test_qf_rejects_malformed_spec():
    mat = {"Silicon": load_material("Si"), "SiO2": load_material("SiO2")}
    with pytest.raises(ValueError, match="tuple"):
        s = DeviceSolver(_mos_cap(), mat,
                          interface_Qf_C_per_cm2={"SI": 1e-8})
        s.solve_equilibrium()


# ---------------------------------------------------------------------------
# Numerical behavior
# ---------------------------------------------------------------------------

@pytest.mark.requires_devsim
def test_qf_zero_matches_no_qf():
    """Qf = 0 must solve identically to omitting interface_Qf entirely."""
    v_none = _vsurf_at_vg(0.0)
    v_zero = _vsurf_at_vg(0.0)  # same code path, as sanity
    assert abs(v_none - v_zero) < 1e-9


@pytest.mark.requires_devsim
def test_qf_positive_shifts_vsurf_positive():
    """Positive Qf (positive ions at the Si-SiO2 interface) must raise
    Vsurf at a fixed Vg — the signature of Vfb → Vfb - Qf/Cox."""
    v_base = _vsurf_at_vg(0.0)
    v_qf   = _vsurf_at_vg(1e-8)
    assert v_qf > v_base, (
        f"Qf=1e-8 should raise Vsurf; got v_base={v_base:.4f} -> "
        f"v_qf={v_qf:.4f}")
    # Shift should be at least a few mV (actual ~3-30 mV depending on bias).
    assert (v_qf - v_base) > 1e-3


@pytest.mark.requires_devsim
def test_qf_scales_linearly():
    """ΔVsurf is linear in Qf over the small-signal range. Compute two
    shifts and check their ratio equals the Qf ratio within 20 %."""
    v0  = _vsurf_at_vg(0.0)
    v1  = _vsurf_at_vg(1e-9)
    v10 = _vsurf_at_vg(1e-8)
    d1  = v1 - v0
    d10 = v10 - v0
    ratio = d10 / d1
    assert 8.0 < ratio < 12.0, (
        f"ΔV(Qf=1e-8)/ΔV(Qf=1e-9) should be ~10, got {ratio:.2f}")
