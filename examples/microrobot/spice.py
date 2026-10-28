"""Optional ngspice adapter for a SKY130 oscillator feasibility experiment.

This RC-loaded ring is our topology choice, not the paper's PTAT relaxation
oscillator. It establishes model loading, oscillation and supply/power costs.
Ideal timing R/C and a deliberately asymmetric power ramp seed startup.
It is not a validated autonomous startup or actuator-driver design.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import numpy as np


def run_ring(output_dir, *, corner="tt", supply_V=1.6, temperature_C=27):
    if corner not in {"tt", "ss", "ff", "sf", "fs"}:
        raise ValueError("Unsupported process corner")
    if not 1.2 <= supply_V <= 1.95 or not -40 <= temperature_C <= 125:
        raise ValueError("Outside this experiment's supply/temperature sweep")
    executable = shutil.which("ngspice")
    if executable is None:
        raise FileNotFoundError("ngspice is not installed")
    pdk = Path(os.environ.get("PDK_ROOT", "/usr/local/share/pdk")) / "sky130A"
    library = pdk / "libs.tech/ngspice/sky130.lib.spice"
    if not library.is_file():
        raise FileNotFoundError(f"Set PDK_ROOT; missing {library}")
    dest = Path(output_dir).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    (dest / ".spiceinit").write_text("set ngbehavior=hsa\nset num_threads=1\n")
    deck = f"""* Our three-stage RC-loaded SKY130 ring; preliminary feasibility only
.lib "{library}" {corner}
.temp {temperature_C}
Vpower vdd 0 PWL(0 0 1u 0 11u {supply_V})
.subckt inv a y vdd vss
Xp y a vdd vdd sky130_fd_pr__pfet_01v8 w=1.26 l=1
Xn y a vss vss sky130_fd_pr__nfet_01v8 w=0.42 l=1
.ends inv
X1 c x1 vdd 0 inv
X2 a x2 vdd 0 inv
X3 b x3 vdd 0 inv
Xbuffer a out vdd 0 inv
R1 x1 a 1Meg
R2 x2 b 1Meg
R3 x3 c 1Meg
C1 a 0 10p
C2 b 0 10p
C3 c 0 10p
Cload out 0 100f
.ic v(a)=0 v(b)=0 v(c)=0.01
.options reltol=1e-5 abstol=1e-15
.control
set wr_vecnames
set wr_singlescale
tran 100n 3m uic
wrdata ring.dat v(vdd) v(out) v(a) v(b) i(Vpower)
quit
.endc
.end
"""
    (dest / "ring.spice").write_text(deck)
    result = subprocess.run([executable, "-b", "ring.spice"], cwd=dest,
                            capture_output=True, text=True, timeout=120)
    (dest / "ngspice.log").write_text(result.stdout + result.stderr)
    if result.returncode or not (dest / "ring.dat").is_file():
        raise RuntimeError(f"ngspice failed; inspect {dest / 'ngspice.log'}")
    data = np.loadtxt(dest / "ring.dat", skiprows=1)
    t, vdd, a, b, c, current = data.T
    select = t > 1e-3
    crossings = np.flatnonzero((a[:-1] < supply_V / 2)
                              & (a[1:] >= supply_V / 2) & select[1:])
    if len(crossings) < 5 or np.ptp(a[select]) < supply_V * 0.8:
        raise RuntimeError("No sustained full-swing oscillation detected")
    times = t[crossings] + (supply_V / 2 - a[crossings]) * (
        t[crossings + 1] - t[crossings]) / (a[crossings + 1] - a[crossings])
    power = float(-np.trapezoid((vdd * current)[select], t[select])
                  / np.ptp(t[select]))
    info = {"corner": corner, "supply_V": supply_V, "temperature_C": temperature_C,
            "frequency_Hz": float(1 / np.mean(np.diff(times))),
            "mean_power_W": power, "minimum_output_V": float(a[select].min()),
            "maximum_output_V": float(a[select].max()),
            "library_sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
            "ngspice_version": subprocess.run([executable, "--version"],
                capture_output=True, text=True).stdout.strip(),
            "startup": "seeded initial condition and specified supply ramp",
            "timing_passives": "ideal 1 Mohm / 10 pF per stage; area unresolved"}
    nodeinfo = pdk / ".config/nodeinfo.json"
    if nodeinfo.is_file():
        info["pdk_nodeinfo"] = json.loads(nodeinfo.read_text())
    (dest / "metrics.json").write_text(json.dumps(info, indent=2) + "\n")
    return info, data
