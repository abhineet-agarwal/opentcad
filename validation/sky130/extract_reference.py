"""Extract SKY130 sky130_fd_pr__nfet_01v8 reference metrics from the PDK's
own BSIM4 model cards via ngspice, into nfet_01v8_tt_reference.json.

Usage: python -m validation.sky130.extract_reference [work_dir]
Needs ngspice and an open_pdks install at $PDK_ROOT/sky130A
(default /usr/local/share/pdk). Decks, raw data and logs go to work_dir
(default: a temporary directory).

Per gate length (W = 10 um, tt corner, 26.85 C = 300 K, body = source = 0):
  * linear Id-Vgs at Vds = 50 mV  -> Vth by max-gm linear extrapolation
    and by constant current (Id = 100 nA * W/L), using the same
    opentcad.device.extract functions the TCAD check uses, plus the
    minimum subthreshold swing.
  * saturation Id-Vgs at Vds = 1.8 V -> constant-current Vth_sat, Ion at
    Vgs = 1.8 V, DIBL from the two constant-current Vths.
  * body effect, for L in BODY_EFFECT_L_UM: the constant-current Vth at
    Vds = 50 mV for each body bias in VBS.

The curves themselves, every CURVE_STEP volts, go to nfet_01v8_tt_curves.json
(the target of the mobility calibration, ``calibrate_mobility.py``).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from opentcad.device.extract import vth_constant_current, vth_max_gm

OUT_JSON = Path(__file__).resolve().parent / "nfet_01v8_tt_reference.json"
OUT_CURVES = Path(__file__).resolve().parent / "nfet_01v8_tt_curves.json"
PDK = Path(os.environ.get("PDK_ROOT", "/usr/local/share/pdk")) / "sky130A"
LIB = PDK / "libs.tech/ngspice/sky130.lib.spice"
SPINIT = PDK / "libs.tech/ngspice/spinit"
CORNER = "tt"
TEMP_C = 26.85
W_UM = 10.0
L_UM = [0.15, 0.18, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 20.0]
VDS_LIN = 0.05
VDS_SAT = 1.8
VG_STEP = 0.002
VBS = [0.0, -0.45, -0.9, -1.35, -1.8]   # body bias for the body-effect table
BODY_EFFECT_L_UM = [1.0, 20.0]
CURVE_STEP = 0.01             # V; spacing of the saved curves


def run_sweep(work: Path, l_um: float, vds: float,
              vbs: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    tag = f"L{l_um:g}_Vd{vds:g}" + (f"_Vb{vbs:g}" if vbs else "")
    tag = tag.replace(".", "p").replace("-", "m")
    deck = f"""* SKY130 nfet_01v8 Id-Vgs, W={W_UM} L={l_um} Vds={vds} Vbs={vbs}
