"""
Phase 3 calibration against SkyWater's sky130_fd_pr__nfet_01v8: the
electrostatics first, then the surface mobility.

The device is the Phase 2 NMOS of ``vth_check.py``: SkyWater's gate oxide,
p-well and junction depth, at L = 1 µm. The targets come from SkyWater's tt
model card evaluated in ngspice (``extract_reference.py``):
``nfet_01v8_tt_reference.json`` (thresholds, including the body effect) and
``nfet_01v8_tt_curves.json`` (Id–Vgs curves). Results go to
``calibration.json``.

Stage 1, electrostatics. SkyWater doesn't publish its threshold-adjust
implant. Phase 2 used a stand-in, boron at 10 keV with the dose set by a 1-D
design formula. That stand-in matches the zero-bias threshold but has twice
SkyWater's body effect: its boron peaks at 2×10¹⁸ cm⁻³ just inside the
depletion region. The body effect depends only on the depletion charge, not
on mobility, so it identifies the profile. Two stand-in parameters are fitted:
the dose and a drive-in anneal at 1000 °C that spreads the implant. The
energy stays at 10 keV, the shallowest the boron tables cover. The target is
SkyWater's constant-current threshold at five body biases. The fit uses the
1-D depletion approximation; the 2-D simulation then checks it, and the 1-D
target is shifted once by the 2-D vs 1-D difference.

Stage 2, mobility. The Lombardi electron coefficients are fitted to
SkyWater's linear Id–Vgs (Vds = 50 mV), at equal gate overdrive above each
curve's own constant-current threshold. Comparing at equal overdrive keeps
any remaining threshold difference out of the mobility. Run ``sensitivity``
first: it shows which coefficients the curve can tell apart.

Every fitted value is effective. It absorbs what the simulation leaves out
(poly depletion, quantum confinement, the real implant and thermal history,
S/D series resistance), and holds only for this device, this mesh and 300 K.
The calibrated material file says so.

Run (each stage reads the previous one's result):
    python -m validation.sky130.calibrate electrostatics
    python -m validation.sky130.calibrate sensitivity
    python -m validation.sky130.calibrate scan
    python -m validation.sky130.calibrate mobility
    python -m validation.sky130.calibrate report
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import contextlib
import io
import json
import math
import multiprocessing
import os
import sys
import warnings
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.optimize import brentq

from opentcad.calibrate import Parameter, apply_overrides, fit, write_material_variant
from opentcad.device.extract import vth_constant_current, vth_max_gm
from opentcad.process.doping import moments_for, pearson_density
from opentcad.process.doping.anneal import diffusivity_intrinsic, temperature_celsius_to_kelvin
from opentcad.process.topography import Recipe
from validation.sky130 import vth_check as v

HERE = Path(__file__).resolve().parent
CURVES_JSON = HERE / "nfet_01v8_tt_curves.json"
RESULT_JSON = HERE / "calibration.json"
MATERIALS_DIR = HERE / "materials"           # register_data_dir("materials", MATERIALS_DIR)
PROCESS = "sky130"                           # load_material("Si", process="sky130")
VARIANT_FILE = MATERIALS_DIR / PROCESS / "Si.yaml"

L_UM = 1.0
W_REF_UM = 10.0
VDS_LIN = 0.05
VDS_SAT = 1.8
I_CRIT_A_PER_UM = 100e-9 / L_UM              # 100 nA·W/L, per µm of width
MESH_UM = 0.01                               # as the Phase 2 check
FIT_VGS_STEP = 0.05
REPORT_VGS_STEP = 0.02                       # linear curves: max-gm needs it
REPORT_SAT_VGS_STEP = 0.05                   # saturation: Ion and a constant-current Vth only

# ---- Stage 1: the stand-in threshold implant --------------------------------
VT_SPECIES = "B"
VT_ENERGY_KEV = 10.0                         # the shallowest the B tables cover
VT_DRIVE_C = 1000.0
ELECTROSTATICS = [
    Parameter("vt_dose_cm2", 7.78e12, 1e11, 1e14),
    Parameter("vt_drive_s", 30.0, 1.0, 3600.0),
]

# ---- Stage 2: surface mobility ----------------------------------------------
OVERDRIVE_V = np.round(np.arange(0.10, 1.1001, 0.05), 3)
#: The fitted coefficients. ``initial`` is the literature value; the fit
#: starts from the best point of the ``scan`` stage when there is one.
MOBILITY = [
    Parameter("mobility_lombardi.C_e", 1.70e4, 1e3, 1e6),
    Parameter("mobility_lombardi.delta_e", 3.58e18, 1e16, 1e20),
    # γ is an exponent of E ≈ 5e5 V/cm: a 0.01 step changes μ_sr by ~14 %.
    Parameter("mobility_lombardi.A_e", 2.58, 2.0, 3.2, log=False, step=0.01),
]
SENSITIVITY = {                              # candidate → changed value
    "mobility_lombardi.B_e": 3.61e7 * 1.5,
    "mobility_lombardi.C_e": 1.70e4 * 1.5,
    "mobility_lombardi.delta_e": 3.58e18 * 1.5,
    "mobility_lombardi.A_e": 2.58 + 0.05,
    "mobility_lombardi.tau_e": 0.0233 * 1.5,
}


# =============================================================================
# Reference
# =============================================================================
def reference_curve(vds: float = VDS_LIN, l_um: float = L_UM) -> tuple[np.ndarray, np.ndarray]:
    """SkyWater's Id–Vgs [V, A/µm] at ``vds`` (50 mV or 1.8 V)."""
    ref = json.loads(CURVES_JSON.read_text())
    key = {VDS_LIN: "Id_lin_A", VDS_SAT: "Id_sat_A"}[vds]
    for row in ref["curves"]:
        if np.isclose(row["L_um"], l_um):
            return (np.asarray(ref["Vgs_V"], float),
                    np.asarray(row[key], float) / ref["conditions"]["W_um"])
    raise KeyError(f"no reference curve for L = {l_um} µm")


