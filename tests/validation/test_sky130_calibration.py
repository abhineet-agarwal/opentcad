"""SKY130 calibration (Phase 3): electrostatics from the body effect, then
surface mobility.

Fast tests pin the targets (the saved SkyWater curves and body-effect table),
the 1-D electrostatics model, and the residual definition. The slow test
re-simulates the calibrated device and checks it reproduces the recorded fit.
"""
import json
import math

import numpy as np
import pytest

from validation.sky130 import calibrate as cal
from validation.sky130 import vth_check as v

EPS0 = 8.8541878128e-14
Q = 1.602176634e-19


def test_saved_curves_reproduce_the_reference_table():
    vg, il = cal.reference_curve(cal.VDS_LIN)
    m = cal.linear_metrics(vg, il)
    row = v.load_reference(1.0)
    # The curves are every 10 mV; the table was extracted every 2 mV.
    assert m["Vth_lin_cc_V"] == pytest.approx(row["Vth_lin_cc_V"], abs=2e-3)
    assert m["Vth_lin_ELR_V"] == pytest.approx(row["Vth_lin_ELR_V"], abs=5e-3)
    assert m["SS_min_mV_per_dec"] == pytest.approx(row["SS_min_mV_per_dec"], rel=0.02)
    assert m["gm_max_lin_S_per_um"] * cal.W_REF_UM == pytest.approx(row["gm_max_lin_S"], rel=0.01)
    vs, isat = cal.reference_curve(cal.VDS_SAT)
    assert isat[-1] == pytest.approx(row["Ion_sat_A_per_um"], rel=1e-5)
    assert vs[-1] == pytest.approx(1.8)


def test_body_effect_table_starts_at_the_zero_bias_threshold():
    vbs, vth = cal.reference_body_effect()
    assert vbs[0] == 0.0 and vth[0] == pytest.approx(v.load_reference(1.0)["Vth_lin_cc_V"])
    assert np.all(np.diff(vth) > 0)                     # reverse bias raises Vth


def test_1d_body_effect_matches_the_textbook_for_uniform_doping():
    z = v.design_grid()
    n = 4e17
    na = np.full_like(z, n)
    phi2 = 2 * v._thermal_voltage() * math.log(n / 9.65e9)
    cox = 3.9 * EPS0 / (v.TOX_UM * 1e-4)
    k = math.sqrt(2 * Q * 11.7 * EPS0 * n) / cox
    vth0 = cal.vth_1d(z, na, 0.0)
    for vbs in (-0.45, -1.8):
        expected = k * (math.sqrt(phi2 - vbs) - math.sqrt(phi2))
        assert cal.vth_1d(z, na, vbs) - vth0 == pytest.approx(expected, abs=2e-3)
    # At zero bias it is the Phase 2 design formula.
    assert vth0 == pytest.approx(v.long_channel_vth(z, na, v.TOX_UM, v.n_poly_flat_band_shift_V())[0],
                                 abs=1e-9)


def test_phase2_stand_in_without_drive_in_is_the_phase2_profile():
    z = v.design_grid()
    p2 = cal.phase2_design()
    assert np.allclose(cal.channel_acceptors_cm3(z, p2), v.channel_acceptors_cm3(z, p2["vt_dose_cm2"]),
                       rtol=1e-9)
    # A drive-in conserves the implanted dose and lowers the peak.
    a = cal.vt_implant_cm3(z, 1e13, 0.0)
    b = cal.vt_implant_cm3(z, 1e13, 300.0)
    assert np.trapezoid(b, z) == pytest.approx(np.trapezoid(a, z), rel=1e-3)
    assert b.max() < 0.8 * a.max()