.lib "{LIB}" {CORNER}
.temp {TEMP_C}
Vd d 0 {vds}
Vg g 0 0
Vb b 0 {vbs}
XM1 d g 0 b sky130_fd_pr__nfet_01v8 w={W_UM} l={l_um} nf=1
.control
set wr_vecnames
set wr_singlescale
dc Vg 0 1.8 {VG_STEP}
wrdata {tag}.dat -i(Vd)
quit
.endc
.end
"""
    (work / f"{tag}.spice").write_text(deck)
    res = subprocess.run(["ngspice", "-b", f"{tag}.spice"], cwd=work,
                         capture_output=True, text=True, timeout=300)
    (work / f"{tag}.log").write_text(res.stdout + res.stderr)
    dat = work / f"{tag}.dat"
    if res.returncode or not dat.is_file():
        raise RuntimeError(f"ngspice failed for {tag}; see {work / (tag + '.log')}")
    if re.search(r"could not find a valid modelname", res.stdout + res.stderr, re.I):
        raise RuntimeError(f"no model bin for {tag}")
    vg, idr = np.loadtxt(dat, skiprows=1).T
    return vg, idr


def min_ss(vg, idr, i_upper):
    """Minimum dVg/dlog10(Id) [mV/dec] over the subthreshold range
    (Id between 1e-13 A and i_upper)."""
    sel = (idr > 1e-13) & (idr < i_upper)
    lg = np.log10(idr[sel])
    s = np.gradient(vg[sel], lg) * 1e3
    s = s[np.isfinite(s) & (s > 0)]
    return float(s.min()) if len(s) else float("nan")


def main(work_dir: str | None = None) -> None:
    if shutil.which("ngspice") is None or not LIB.is_file():
        raise SystemExit("needs ngspice and PDK_ROOT/sky130A")
    work = Path(work_dir or tempfile.mkdtemp(prefix="sky130_ref_")).resolve()
    work.mkdir(parents=True, exist_ok=True)
    shutil.copy(SPINIT, work / ".spiceinit")
    ver = subprocess.run(["ngspice", "-v"], capture_output=True, text=True).stdout
    nodeinfo = json.loads((PDK / ".config/nodeinfo.json").read_text())

    rows = []
    curves = []
    for l_um in L_UM:
        i_crit = 100e-9 * W_UM / l_um
        vg, il = run_sweep(work, l_um, VDS_LIN)
        _, isat = run_sweep(work, l_um, VDS_SAT)
        v_elr = vth_max_gm(vg, il, VDS_LIN)
        gm_pk = float(np.max(np.gradient(il, vg)))
        v_cc_lin = vth_constant_current(vg, il, i_crit)
        v_cc_sat = vth_constant_current(vg, isat, i_crit)
        rows.append({
            "L_um": l_um,
            "Vth_lin_ELR_V": round(v_elr, 4),
            "Vth_lin_cc_V": round(v_cc_lin, 4),
            "Vth_sat_cc_V": round(v_cc_sat, 4),
            "DIBL_mV_per_V": round((v_cc_lin - v_cc_sat) / (VDS_SAT - VDS_LIN) * 1e3, 1),
            "SS_min_mV_per_dec": round(min_ss(vg, il, i_crit), 1),
            "gm_max_lin_S": gm_pk,
            "Ion_sat_A_per_um": float(isat[-1] / W_UM),
            "Ioff_sat_A_per_um": float(isat[0] / W_UM),
        })
        every = round(CURVE_STEP / VG_STEP)
        curves.append({"L_um": l_um,
                       "Id_lin_A": [float(f"{x:.6e}") for x in il[::every]],
                       "Id_sat_A": [float(f"{x:.6e}") for x in isat[::every]]})
        r = rows[-1]
        print(f"L={l_um:6.2f} um  Vth_ELR={r['Vth_lin_ELR_V']:.3f}  "
              f"Vth_cc,lin={r['Vth_lin_cc_V']:.3f}  Vth_cc,sat={r['Vth_sat_cc_V']:.3f}  "
              f"DIBL={r['DIBL_mV_per_V']:6.1f} mV/V  SS={r['SS_min_mV_per_dec']:5.1f} mV/dec  "
              f"Ion={r['Ion_sat_A_per_um']*1e6:7.1f} uA/um  Ioff={r['Ioff_sat_A_per_um']:.2e} A/um")

    body = []
    for l_um in BODY_EFFECT_L_UM:
        i_crit = 100e-9 * W_UM / l_um
        vths = []
        for vbs in VBS:
            vg, il = run_sweep(work, l_um, VDS_LIN, vbs)
            vths.append(round(vth_constant_current(vg, il, i_crit), 4))
        body.append({"L_um": l_um, "Vbs_V": VBS, "Vth_lin_cc_V": vths})
        print(f"L={l_um:6.2f} um  body effect: Vth_cc,lin " + ", ".join(
            f"{vt:.3f} V @ {vb:+.2f}" for vt, vb in zip(vths, VBS)))

    ref = {
        "device": "sky130_fd_pr__nfet_01v8",
        "source": "SkyWater SKY130 BSIM4 model cards, evaluated with ngspice",
        "pdk": {
            "path": str(PDK),
            "open_pdks_commit": nodeinfo.get("reference", {}).get("open_pdks"),
            "sky130_fd_pr_commit": nodeinfo.get("reference", {}).get("sky130_fd_pr"),
            "corner": CORNER,
            "toxe_nm_from_model_card": 4.148,
        },
        "simulator": ver.strip().splitlines()[1].strip("* ") if ver else "ngspice",
        "conditions": {
            "W_um": W_UM, "temperature_C": TEMP_C, "Vds_lin_V": VDS_LIN,
            "Vds_sat_V": VDS_SAT, "Vbs_V": 0.0, "Vgs_step_V": VG_STEP,
        },
        "methods": {
            "Vth_lin_ELR": "max-gm linear extrapolation at Vds_lin: Vg* - Id*/gm* - Vds/2",
            "Vth_cc": "Vgs where Id = 100 nA * W/L (log-interpolated)",
            "DIBL": "(Vth_lin_cc - Vth_sat_cc) / (Vds_sat - Vds_lin)",
            "SS_min": "min dVgs/dlog10(Id) for 1e-13 A < Id < 100 nA*W/L at Vds_lin",
            "body_effect": "Vth_cc at Vds_lin for each body bias Vbs (source at 0 V)",
        },
        "results": rows,
        "body_effect": body,
    }
    OUT_JSON.write_text(json.dumps(ref, indent=2) + "\n")
    OUT_CURVES.write_text(json.dumps({
        "device": ref["device"], "source": ref["source"], "pdk": ref["pdk"],
        "simulator": ref["simulator"], "conditions": ref["conditions"],
        "units": {"Vgs": "V", "Id": "A, drain current for W = W_um (body and source at 0 V)"},
        "Vgs_V": [round(float(v), 4) for v in vg[::every]],
        "curves": curves,
    }) + "\n")
    print(f"\nwrote {OUT_JSON} and {OUT_CURVES.name}  (decks and logs in {work})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