def reference_body_effect(l_um: float = L_UM) -> tuple[np.ndarray, np.ndarray]:
    """SkyWater's constant-current threshold [V] at each body bias [V]."""
    for row in json.loads(v.REFERENCE_JSON.read_text())["body_effect"]:
        if np.isclose(row["L_um"], l_um):
            return np.asarray(row["Vbs_V"], float), np.asarray(row["Vth_lin_cc_V"], float)
    raise KeyError(f"no body-effect row for L = {l_um} µm")


# =============================================================================
# Stage 1: 1-D electrostatics
# =============================================================================
def _sigma2_um2(species: str, temperature_C: float, time_s: float) -> float:
    D = diffusivity_intrinsic(species, temperature_celsius_to_kelvin(temperature_C))
    return 2.0 * D * time_s / v.UM_TO_CM ** 2


def vt_implant_cm3(z_um, dose_cm2: float, drive_s: float) -> np.ndarray:
    """The stand-in threshold implant after its drive-in and the S/D anneal
    (intrinsic diffusion: the two Gaussian spreads add), no-flux at the Si
    surface."""
    depth_um, dens_per_um = pearson_density(moments_for(VT_SPECIES, VT_ENERGY_KEV))
    prof = dose_cm2 * np.interp(z_um + v.TOX_UM, depth_um, dens_per_um,
                                left=0.0, right=0.0) / v.UM_TO_CM
    s2 = (_sigma2_um2(VT_SPECIES, VT_DRIVE_C, drive_s)
          + _sigma2_um2(VT_SPECIES, v.ANNEAL_T_C, v.ANNEAL_T_S))
    return gaussian_filter1d(prof, math.sqrt(s2) / float(z_um[1] - z_um[0]), mode="mirror")


def channel_acceptors_cm3(z_um, design: dict) -> np.ndarray:
    return (v.BACKGROUND_NA_CM3 + v.pwell_cm3(z_um)
            + vt_implant_cm3(z_um, design["vt_dose_cm2"], design["vt_drive_s"]))


