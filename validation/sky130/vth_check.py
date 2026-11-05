"""
SKY130 nfet_01v8 threshold-voltage check — the Phase 2 exit criterion.

Builds a 1 µm NMOS from a process recipe, simulates Id–Vgs at
Vds = 50 mV, extracts Vth by max-gm linear extrapolation, and compares it
with the same extraction applied to SkyWater's own BSIM4 model card
(``nfet_01v8_tt_reference.json``, made by ``extract_reference.py``).
Pass: within 20 %.

Inputs taken from SkyWater
  * gate oxide 4.148 nm — ``toxe`` of the nfet_01v8 tt model card, the
    same in all 180 bins;
  * p-well profile N(y) = 4e17·exp(−((y − 0.42)/0.13)²) cm⁻³ and
    background 8e14 cm⁻³ — SKY130 design criteria (skywater-pdk
    docs/rules/assumptions.rst, Table 3a: PWPCONC, PWPCOORD, PWYCHAR,
    NWBCONC), placed as the final well profile;
  * S/D junction depth 0.1 µm (Table 3b, JCTD) — the S/D implant energy
    is chosen to land there.

Not published by SkyWater, so these are stand-ins
  * the threshold-adjust implant: boron at 10 keV, with the dose sized
    ONCE by the 1-D depletion-approximation formula below so that the
    design Vth equals the reference; the 2-D simulation is then run
    untuned;
  * S/D arsenic dose 2e15 cm⁻²; a 1000 °C / 10 s anneal;
  * n+ poly gate taken as degenerate (Fermi level at Ec, φ_m = χ_Si);
    poly depletion and quantum confinement are not modelled.

What passing means: the process→device chain agrees with first-order
design and lands in SkyWater's range. It does not show that OpenTCAD
predicts SkyWater's actual (unpublished) process.

Run:  python -m validation.sky130.vth_check
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.optimize import brentq

from opentcad.device.extract import vth_constant_current, vth_max_gm
from opentcad.geometry.formats import Material, MeshField, ProcessStep
from opentcad.geometry.structure import Structure
from opentcad.materials.database import load_material
from opentcad.process.doping import moments_for, pearson_density
from opentcad.process.doping.anneal import (diffusivity_intrinsic,
                                            temperature_celsius_to_kelvin)
from opentcad.process.topography import Recipe

HERE = Path(__file__).resolve().parent
REFERENCE_JSON = HERE / "nfet_01v8_tt_reference.json"

Q_C = 1.602176634e-19
KB_J = 1.380649e-23
EPS0_F_CM = 8.8541878128e-14
T_K = 300.0
UM_TO_CM = 1e-4

# ---- From SkyWater -----------------------------------------------------------
TOX_UM = 4.148e-3            # toxe, nfet_01v8 tt model card
L_GATE_UM = 1.0
VDS_LIN = 0.05
PWELL_PEAK_CM3 = 4e17        # PWPCONC
PWELL_PEAK_DEPTH_UM = 0.42   # PWPCOORD
PWELL_YCHAR_UM = 0.13        # PWYCHAR
BACKGROUND_NA_CM3 = 8e14     # NWBCONC (p-substrate background)
PWELL_DEPTH_UM = 0.75        # PWVDIM, used only as a consistency check
SD_XJ_UM = 0.1               # JCTD

# ---- Stand-ins ---------------------------------------------------------------
VT_SPECIES = "B"
VT_ENERGY_KEV = 10.0
SD_SPECIES = "As"
SD_DOSE_CM2 = 2e15
ANNEAL_T_C = 1000.0
ANNEAL_T_S = 10.0
PASS_TOLERANCE = 0.20

# ---- Simulation geometry -----------------------------------------------------
W_SD_UM = 0.5
H_BODY_UM = 1.2              # deeper than the 0.75 µm p-well
WIDTH_UM = 2 * W_SD_UM + L_GATE_UM
VGS_STEP = 0.02
VGS_END = 1.8

_Z_STEP_UM = 5e-4            # 1-D design grid
_Z_MAX_UM = 1.5


# =============================================================================
# Reference
# =============================================================================
def load_reference(l_um: float = L_GATE_UM) -> dict:
    """The ngspice-extracted SKY130 row for gate length ``l_um``."""
    ref = json.loads(REFERENCE_JSON.read_text())
    for row in ref["results"]:
        if math.isclose(row["L_um"], l_um):
            return row
    raise KeyError(f"no reference row for L = {l_um} µm")


# =============================================================================
# Material constants (the same numbers DeviceSolver uses)
# =============================================================================
def _thermal_voltage() -> float:
    return KB_J * T_K / Q_C


def _si():
    return load_material("Si").band_structure


def _eps_ox_F_cm() -> float:
    return load_material("SiO2").band_structure.permittivity_relative * EPS0_F_CM


def n_poly_flat_band_shift_V() -> float:
    """``flat_band_shift_V`` for a degenerate n+ poly gate.

    DeviceSolver pins the gate Potential to V_gate − vfb, with Potential
    referenced to the intrinsic level (n = n_i·exp(ψ/V_t)). A gate of
    work function φ_m then needs vfb = φ_m − χ − (E_c − E_i), and
    E_c − E_i = V_t·ln(N_c/n_i). Degenerate n+ poly has φ_m = χ.
    """
    bs = _si()
    return -_thermal_voltage() * math.log(bs.Nc_cm3_300K / bs.ni_cm3_300K)


# =============================================================================
# 1-D profiles (depth z measured down from the Si surface, in µm)
# =============================================================================
def pwell_cm3(z_um) -> np.ndarray:
    """SKY130 p-well design-criteria profile (without the background)."""
    z = np.asarray(z_um, dtype=float)
    return PWELL_PEAK_CM3 * np.exp(-((z - PWELL_PEAK_DEPTH_UM) / PWELL_YCHAR_UM) ** 2)


def anneal_sigma_um(species: str) -> float:
    """Intrinsic diffusion length √(2·D·t) of the stand-in anneal [µm]."""
    D = diffusivity_intrinsic(species, temperature_celsius_to_kelvin(ANNEAL_T_C))
    return math.sqrt(2.0 * D * ANNEAL_T_S) / UM_TO_CM


def implant_profile_cm3(species: str, energy_keV: float, dose_cm2: float,
                        z_um: np.ndarray) -> np.ndarray:
    """Annealed 1-D implant profile in the Si below the gate oxide.

    The implant depth is measured from the top of the stack, i.e. TOX
    above the Si surface (the oxide is crossed with Si stopping, as
    ``apply_implant`` does). The anneal is a Gaussian of the intrinsic
    diffusion length with a no-flux wall at the Si surface.
    """
    depth_um, dens_per_um = pearson_density(moments_for(species, energy_keV))
    as_implanted = dose_cm2 * np.interp(z_um + TOX_UM, depth_um, dens_per_um,
                                        left=0.0, right=0.0) / UM_TO_CM
    sigma = anneal_sigma_um(species)
    dz = float(z_um[1] - z_um[0])
    if sigma < 0.1 * dz:
        return as_implanted
    return gaussian_filter1d(as_implanted, sigma / dz, mode="mirror")


def design_grid() -> np.ndarray:
    return np.arange(0.0, _Z_MAX_UM + _Z_STEP_UM / 2, _Z_STEP_UM)


def channel_acceptors_cm3(z_um: np.ndarray, vt_dose_cm2: float) -> np.ndarray:
    return (BACKGROUND_NA_CM3 + pwell_cm3(z_um)
            + implant_profile_cm3(VT_SPECIES, VT_ENERGY_KEV, vt_dose_cm2, z_um))


# =============================================================================
# First-order (depletion-approximation) long-channel Vth for a 1-D profile
# =============================================================================
def long_channel_vth(z_um: np.ndarray, na_cm3: np.ndarray, tox_um: float,
                     vfb_V: float) -> tuple[float, float]:
    """Threshold voltage [V] and depletion width [µm] for acceptor
    profile ``na_cm3(z)``, by the depletion approximation.

    Threshold: surface electron density equals the surface acceptor
    density, so ψ(0) = φ_F(N_s) above the intrinsic level, while the
    neutral depletion edge sits at ψ(W) = −φ_F(N(W)). Poisson with zero
    field at W gives φ_F(N_s) + φ_F(N(W)) = (q/ε_s)∫₀ᵂ z·N dz, which
    fixes W; the depletion charge Q_B = q∫₀ᵂ N dz then gives

        Vth = vfb + φ_F(N_s) + Q_B / C_ox.

    For uniform doping this is the textbook φ_MS + 2φ_F + Q_B/C_ox.
    """
    bs = _si()
    vt = _thermal_voltage()
    eps_si = bs.permittivity_relative * EPS0_F_CM
    z_cm = np.asarray(z_um, dtype=float) * UM_TO_CM
    na = np.asarray(na_cm3, dtype=float)
    phi_f = vt * np.log(na / bs.ni_cm3_300K)
    dz = np.diff(z_cm)
    q1 = np.concatenate([[0.0], np.cumsum(0.5 * (na[1:] + na[:-1]) * dz)])
    zn = z_cm * na
    m1 = np.concatenate([[0.0], np.cumsum(0.5 * (zn[1:] + zn[:-1]) * dz)])
    g = Q_C * m1 / eps_si - (phi_f[0] + phi_f)
    k = np.flatnonzero(g >= 0.0)
    if len(k) == 0 or k[0] == 0:
        raise ValueError("depletion edge not bracketed by the design grid")
    k = int(k[0])
    t = -g[k - 1] / (g[k] - g[k - 1])
    w_cm = z_cm[k - 1] + t * (z_cm[k] - z_cm[k - 1])
    q_b = Q_C * (q1[k - 1] + t * (q1[k] - q1[k - 1]))
    c_ox = _eps_ox_F_cm() / (tox_um * UM_TO_CM)
    return float(vfb_V + phi_f[0] + q_b / c_ox), float(w_cm / UM_TO_CM)


def design_vt_dose(target_vth_V: float) -> float:
    """Boron dose [cm⁻²] whose design Vth equals ``target_vth_V``."""
    z = design_grid()
    vfb = n_poly_flat_band_shift_V()

    def miss(log_dose):
        na = channel_acceptors_cm3(z, 10.0 ** log_dose)
        return long_channel_vth(z, na, TOX_UM, vfb)[0] - target_vth_V

    return float(10.0 ** brentq(miss, 11.0, 14.0, xtol=1e-6))


def junction_depth_um(z_um: np.ndarray, nd_cm3: np.ndarray,
                      na_cm3: np.ndarray) -> float:
    """Deepest depth where net doping changes from n to p."""
    net = nd_cm3 - na_cm3
    k = np.flatnonzero((net[:-1] > 0) & (net[1:] <= 0))
    if len(k) == 0:
        raise ValueError("no n/p junction in the profile")
    k = int(k[-1])
    t = net[k] / (net[k] - net[k + 1])
    return float(z_um[k] + t * (z_um[k + 1] - z_um[k]))


def design_sd_energy_keV(vt_dose_cm2: float) -> float:
    """As energy [keV] whose annealed S/D junction lands at SD_XJ_UM."""
    z = design_grid()
    na = channel_acceptors_cm3(z, vt_dose_cm2)

    def miss(e_keV):
        nd = implant_profile_cm3(SD_SPECIES, e_keV, SD_DOSE_CM2, z)
        return junction_depth_um(z, nd, na) - SD_XJ_UM

    return float(brentq(miss, 10.0, 200.0, xtol=1e-3))


# =============================================================================
# 2-D process + device
# =============================================================================
def build_structure(vfb_V: float) -> Structure:
    """Substrate + gate oxide + S/D windows; no doping beyond the background."""
    top = H_BODY_UM + TOX_UM
    return (Structure(width_um=WIDTH_UM, name="sky130_nfet_check")
            .add_substrate("p_body", H_BODY_UM, Material.SI,
                           doping_Na=BACKGROUND_NA_CM3)
            .add_layer("oxide", TOX_UM, Material.SIO2)
            .add_region("source_window", 0.0, W_SD_UM, H_BODY_UM, top, Material.SI)
            .add_region("drain_window", WIDTH_UM - W_SD_UM, WIDTH_UM,
                        H_BODY_UM, top, Material.SI)
            .add_contact("source", 0.0, W_SD_UM, "oxide", surface="top")
            .add_contact("drain", WIDTH_UM - W_SD_UM, WIDTH_UM, "oxide",
                         surface="top")
            .add_contact("gate", W_SD_UM, W_SD_UM + L_GATE_UM, "oxide",
                         surface="top", flat_band_shift_V=vfb_V)
            .add_contact("body", 0.0, WIDTH_UM, "p_body", surface="bottom"))


def build_recipe(vt_dose_cm2: float, sd_energy_keV: float) -> Recipe:
    src = (0.0, W_SD_UM)
    drn = (WIDTH_UM - W_SD_UM, WIDTH_UM)
    return (Recipe("sky130_nfet_standin")
            .implant(VT_SPECIES, VT_ENERGY_KEV, vt_dose_cm2)
            .implant(SD_SPECIES, sd_energy_keV, SD_DOSE_CM2, window_x_um=src)
            .implant(SD_SPECIES, sd_energy_keV, SD_DOSE_CM2, window_x_um=drn)
            .anneal(ANNEAL_T_C, ANNEAL_T_S))


def add_pwell(mf: MeshField) -> None:
    """Place the SKY130 p-well profile on every node below the Si surface."""
    pts = np.asarray(mf.grid.points, dtype=float)[:, :2]
    z = H_BODY_UM - pts[:, 1]
    add = np.where(z >= 0.0, pwell_cm3(np.clip(z, 0.0, None)), 0.0)
    mf.set_species("boron", mf.get_species("boron") + add)
    mf.Na = mf.Na + add
    mf.process_history.append(ProcessStep(
        step_type="analytic_profile", species="boron",
        parameters={"peak_cm3": PWELL_PEAK_CM3,
                    "peak_depth_um": PWELL_PEAK_DEPTH_UM,
                    "ychar_um": PWELL_YCHAR_UM,
                    "source": "SKY130 assumptions.rst Table 3a"}))


def _vertical_cut(mf: MeshField, x_um: float, tol_um: float = 0.02):
    pts = np.asarray(mf.grid.points, dtype=float)[:, :2]
    sel = np.flatnonzero((np.abs(pts[:, 0] - x_um) < tol_um)
                         & (pts[:, 1] <= H_BODY_UM + 1e-9))
    order = sel[np.argsort(H_BODY_UM - pts[sel, 1])]
    z = H_BODY_UM - pts[order, 1]
    z, first = np.unique(np.round(z, 6), return_index=True)
    return z, mf.Nd[order][first], mf.Na[order][first]


def run_check(mesh_size_um: float = 0.01, *, vgs_step: float = VGS_STEP,
              verbose: bool = True) -> dict:
    """Design, build, simulate and compare. Returns a results dict.

    ``mesh_size_um`` is the bulk element size; DSL meshing halves it at
    the Si/SiO2 interface. The default 10 nm (5 nm at the interface) is
    the coarsest mesh on which the simulated gm reaches its maximum inside
    the 0–1.8 V sweep; see README.md for the refinement study.
    """
    from opentcad.device.models import Klaassen, Lombardi
    from opentcad.device.physics import PhysicsConfig
    from opentcad.device.solver import DeviceSolver
    from opentcad.process import run_recipe

    ref = load_reference(L_GATE_UM)
    target = ref["Vth_lin_ELR_V"]
    vfb = n_poly_flat_band_shift_V()
    vt_dose = design_vt_dose(target)
    sd_energy = design_sd_energy_keV(vt_dose)

    z = design_grid()
    na_design = channel_acceptors_cm3(z, vt_dose)
    vth_design, w_dep = long_channel_vth(z, na_design, TOX_UM, vfb)
    if verbose:
        print(f"Design: n+ poly vfb = {vfb:.4f} V; Vt implant {VT_SPECIES} "
              f"{VT_ENERGY_KEV:g} keV, {vt_dose:.3e} cm⁻² → design Vth "
              f"{vth_design:.3f} V (W_dep {w_dep*1e3:.1f} nm, "
              f"N_s {na_design[0]:.2e} cm⁻³); S/D {SD_SPECIES} "
              f"{sd_energy:.1f} keV, {SD_DOSE_CM2:.0e} cm⁻²")

    out = run_recipe(build_structure(vfb), build_recipe(vt_dose, sd_energy),
                     mesh_size_um=mesh_size_um)
    mf = out.meshfield
    add_pwell(mf)

    zc, ndc, nac = _vertical_cut(mf, WIDTH_UM / 2)
    zs, nds, nas = _vertical_cut(mf, W_SD_UM / 2)
    xj_tcad = junction_depth_um(zs, nds, nas)
    if verbose:
        print(f"Mesh {mesh_size_um} µm: {mf.n_cells} cells, {mf.n_points} "
              f"nodes; channel N_s {nac[0]:.2e} cm⁻³; S/D xj "
              f"{xj_tcad*1e3:.1f} nm (SKY130 {SD_XJ_UM*1e3:.0f} nm)")

    physics = PhysicsConfig(mobility=Lombardi(base=Klaassen()))
    solver = DeviceSolver(mf, {"Silicon": load_material("Si"),
                               "SiO2": load_material("SiO2")},
                          physics=physics)
    vgs, ids = solver.iv_sweep("gate", "source", v_start=0.0,
                               v_end=VGS_END, v_step=vgs_step,
                               hold_contacts={"drain": VDS_LIN, "body": 0.0},
                               measure_contact="drain")
    import devsim as ds
    for d in list(ds.get_device_list()):
        ds.delete_device(device=d)

    vgs = np.asarray(vgs, dtype=float)
    ids = np.abs(np.asarray(ids, dtype=float))
    vth_elr = vth_max_gm(vgs, ids, VDS_LIN)
    i_crit_A_per_cm = 1e-3 / L_GATE_UM      # 100 nA·W/L per cm of width
    vth_cc = vth_constant_current(vgs, ids, i_crit_A_per_cm)
    err = (vth_elr - target) / target
    res = {
        "mesh_size_um": mesh_size_um,
        "vgs_step_V": vgs_step,
        "vfb_V": vfb,
        "vt_dose_cm2": vt_dose,
        "sd_energy_keV": sd_energy,
        "vth_design_V": vth_design,
        "vth_tcad_elr_V": vth_elr,
        "vth_tcad_cc_V": vth_cc,
        "vth_ref_elr_V": target,
        "vth_ref_cc_V": ref["Vth_lin_cc_V"],
        "rel_error_elr": err,
        "passed": abs(err) <= PASS_TOLERANCE,
        "xj_tcad_um": xj_tcad,
        "channel_Ns_tcad_cm3": float(nac[0]),
        "channel_Ns_design_cm3": float(na_design[0]),
        "vgs_V": vgs.tolist(),
        "id_A_per_cm": ids.tolist(),
        "channel_cut": {"z_um": zc.tolist(), "Na_cm3": nac.tolist(),
                        "Nd_cm3": ndc.tolist()},
    }
    if verbose:
        print(f"TCAD Vth (max-gm) {vth_elr:.3f} V vs SKY130 {target:.3f} V "
              f"→ {err*100:+.1f} %  ({'PASS' if res['passed'] else 'FAIL'}, "
              f"±{PASS_TOLERANCE*100:.0f} %);  constant-current "
              f"{vth_cc:.3f} V vs {ref['Vth_lin_cc_V']:.3f} V")
    return res


def _plot(res: dict, path: Path) -> None:
    import matplotlib.pyplot as plt
    ref = json.loads(REFERENCE_JSON.read_text())
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    cut = res["channel_cut"]
    z = design_grid()
    axes[0].semilogy(np.asarray(cut["z_um"]) * 1e3, cut["Na_cm3"], "o",
                     ms=3, label="TCAD mesh (channel centre)")
    axes[0].semilogy(z * 1e3, channel_acceptors_cm3(z, res["vt_dose_cm2"]),
                     "-", lw=1, label="1-D design profile")
    axes[0].set_xlim(0, 900)
    axes[0].set_ylim(1e14, 1e19)
    axes[0].set_xlabel("depth below Si surface [nm]")
    axes[0].set_ylabel("Na [cm⁻³]")
    axes[0].set_title("Channel acceptors (Vt implant + SKY130 p-well)")
    axes[0].legend(fontsize=8)
    axes[0].grid(True, which="both", alpha=0.3)

    vgs = np.asarray(res["vgs_V"])
    ids = np.asarray(res["id_A_per_cm"]) * 1e-4      # A/cm → A/µm
    axes[1].semilogy(vgs, ids, "o-", ms=3, label="OpenTCAD (A/µm)")
    axes[1].axvline(res["vth_tcad_elr_V"], color="tab:blue", ls=":", lw=1)
    axes[1].axvline(res["vth_ref_elr_V"], color="k", ls="--", lw=1,
                    label=f"SKY130 Vth {res['vth_ref_elr_V']:.3f} V")
    band = (res["vth_ref_elr_V"] * (1 - PASS_TOLERANCE),
            res["vth_ref_elr_V"] * (1 + PASS_TOLERANCE))
    axes[1].axvspan(*band, color="tab:green", alpha=0.1, label="±20 %")
    axes[1].set_xlabel("Vgs [V]")
    axes[1].set_ylabel("|Id| [A/µm]")
    axes[1].set_title(f"Id–Vgs, Vds = 50 mV, L = 1 µm: Vth "
                      f"{res['vth_tcad_elr_V']:.3f} V "
                      f"({res['rel_error_elr']*100:+.1f} %)")
    axes[1].legend(fontsize=8, loc="lower right")
    axes[1].grid(True, which="both", alpha=0.3)
    fig.suptitle(f"SKY130 nfet_01v8 Vth check — reference: "
                 f"{ref['pdk']['corner']} model card, sky130_fd_pr "
                 f"{ref['pdk']['sky130_fd_pr_commit'][:7]}", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=120)


def main() -> None:
    res = run_check()
    _plot(res, HERE / "vth_check.png")
    summary = {k: v for k, v in res.items()
               if k not in ("vgs_V", "id_A_per_cm", "channel_cut")}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