def test_residuals_vanish_against_the_reference_itself():
    vg, il = cal.reference_curve()
    assert np.max(np.abs(cal.curve_residuals(vg, il))) < 1e-12
    # A uniformly 20 % higher current also lowers Vth_cc (by SS·log10 1.2 ≈ 7 mV),
    # so at equal overdrive it reads as +20 % only well above threshold.
    r = cal.curve_residuals(vg, il * 1.2)
    assert np.all((r > 0) & (r <= 0.2)) and np.all(np.diff(r) > 0)
    assert r[-1] == pytest.approx(0.2, abs=0.01)


def test_residuals_refuse_a_curve_without_room_for_the_overdrive():
    vg, il = cal.reference_curve()
    later = np.interp(vg - 0.3, vg, il, left=il[0])      # Vth_cc 0.3 V higher
    with pytest.raises(ValueError, match="no room"):
        cal.curve_residuals(vg, later)


def _recorded():
    if not cal.RESULT_JSON.exists():
        pytest.skip("run python -m validation.sky130.calibrate first")
    return json.loads(cal.RESULT_JSON.read_text())


def test_calibrated_electrostatics_match_the_body_effect():
    rec = _recorded()["electrostatics"]
    vbs, vth_ref = cal.reference_body_effect()
    assert rec["target"]["Vth_lin_cc_V"] == vth_ref.tolist()
    # The 1-D model reproduces what was recorded and agrees with the 2-D check.
    assert np.allclose(cal.body_effect_1d(rec["design"], vbs), rec["Vth_1d_V"], atol=1e-6)
    assert np.max(np.abs(np.subtract(rec["Vth_2d_V"], rec["Vth_1d_V"]))) < 0.01
    # Two stand-in parameters can't follow SkyWater's curvature exactly (18.7 mV
    # rms when recorded), but they remove most of the Phase 2 stand-in's error.
    rms_p2 = np.sqrt(np.mean((np.asarray(rec["phase2"]["Vth_2d_V"]) - vth_ref) ** 2)) * 1e3
    assert rec["rms_2d_mV"] < 25.0 and rms_p2 > 5 * rec["rms_2d_mV"]


def test_fitted_variant_records_its_provenance():
    if not cal.VARIANT_FILE.exists():
        pytest.skip("run python -m validation.sky130.calibrate mobility first")
    from opentcad import plugins
    from opentcad.materials.database import load_material
    plugins._reset_for_tests()
    try:
        plugins.register_data_dir("materials", cal.MATERIALS_DIR)
        si = load_material("Si", process=cal.PROCESS)
    finally:
        plugins._reset_for_tests()
    c = si.raw["calibration"]
    assert c["status"] == "fitted" and "nfet_01v8" in c["calibrated_against"]
    assert set(c["fitted"]) == {p.name for p in cal.MOBILITY}
    for name, entry in c["fitted"].items():
        block, key = name.split(".")
        assert getattr(getattr(si, block), key) == pytest.approx(entry["value"], rel=1e-3)
    assert si.defaulted == []


@pytest.mark.slow
@pytest.mark.requires_devsim
def test_calibrated_device_reproduces_the_recorded_fit():
    rec = _recorded()
    if "mobility" not in rec:
        pytest.skip("run python -m validation.sky130.calibrate mobility first")
    fitted = {p["name"]: p["fitted"] for p in rec["mobility"]["fit"]["parameters"]}
    r = cal.mobility_residuals(fitted)
    assert np.sqrt(np.mean(r ** 2)) == pytest.approx(rec["mobility"]["fit"]["rms"], abs=2e-3)


def test_recorded_report_meets_the_phase3_exit_metrics():
    """calibration.json's report: the calibrated device's Vth, SS and Ion are
    within 10 % of SkyWater (Phase 3 exit), with the default Canali force."""
    report = json.loads(cal.RESULT_JSON.read_text())["report"]["calibrated"]["metrics"]
    for key in ("Vth_lin_ELR_V", "Vth_lin_cc_V", "SS_min_mV_per_dec", "Ion_sat_A_per_um"):
        assert abs(report[key]["rel_error"]) < 0.10, key