def vth_1d(z_um, na_cm3, vbs: float = 0.0) -> float:
    """Depletion-approximation threshold [V] with the body at ``vbs``.

    As ``vth_check.long_channel_vth``, with the reverse body bias added to the
    band bending across the depletion region: ψ(0) − ψ(W) = φ_F(N_s) +
    φ_F(N(W)) − vbs."""
    bs = v._si()
    vt = v._thermal_voltage()
    eps_si = bs.permittivity_relative * v.EPS0_F_CM
    z = np.asarray(z_um, float) * v.UM_TO_CM
    na = np.asarray(na_cm3, float)
    phi = vt * np.log(na / bs.ni_cm3_300K)
    dz = np.diff(z)
    q1 = np.concatenate([[0.0], np.cumsum(0.5 * (na[1:] + na[:-1]) * dz)])
    zn = z * na
    m1 = np.concatenate([[0.0], np.cumsum(0.5 * (zn[1:] + zn[:-1]) * dz)])
    g = v.Q_C * m1 / eps_si - (phi[0] + phi - vbs)
    k = np.flatnonzero(g >= 0.0)
    if len(k) == 0 or k[0] == 0:
        raise ValueError("depletion edge not bracketed by the design grid")
    k = int(k[0])
    t = -g[k - 1] / (g[k] - g[k - 1])
    q_b = v.Q_C * (q1[k - 1] + t * (q1[k] - q1[k - 1]))
    c_ox = v._eps_ox_F_cm() / (v.TOX_UM * v.UM_TO_CM)
    return float(v.n_poly_flat_band_shift_V() + phi[0] + q_b / c_ox)


def body_effect_1d(design: dict, vbs_list) -> np.ndarray:
    z = v.design_grid()
    na = channel_acceptors_cm3(z, design)
    return np.array([vth_1d(z, na, vb) for vb in vbs_list])


def sd_energy_keV(design: dict) -> float:
    """As energy [keV] whose annealed S/D junction lands at SkyWater's 0.1 µm."""
    z = v.design_grid()
    na = channel_acceptors_cm3(z, design)

    def miss(e_keV):
        nd = v.implant_profile_cm3(v.SD_SPECIES, e_keV, v.SD_DOSE_CM2, z)
        return v.junction_depth_um(z, nd, na) - v.SD_XJ_UM

    return float(brentq(miss, 10.0, 200.0, xtol=1e-3))


def _electrostatics_residuals(values: dict, offset_V: float = 0.0) -> np.ndarray:
    vbs, vth_ref = reference_body_effect()
    return body_effect_1d(values, vbs) - (vth_ref - offset_V)


# =============================================================================
# Stage 1 and 2: 2-D device
# =============================================================================
def phase2_design() -> dict:
    """The Phase 2 stand-in, as a design dict (no drive-in)."""
    return {"vt_dose_cm2": v.design_vt_dose(v.load_reference(L_UM)["Vth_lin_ELR_V"]),
            "vt_drive_s": 0.0}


def build_recipe(design: dict) -> Recipe:
    src = (0.0, v.W_SD_UM)
    drn = (v.WIDTH_UM - v.W_SD_UM, v.WIDTH_UM)
    e_sd = sd_energy_keV(design)
    r = Recipe("sky130_nfet_calibrated").implant(VT_SPECIES, VT_ENERGY_KEV, design["vt_dose_cm2"])
    if design["vt_drive_s"] > 0:
        r = r.anneal(VT_DRIVE_C, design["vt_drive_s"])
    return (r.implant(v.SD_SPECIES, e_sd, v.SD_DOSE_CM2, window_x_um=src)
             .implant(v.SD_SPECIES, e_sd, v.SD_DOSE_CM2, window_x_um=drn)
             .anneal(v.ANNEAL_T_C, v.ANNEAL_T_S))


def build_meshfield(design: dict, mesh_size_um: float = MESH_UM):
    from opentcad.process import run_recipe
    mf = run_recipe(v.build_structure(v.n_poly_flat_band_shift_V()), build_recipe(design),
                    mesh_size_um=mesh_size_um).meshfield
    v.add_pwell(mf)
    return mf


