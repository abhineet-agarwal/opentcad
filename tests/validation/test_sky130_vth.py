"""
SKY130 nfet_01v8 Vth check — the Phase 2 exit criterion.

Fast tests pin the 1-D design side (textbook limit, the SKY130 profile
reading, the n+ poly gate, the designed doses). The slow test runs the
full recipe → mesh → DEVSIM chain and asserts the ±20 % pass.
"""
import math

import numpy as np
import pytest

from validation.sky130 import vth_check as v

Q_C = 1.602176634e-19
EPS0 = 8.8541878128e-14


def test_reference_row_for_1um():
    row = v.load_reference(1.0)
    assert row["Vth_lin_ELR_V"] == pytest.approx(0.592, abs=1e-3)
    assert row["Vth_lin_cc_V"] == pytest.approx(0.547, abs=1e-3)
    with pytest.raises(KeyError):
        v.load_reference(0.33)


def test_uniform_doping_reduces_to_textbook_vth():
    z = v.design_grid()
    na = np.full_like(z, 1e18)
    vfb = v.n_poly_flat_band_shift_V()
    vth, w_um = v.long_channel_vth(z, na, v.TOX_UM, vfb)
    vt = v._thermal_voltage()
    phi_f = vt * math.log(1e18 / 9.65e9)
    eps_si = 11.7 * EPS0
    q_b = math.sqrt(2 * Q_C * eps_si * 1e18 * 2 * phi_f)
    c_ox = 3.9 * EPS0 / (v.TOX_UM * 1e-4)
    assert vth == pytest.approx((vfb - phi_f) + 2 * phi_f + q_b / c_ox, abs=1e-4)
    w_textbook_um = math.sqrt(2 * eps_si * 2 * phi_f / (Q_C * 1e18)) * 1e4
    assert w_um == pytest.approx(w_textbook_um, rel=1e-3)


def test_pwell_reading_matches_sky130_well_depth():
    # Reading Table 3a as N = Npk·exp(−((y − ypk)/ychar)²) must put the
    # well back at the background where SKY130 says it ends (PWVDIM).
    assert v.pwell_cm3(v.PWELL_DEPTH_UM) == pytest.approx(
        v.BACKGROUND_NA_CM3, rel=0.25)
    assert v.pwell_cm3(v.PWELL_PEAK_DEPTH_UM) == pytest.approx(v.PWELL_PEAK_CM3)
    assert v.pwell_cm3(0.0) < 1e-3 * v.PWELL_PEAK_CM3   # retrograde


def test_n_poly_gate_sits_near_conduction_band():
    vfb = v.n_poly_flat_band_shift_V()
    # Ec − Ei ≈ Eg/2 for silicon: about −0.56 V.
    assert -0.58 < vfb < -0.55


def test_designed_vt_dose_hits_target():
    target = v.load_reference()["Vth_lin_ELR_V"]
    dose = v.design_vt_dose(target)
    assert 1e12 < dose < 1e13                  # usual Vt-adjust range
    z = v.design_grid()
    vth, _ = v.long_channel_vth(z, v.channel_acceptors_cm3(z, dose),
                                v.TOX_UM, v.n_poly_flat_band_shift_V())
    assert vth == pytest.approx(target, abs=1e-4)


def test_designed_sd_energy_hits_published_junction_depth():
    dose = v.design_vt_dose(v.load_reference()["Vth_lin_ELR_V"])
    e_keV = v.design_sd_energy_keV(dose)
    z = v.design_grid()
    nd = v.implant_profile_cm3(v.SD_SPECIES, e_keV, v.SD_DOSE_CM2, z)
    xj = v.junction_depth_um(z, nd, v.channel_acceptors_cm3(z, dose))
    assert xj == pytest.approx(v.SD_XJ_UM, abs=1e-3)


@pytest.mark.requires_devsim
@pytest.mark.slow
@pytest.mark.integration
def test_sky130_nfet_vth_within_20_percent():
    # The documented settings (10 nm mesh, 20 mV steps). Coarser Vgs steps
    # can put the flat-topped gm maximum on the last bias point.
    res = v.run_check(verbose=False)
    assert res["passed"], (
        f"Vth {res['vth_tcad_elr_V']:.3f} V vs SKY130 "
        f"{res['vth_ref_elr_V']:.3f} V ({res['rel_error_elr']*100:+.1f} %)")
    cc_err = (res["vth_tcad_cc_V"] - res["vth_ref_cc_V"]) / res["vth_ref_cc_V"]
    assert abs(cc_err) <= v.PASS_TOLERANCE
    assert res["xj_tcad_um"] == pytest.approx(v.SD_XJ_UM, rel=0.1)