def _physics(saturation: bool):
    from opentcad.device.models import Canali, Klaassen, Lombardi
    from opentcad.device.physics import PhysicsConfig
    if saturation:   # velocity saturation acts on the full (surface) mobility
        return PhysicsConfig(mobility=Canali(base=Lombardi(base=Klaassen())))
    return PhysicsConfig(mobility=Lombardi(base=Klaassen()))


def simulate(design: dict, values: dict | None = None, *, vds: float = VDS_LIN,
             vbs: float = 0.0, vgs_end: float = v.VGS_END, vgs_step: float = FIT_VGS_STEP,
             mesh_size_um: float = MESH_UM,
             saturation: bool | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Id–Vgs [V, A/µm] of the NMOS built with ``design`` (the threshold
    implant), with silicon's parameters changed by ``values``
    (``{"block.field": value}``), at body bias ``vbs``. Velocity saturation is
    on above Vds = 0.5 V unless ``saturation`` says otherwise."""
    from opentcad.device.solver import DeviceSolver
    from opentcad.materials.database import load_material
    if saturation is None:
        saturation = vds > 0.5
    si = apply_overrides(load_material("Si"), values or {})
    solver = DeviceSolver(build_meshfield(design, mesh_size_um),
                          {"Silicon": si, "SiO2": load_material("SiO2")},
                          physics=_physics(saturation))
    try:
        with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            vgs, ids = solver.iv_sweep("gate", "source", v_start=0.0, v_end=vgs_end,
                                       v_step=vgs_step,
                                       hold_contacts={"drain": vds, "body": vbs},
                                       measure_contact="drain")
    finally:
        solver.close()
    return np.asarray(vgs, float), np.abs(np.asarray(ids, float)) * 1e-4   # A/cm → A/µm


def _body_effect_case(args) -> float:
    design, vbs = args
    vg, i = simulate(design, vbs=vbs, vgs_end=1.4)
    return vth_constant_current(vg, i, I_CRIT_A_PER_UM)


def body_effect_2d(design: dict, vbs_list, workers: int) -> np.ndarray:
    return np.array(_pool_map(_body_effect_case, [(design, vb) for vb in vbs_list], workers))


# =============================================================================
# Stage 2: mobility residuals and metrics
# =============================================================================
def curve_residuals(vgs, ids) -> np.ndarray:
    """Relative Id difference from SkyWater at equal overdrive above Vth_cc."""
    vr, ir = reference_curve(VDS_LIN)
    vt_sim = vth_constant_current(vgs, ids, I_CRIT_A_PER_UM)
    vt_ref = vth_constant_current(vr, ir, I_CRIT_A_PER_UM)
    if vt_sim + OVERDRIVE_V[-1] > vgs[-1]:
        raise ValueError(f"Vth_cc {vt_sim:.3f} V leaves no room for the overdrive range")
    return np.interp(vt_sim + OVERDRIVE_V, vgs, ids) / np.interp(vt_ref + OVERDRIVE_V, vr, ir) - 1.0


def calibrated_design() -> dict:
    """The stage-1 result (``calibration.json``)."""
    if not RESULT_JSON.exists() or "electrostatics" not in json.loads(RESULT_JSON.read_text()):
        raise FileNotFoundError("run the electrostatics stage first")
    return json.loads(RESULT_JSON.read_text())["electrostatics"]["design"]


def mobility_residuals(values: dict) -> np.ndarray:
    """The mobility fit's residual function (module-level, for the workers)."""
    return curve_residuals(*simulate(calibrated_design(), values))


def subthreshold_swing(vgs, ids, i_upper: float = I_CRIT_A_PER_UM) -> float:
    """Minimum dVgs/dlog10(Id) [mV/dec] below Id = 100 nA·W/L, as
    extract_reference does (its 1e-13 A floor is for W = 10 µm)."""
    sel = (ids > 1e-13 / W_REF_UM) & (ids < i_upper)
    s = np.gradient(vgs[sel], np.log10(ids[sel])) * 1e3
    s = s[np.isfinite(s) & (s > 0)]
    return float(s.min())


def linear_metrics(vgs, ids) -> dict:
    gm = np.gradient(ids, vgs)
    return {"Vth_lin_ELR_V": vth_max_gm(vgs, ids, VDS_LIN),
            "Vth_lin_cc_V": vth_constant_current(vgs, ids, I_CRIT_A_PER_UM),
            "SS_min_mV_per_dec": subthreshold_swing(vgs, ids),
            "gm_max_lin_S_per_um": float(gm.max()),
            "Vgs_at_gm_max_V": float(vgs[int(gm.argmax())])}


def reference_metrics() -> dict:
    vr, ir = reference_curve(VDS_LIN)
    out = linear_metrics(vr, ir)
    vs, isat = reference_curve(VDS_SAT)
    out["Ion_sat_A_per_um"] = float(isat[-1])
    out["Vth_sat_cc_V"] = vth_constant_current(vs, isat, I_CRIT_A_PER_UM)
    return out


# =============================================================================
# Stages
# =============================================================================
def _pool_map(fn, args: list, workers: int) -> list:
    with cf.ProcessPoolExecutor(max_workers=workers,
                                mp_context=multiprocessing.get_context("spawn")) as pool:
        return list(pool.map(fn, args))


def _load() -> dict:
    return json.loads(RESULT_JSON.read_text()) if RESULT_JSON.exists() else {}


def _save(section: str, data) -> None:
    out = _load()
    out[section] = data
    RESULT_JSON.write_text(json.dumps(out, indent=1) + "\n")


def _fit_1d(offset_V: float):
    def res(values):
        return _electrostatics_residuals(values, offset_V)
    return fit(res, ELECTROSTATICS, max_iterations=50, tolerance=1e-6, log=None)


def stage_electrostatics(workers: int) -> dict:
    vbs, vth_ref = reference_body_effect()
    p2 = phase2_design()
    p2_2d = body_effect_2d(p2, vbs, workers)
    first = _fit_1d(0.0)
    d1 = {k: float(val) for k, val in first.values.items()}
    first_2d = body_effect_2d(d1, vbs, workers)
    offset = float(np.mean(first_2d - body_effect_1d(d1, vbs)))   # 2-D minus 1-D
    second = _fit_1d(offset)
    design = {k: float(val) for k, val in second.values.items()}
    final_2d = body_effect_2d(design, vbs, workers)
    z = v.design_grid()
    out = {
        "target": {"Vbs_V": vbs.tolist(), "Vth_lin_cc_V": vth_ref.tolist(),
                   "source": v.REFERENCE_JSON.name + " body_effect, L = 1 µm"},
        "phase2": {"design": p2, "Vth_2d_V": p2_2d.tolist(),
                   "Vth_1d_V": body_effect_1d(p2, vbs).tolist()},
        "fit_1d": {"first": first.to_dict(), "offset_2d_minus_1d_V": offset,
                   "second": second.to_dict()},
        "design": design,
        "sd_energy_keV": sd_energy_keV(design),
        "Vth_1d_V": body_effect_1d(design, vbs).tolist(),
        "Vth_2d_V": final_2d.tolist(),
        "rms_2d_mV": float(np.sqrt(np.mean((final_2d - vth_ref) ** 2)) * 1e3),
        "channel_profile": {"z_um": z[::20].tolist(),
                            "Na_phase2_cm3": channel_acceptors_cm3(z, p2)[::20].tolist(),
                            "Na_calibrated_cm3": channel_acceptors_cm3(z, design)[::20].tolist()},
    }
    _save("electrostatics", out)
    print(f"Phase 2 stand-in: Vth_cc(Vbs) 2-D {np.round(p2_2d, 3)}")
    print(f"SkyWater:                        {np.round(vth_ref, 3)}")
    print(f"calibrated: dose {design['vt_dose_cm2']:.3e} cm⁻², drive-in "
          f"{design['vt_drive_s']:.1f} s at {VT_DRIVE_C:g} °C → 2-D {np.round(final_2d, 3)} "
          f"(rms {out['rms_2d_mV']:.1f} mV; 1-D→2-D offset {offset * 1e3:+.1f} mV)")
    return out


def _mobility_case(values: dict) -> list:
    return mobility_residuals(values).tolist()


def stage_sensitivity(workers: int) -> dict:
    cases = [{}] + [{k: val} for k, val in SENSITIVITY.items()]
    out = _pool_map(_mobility_case, cases, workers)
    base = np.asarray(out[0])
    D = np.column_stack([np.asarray(r) - base for r in out[1:]])
    norms = np.linalg.norm(D, axis=0)
    cos = (D.T @ D) / np.outer(norms, norms)
    names = [k.split(".")[-1] for k in SENSITIVITY]
    print(f"literature values: rms {np.sqrt(np.mean(base ** 2)):.4f}")
    print("overdrive [V]: " + " ".join(f"{x:5.2f}" for x in OVERDRIVE_V[::4]))
    print(f"{'base':>24}: " + " ".join(f"{x:+5.2f}" for x in base[::4]))
    for n, val, d in zip(names, SENSITIVITY.values(), D.T):
        print(f"{n + f' → {val:.3g}':>24}: " + " ".join(f"{x:+5.2f}" for x in d[::4]))
    print("cosine similarity of the responses (1 = the curve can't tell them apart):")
    print("        " + " ".join(f"{n:>8}" for n in names))
    for n, row in zip(names, cos):
        print(f"{n:>8}" + " ".join(f"{x:8.3f}" for x in row))
    data = {"steps": SENSITIVITY, "base": base.tolist(),
            "responses": {k: d.tolist() for k, d in zip(SENSITIVITY, D.T)},
            "cosine": np.round(cos, 4).tolist()}
    _save("sensitivity", data)
    return data


SCAN = {"mobility_lombardi.C_e": [1.70e4, 5.1e4, 1e6],          # literature, ×3, the bound
        "mobility_lombardi.delta_e": [3.58e18, 7.16e17, 1.79e17]}  # literature, ÷5, ÷20


def stage_scan(workers: int) -> dict:
    """The residual on a coarse grid of the two mobility coefficients that
    act most differently (phonon C_e, surface-roughness delta_e). The local
    sensitivity can't show what delta_e does far from the literature value,
    where surface roughness starts to limit the mobility."""
    (n1, v1), (n2, v2) = SCAN.items()
    cases = [{n1: a, n2: b} for a in v1 for b in v2]
    out = _pool_map(_mobility_case, cases, workers)
    rows = [{"values": c, "rms": float(np.sqrt(np.mean(np.square(r)))), "residuals": r}
            for c, r in zip(cases, out)]
    print("overdrive [V]: " + " ".join(f"{x:5.2f}" for x in OVERDRIVE_V[::4]))
    for row in rows:
        c = row["values"]
        print(f"C_e {c[n1]:8.3g}  delta_e {c[n2]:8.3g}: rms {row['rms']:.3f}  "
              + " ".join(f"{x:+5.2f}" for x in np.asarray(row["residuals"])[::4]))
    _save("scan", {"grid": SCAN, "rows": rows})
    return {"rows": rows}


def _start() -> list[Parameter]:
    """MOBILITY, starting from the scan's best grid point where it has one."""
    rows = _load().get("scan", {}).get("rows", [])
    best = min(rows, key=lambda r: r["rms"])["values"] if rows else {}
    return [Parameter(p.name, best.get(p.name, p.initial), p.lower, p.upper, p.log, p.step)
            for p in MOBILITY]


def stage_mobility(workers: int) -> dict:
    calibrated_design()                       # fail early without stage 1
    start = _start()
    result = fit(mobility_residuals, start, workers=workers, max_iterations=10)
    print(f"fit: rms {result.initial_rms:.4f} → {result.rms:.4f}  ({result.message})")
    data = {"target": {"curves": CURVES_JSON.name, "L_um": L_UM, "Vds_V": VDS_LIN,
                       "overdrive_V": OVERDRIVE_V.tolist(),
                       "residual": "Id_sim(Vth_cc,sim + ov) / Id_ref(Vth_cc,ref + ov) - 1"},
            "mesh_size_um": MESH_UM, "fit_vgs_step_V": FIT_VGS_STEP,
            "fit": result.to_dict(), "residuals": result.residuals.tolist(),
            "history": [{"values": e.values, "rms": e.rms} for e in result.evaluations]}
    _save("mobility", data)
    from opentcad.materials.database import load_material
    design = calibrated_design()
    write_material_variant(VARIANT_FILE, load_material("Si"), result.values, calibration={
        "status": "fitted",
        "calibrated_against": "SkyWater sky130_fd_pr__nfet_01v8, tt model card (BSIM4 in "
                              "ngspice), L = 1 µm, W = 10 µm, Vds = 50 mV, 300 K",
        "fitted": {p.name: {"value": float(f"{result.values[p.name]:.4g}"),
                            "literature": p.initial,
                            "fit_started_at": s.initial}
                   for p, s in zip(MOBILITY, start)},
        "fitted_with": "validation/sky130/calibrate.py",
        "result": "validation/sky130/calibration.json",
        "valid_for": (f"Lombardi(base=Klaassen()) on the calibrated NMOS of "
                      f"validation/sky130/calibrate.py (B {VT_ENERGY_KEV:g} keV, "
                      f"{design['vt_dose_cm2']:.3g} cm-2, {design['vt_drive_s']:.3g} s at "
                      f"{VT_DRIVE_C:g} C), {MESH_UM * 1e3:g} nm mesh, 300 K"),
        "notes": "Effective values: they absorb poly depletion, quantum confinement, "
                 "the real implant and thermal history and series-resistance "
                 "differences, which the simulation leaves out.",
    })
    return data


def _report_case(args) -> tuple:
    design, values, vds = args
    step = REPORT_VGS_STEP if vds == VDS_LIN else REPORT_SAT_VGS_STEP
    vgs, ids = simulate(design, values, vds=vds, vgs_step=step)
    return vgs.tolist(), ids.tolist()


def stage_report(workers: int) -> dict:
    res = _load()
    design = calibrated_design()
    fitted = {p["name"]: p["fitted"] for p in res["mobility"]["fit"]["parameters"]}
    p2 = phase2_design()
    setups = {"phase2": (p2, {}), "electrostatics": (design, {}), "calibrated": (design, fitted)}
    cases = [(d, vals, vds) for d, vals in setups.values() for vds in (VDS_LIN, VDS_SAT)]
    runs = iter(_pool_map(_report_case, cases, workers))
    ref = reference_metrics()
    out = {}
    for label in setups:
        vg, il = map(np.asarray, next(runs))
        vs, isat = map(np.asarray, next(runs))
        m = linear_metrics(vg, il)
        m["Ion_sat_A_per_um"] = float(isat[-1])
        m["Vth_sat_cc_V"] = vth_constant_current(vs, isat, I_CRIT_A_PER_UM)
        out[label] = {
            "metrics": {k: {"opentcad": m[k], "sky130": ref[k], "rel_error": (m[k] - ref[k]) / ref[k]}
                        for k in m if k in ref},
            "curve_rms": float(np.sqrt(np.mean(curve_residuals(vg, il) ** 2))),
            "curves": {"Vgs_V": vg.tolist(), "Id_lin_A_per_um": il.tolist(),
                       "Vgs_sat_V": vs.tolist(), "Id_sat_A_per_um": isat.tolist()}}
    _save("report", out)
    for label, r in out.items():
        print(f"\n{label} (curve rms {r['curve_rms']:.3f}):")
        for k, row in r["metrics"].items():
            print(f"  {k:22s} {row['opentcad']:.4g} vs {row['sky130']:.4g}  "
                  f"({row['rel_error'] * 100:+.1f} %)")
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="SKY130 calibration (Phase 3)")
    ap.add_argument("stage", choices=["electrostatics", "sensitivity", "scan", "mobility", "report"])
    ap.add_argument("--workers", type=int, default=min(6, os.cpu_count() or 1))
    args = ap.parse_args(argv)
    {"electrostatics": stage_electrostatics, "sensitivity": stage_sensitivity,
     "scan": stage_scan, "mobility": stage_mobility,
     "report": stage_report}[args.stage](args.workers)


if __name__ == "__main__":
    sys.exit(main())
